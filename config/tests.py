import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse, JsonResponse
from django.middleware.security import SecurityMiddleware
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from ai_assistant.throttling import (
    AIStreamSlot,
    acquire_ai_request_slot,
    reserve_ai_request_quota,
)
from ai_assistant.views import _rate_limited_response
from config.client_ip import get_client_ip
from config.proxy import TrustedProxyHeadersMiddleware
from config.rate_limit import RateLimitMiddleware


class CleanMigrationSeedTests(SimpleTestCase):
    def test_clean_sqlite_database_migrates_and_seeds(self):
        base_dir = Path(__file__).resolve().parent.parent

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "clean.sqlite3"
            env = os.environ.copy()

            for name in (
                "DB_HOST",
                "DB_NAME",
                "DB_USER",
                "DB_PASSWORD",
                "DB_PORT",
                "REDIS_URL",
            ):
                env.pop(name, None)

            env.update(
                {
                    "DJANGO_ENV": "development",
                    "SQLITE_DATABASE_PATH": str(db_path),
                    "RATE_LIMIT_ENABLED": "False",
                    "PYTHONIOENCODING": "utf-8",
                }
            )

            migrate = subprocess.run(
                [
                    sys.executable,
                    "manage.py",
                    "migrate",
                    "--noinput",
                    "--verbosity",
                    "0",
                ],
                cwd=base_dir,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )

            self.assertEqual(
                migrate.returncode,
                0,
                msg=migrate.stdout + migrate.stderr,
            )

            fixture = subprocess.run(
                [
                    sys.executable,
                    "manage.py",
                    "loaddata",
                    "data/fixtures/base_restaurant.json",
                    "--verbosity",
                    "0",
                ],
                cwd=base_dir,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )

            self.assertEqual(
                fixture.returncode,
                0,
                msg=fixture.stdout + fixture.stderr,
            )

            seed = subprocess.run(
                [
                    sys.executable,
                    "manage.py",
                    "seed_project_data",
                    "--verbosity",
                    "0",
                ],
                cwd=base_dir,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )

            self.assertEqual(seed.returncode, 0, msg=seed.stdout + seed.stderr)

            translations = subprocess.run(
                [
                    sys.executable,
                    "manage.py",
                    "check_menu_translations",
                    "--restaurant-slug",
                    "caesar-company",
                ],
                cwd=base_dir,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )

            self.assertEqual(
                translations.returncode,
                0,
                msg=translations.stdout + translations.stderr,
            )

            connection = sqlite3.connect(db_path)
            cursor = connection.cursor()
            applied_migrations = set(
                cursor.execute(
                    "select app, name from django_migrations where app in ('menu', 'orders')"
                ).fetchall()
            )
            tables = {
                row[0]
                for row in cursor.execute(
                    "select name from sqlite_master where type = 'table'"
                ).fetchall()
            }
            table_count = cursor.execute("select count(*) from orders_table").fetchone()[0]
            dish_count = cursor.execute("select count(*) from menu_dish").fetchone()[0]
            connection.close()

        self.assertIn(("menu", "0006_alter_category_options_and_more"), applied_migrations)
        self.assertIn(("orders", "0004_table_qr_token"), applied_migrations)
        self.assertIn(("orders", "0005_table_qr_token_security"), applied_migrations)
        self.assertIn("orders_order", tables)
        self.assertIn("orders_table", tables)
        self.assertGreaterEqual(table_count, 1)
        self.assertGreater(dish_count, 0)


class UiPreferencesContextTests(SimpleTestCase):
    def test_ui_language_cookie_is_normalized(self):
        from django.test import RequestFactory

        from config.context_processors import ui_preferences

        request = RequestFactory().get("/", HTTP_COOKIE="cc_language=tr")

        self.assertEqual(ui_preferences(request)["ui_language"], "tr")

    def test_invalid_ui_language_cookie_falls_back_to_russian(self):
        from django.test import RequestFactory

        from config.context_processors import ui_preferences

        request = RequestFactory().get("/", HTTP_COOKIE="cc_language=de")

        self.assertEqual(ui_preferences(request)["ui_language"], "ru")


class ClientIPTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(
        TRUST_PROXY_HEADERS=True,
        TRUSTED_PROXY_CIDRS=["172.16.0.0/12"],
    )
    def test_untrusted_direct_client_cannot_spoof_forwarded_ip(self):
        request = self.factory.get(
            "/",
            REMOTE_ADDR="203.0.113.9",
            HTTP_X_FORWARDED_FOR="198.51.100.12",
            HTTP_X_REAL_IP="198.51.100.13",
        )

        self.assertEqual(get_client_ip(request), "203.0.113.9")

    @override_settings(
        TRUST_PROXY_HEADERS=True,
        TRUSTED_PROXY_CIDRS=["172.16.0.0/12"],
    )
    def test_trusted_proxy_chain_returns_nearest_untrusted_client(self):
        request = self.factory.get(
            "/",
            REMOTE_ADDR="172.18.0.5",
            HTTP_X_FORWARDED_FOR="198.51.100.12, 172.18.0.4",
        )

        self.assertEqual(get_client_ip(request), "198.51.100.12")

    @override_settings(
        TRUST_PROXY_HEADERS=True,
        TRUSTED_PROXY_CIDRS=["172.16.0.0/12"],
    )
    def test_proxy_middleware_removes_headers_from_untrusted_peer(self):
        def response_for(request):
            return JsonResponse(
                {
                    "forwarded_for": request.META.get("HTTP_X_FORWARDED_FOR"),
                    "forwarded_proto": request.META.get("HTTP_X_FORWARDED_PROTO"),
                    "trusted": request.resto_proxy_headers_trusted,
                }
            )

        middleware = TrustedProxyHeadersMiddleware(response_for)
        request = self.factory.get(
            "/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="198.51.100.12",
            HTTP_X_FORWARDED_PROTO="https",
        )
        response = middleware(request)

        self.assertJSONEqual(
            response.content,
            {
                "forwarded_for": None,
                "forwarded_proto": None,
                "trusted": False,
            },
        )

    @override_settings(
        TRUST_PROXY_HEADERS=True,
        TRUSTED_PROXY_CIDRS=["172.16.0.0/12"],
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
        SECURE_SSL_REDIRECT=True,
        ALLOWED_HOSTS=["example.com"],
    )
    def test_untrusted_peer_cannot_spoof_https(self):
        app = TrustedProxyHeadersMiddleware(
            SecurityMiddleware(lambda _request: HttpResponse("ok"))
        )
        request = self.factory.get(
            "/private/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_HOST="example.com",
        )

        response = app(request)

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://example.com/private/")

    @override_settings(
        TRUST_PROXY_HEADERS=True,
        TRUSTED_PROXY_CIDRS=["172.16.0.0/12"],
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
        SECURE_SSL_REDIRECT=True,
        ALLOWED_HOSTS=["example.com"],
    )
    def test_trusted_proxy_can_assert_https(self):
        app = TrustedProxyHeadersMiddleware(
            SecurityMiddleware(lambda _request: HttpResponse("ok"))
        )
        request = self.factory.get(
            "/private/",
            REMOTE_ADDR="172.18.0.5",
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_HOST="example.com",
        )

        response = app(request)

        self.assertEqual(response.status_code, 200)


class SecurityHeaderTests(TestCase):
    def test_dynamic_response_has_security_policies(self):
        response = self.client.get("/health/live/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("default-src 'self'", response["Content-Security-Policy"])
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertNotIn("'unsafe-inline'", response["Content-Security-Policy"].split("script-src", 1)[1].split(";", 1)[0])
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertIn("camera=()", response["Permissions-Policy"])
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(
            response["X-Permitted-Cross-Domain-Policies"],
            "none",
        )

    def test_readiness_reports_cache_failure(self):
        with patch("config.health.cache.set", side_effect=ConnectionError):
            response = self.client.get("/health/ready/")

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["dependencies"]["cache"])
        self.assertEqual(response["Cache-Control"], "no-store")


class RateLimitFailurePolicyTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, view_name):
        request = self.factory.post(
            "/test/",
            data={"email": "user@example.com"},
            REMOTE_ADDR="203.0.113.9",
            HTTP_ACCEPT="application/json",
        )
        request.user = AnonymousUser()
        request.session = SimpleNamespace(session_key="test-session")
        request.resolver_match = SimpleNamespace(view_name=view_name)
        return request

    @override_settings(
        RATE_LIMIT_ENABLED=True,
        RATE_LIMIT_RULES={
            "test:closed": {
                "methods": ["POST"],
                "identity": "ip",
                "cache_failure": "closed",
                "limits": [{"name": "minute", "limit": 1, "window": 60}],
            }
        },
    )
    def test_closed_policy_returns_controlled_503(self):
        request = self._request("test:closed")
        middleware = RateLimitMiddleware(lambda _request: None)

        with (
            patch("config.rate_limit._increment", side_effect=ConnectionError),
            patch("config.rate_limit.logger.exception"),
        ):
            response = middleware.process_view(request, None, (), {})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(__import__("json").loads(response.content)["code"], "rate_limit_unavailable")
        self.assertEqual(response["Retry-After"], "5")

    @override_settings(
        RATE_LIMIT_ENABLED=True,
        RATE_LIMIT_RULES={
            "test:open": {
                "methods": ["POST"],
                "identity": "ip",
                "cache_failure": "open",
                "limits": [{"name": "minute", "limit": 1, "window": 60}],
            }
        },
    )
    def test_open_policy_allows_request_when_cache_is_down(self):
        request = self._request("test:open")
        middleware = RateLimitMiddleware(lambda _request: None)

        with (
            patch("config.rate_limit._increment", side_effect=ConnectionError),
            patch("config.rate_limit.logger.exception"),
        ):
            response = middleware.process_view(request, None, (), {})

        self.assertIsNone(response)


class AIStoreFailureTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(
        AI_RATE_LIMIT_IP_PER_MINUTE=10,
        AI_RATE_LIMIT_USER_PER_MINUTE=10,
        AI_DAILY_QUOTA_IP=10,
        AI_DAILY_QUOTA_USER=10,
    )
    def test_quota_store_failure_is_fail_closed(self):
        request = self.factory.post("/ai/ask/", REMOTE_ADDR="203.0.113.9")
        request.user = SimpleNamespace(is_authenticated=True, pk=12)

        with (
            patch("ai_assistant.throttling.cache.get", side_effect=ConnectionError),
            patch("ai_assistant.throttling.logger.exception"),
        ):
            decision = reserve_ai_request_quota(request, "Recommend a dish")

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "quota_store_unavailable")
        self.assertEqual(decision.retry_after, 5)

    def test_request_lease_store_failure_is_controlled(self):
        with (
            patch("ai_assistant.throttling.cache.add", side_effect=ConnectionError),
            patch("ai_assistant.throttling.logger.exception"),
        ):
            slot = acquire_ai_request_slot("0b5b909b-b13b-42dc-a0ac-e02a4366a11d")

        self.assertFalse(slot.allowed)
        self.assertEqual(slot.reason, "guard_store_unavailable")
        self.assertEqual(slot.retry_after, 5)

    def test_ai_store_failure_response_uses_503(self):
        response = _rate_limited_response(
            AIStreamSlot(
                allowed=False,
                reason="guard_store_unavailable",
                message="Temporarily unavailable",
                retry_after=5,
            )
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(__import__("json").loads(response.content)["code"], "ai_guard_unavailable")
        self.assertEqual(response["Retry-After"], "5")


class RuntimeDeploymentConfigurationTests(SimpleTestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent

    def test_web_entrypoint_does_not_run_release_tasks(self):
        entrypoint = (self.base_dir / "entrypoint.sh").read_text(encoding="utf-8")

        self.assertNotIn("manage.py migrate", entrypoint)
        self.assertNotIn("manage.py collectstatic", entrypoint)
        self.assertNotIn("seed_project_data", entrypoint)
        self.assertNotIn("import_caesar_images", entrypoint)
        self.assertIn('exec "$@"', entrypoint)

    def test_release_script_owns_schema_and_static_tasks(self):
        release_script = (self.base_dir / "ops" / "release.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("manage.py check", release_script)
        self.assertIn("manage.py migrate --noinput", release_script)
        self.assertIn("manage.py collectstatic --noinput --clear", release_script)
        self.assertNotIn("seed_project_data", release_script)
        self.assertNotIn("import_caesar_images", release_script)

    def test_docker_image_declares_unprivileged_runtime_user(self):
        dockerfile = (self.base_dir / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("ARG APP_UID=10001", dockerfile)
        self.assertIn("ARG APP_GID=10001", dockerfile)
        self.assertIn("USER resto:resto", dockerfile)

    def test_compose_has_one_shot_release_and_no_fixed_container_names(self):
        compose = (self.base_dir / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("  release:\n", compose)
        self.assertIn('command: ["/app/ops/release.sh"]', compose)
        self.assertIn('restart: "no"', compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("redis_data:/data", compose)
        self.assertNotIn("container_name:", compose)
        self.assertNotIn("IMPORT_SEED_DATA_ON_STARTUP", compose)
        self.assertNotIn("IMPORT_SEED_IMAGES_ON_STARTUP", compose)

    def test_production_uses_manifest_static_storage(self):
        env = os.environ.copy()
        env.update(
            {
                "DJANGO_ENV": "production",
                "DJANGO_DEBUG": "False",
                "DJANGO_SECRET_KEY": "production-test-secret-key-not-an-example-value",
                "DJANGO_ALLOWED_HOSTS": "example.com",
                "DJANGO_CSRF_TRUSTED_ORIGINS": "https://example.com",
                "DJANGO_TRUST_PROXY_HEADERS": "False",
                "DJANGO_SECURE_PROXY_SSL_HEADER": "False",
                "DJANGO_SECURE_SSL_REDIRECT": "False",
                "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
                "EMAIL_HOST": "smtp.example.com",
                "EMAIL_PORT": "587",
                "EMAIL_USE_TLS": "True",
                "EMAIL_USE_SSL": "False",
                "DEFAULT_FROM_EMAIL": "no-reply@example.com",
                "DB_HOST": "db",
                "DB_PORT": "5432",
                "DB_NAME": "resto_test",
                "DB_USER": "resto_test",
                "DB_PASSWORD": "unique-production-test-password",
                "REDIS_URL": "redis://redis:6379/1",
                "SITE_URL": "https://example.com",
                "YOOKASSA_MOCK": "False",
            }
        )
        env.pop("DJANGO_STATICFILES_BACKEND", None)
        env.pop("SQLITE_DATABASE_PATH", None)

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import django; django.setup(); "
                    "from django.conf import settings; "
                    "print(settings.STORAGES['staticfiles']['BACKEND'])"
                ),
            ],
            cwd=self.base_dir,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "whitenoise.storage.CompressedManifestStaticFilesStorage",
        )
