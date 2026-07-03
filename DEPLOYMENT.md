# Production deployment

The production Compose configuration separates build, release, and runtime
responsibilities:

- image build installs dependencies and copies immutable application code;
- the one-shot `release` service applies migrations and collects static files;
- the long-running `web` service starts Gunicorn only;
- seed data and seed images are imported only by explicit operator commands.

The application image runs as the unprivileged `resto` user. Its default UID
and GID are both `10001` and can be changed with `APP_UID` and `APP_GID` at
build time.

## Environment

1. Copy `.env.example` to `.env`.
2. Fill every blank required value.
3. Generate a unique `DJANGO_SECRET_KEY`.
4. Set `DJANGO_DEBUG=False`.
5. Set `DJANGO_ALLOWED_HOSTS` to the real domains plus the healthcheck host.
6. Set `DJANGO_CSRF_TRUSTED_ORIGINS` to the HTTPS origins.
7. Configure a real email delivery backend. Production must not use console,
   dummy, locmem, or file-based email backends.

PostgreSQL and Redis are exposed only on the internal Docker network. The web
service binds to `127.0.0.1:8000` by default for local administration. Public
traffic must pass through Nginx or another trusted reverse proxy.

When forwarding headers are enabled, configure both:

```env
DJANGO_TRUST_PROXY_HEADERS=True
DJANGO_TRUSTED_PROXY_CIDRS=172.16.0.0/12
```

The CIDR list must contain only the direct proxy network. Never use
`0.0.0.0/0`.

## Image reproducibility

The image names are configurable:

```env
APP_IMAGE=registry.example.com/resto/web:2026-07-03
POSTGRES_IMAGE=postgres:15-alpine
REDIS_IMAGE=redis:8-alpine
NGINX_IMAGE=nginx:1.27-alpine
```

For a real production release, pin third-party images to reviewed digests, for
example `postgres:15-alpine@sha256:...`, and promote an immutable application
image instead of rebuilding independently on every host.

## Release workflow

Build the application image once:

```bash
docker compose build web
```

Start the stateful dependencies:

```bash
docker compose up -d db redis
```

Run the one-shot release tasks:

```bash
docker compose --profile release run --rm release
```

The release container performs, in order:

```text
python manage.py check
python manage.py migrate --noinput
python manage.py collectstatic --noinput --clear
python manage.py migrate --check
```

Only after the release command succeeds, start or replace the application:

```bash
docker compose up -d web
```

With the bundled TLS proxy:

```bash
docker compose --profile tls up -d nginx
```

A failed release leaves the old web container untouched. Do not put migrations
back into the web entrypoint: multiple web replicas must never race to migrate
or rewrite the shared static volume.

## Updating an existing installation from a root-running image

Fresh named volumes inherit the correct UID/GID from the image. Older
`static_volume` or `media_volume` volumes may contain root-owned files. After
building Patch 13, stop web and run this one-time ownership repair before the
release command:

```bash
docker compose stop web
docker run --rm --user 0 --entrypoint sh \
  -v resto_static_volume:/app/staticfiles \
  -v resto_media_volume:/app/mediafiles \
  "${APP_IMAGE:-resto-web:local}" \
  -c 'chown -R 10001:10001 /app/staticfiles /app/mediafiles'
```

Use your configured UID/GID instead of `10001:10001` when they differ.

## Static files

Production uses `CompressedManifestStaticFilesStorage`. Template references are
resolved to content-hashed filenames such as:

```text
/static/js/menu-ui.4f0f0a3d2c1b.js
```

Nginx can therefore cache `/static/` for one year with `immutable`. The web
container mounts the collected static volume read-only; only the release
service writes it. `DJANGO_USE_WHITENOISE=True` remains a safe fallback when an
external proxy forwards static requests to Django.

## Seed data

Seed import is never part of container startup. For a new environment, run it
explicitly after a successful release:

```bash
docker compose exec web python manage.py seed_project_data
```

To import images explicitly:

```bash
docker compose exec web python manage.py import_caesar_images
```

Before a release, validate translated menu data:

```bash
docker compose exec web python manage.py check_menu_translations --restaurant-slug caesar-company
docker compose exec web python manage.py validate_translation_sources
```

## Runtime hardening

The `web` and `release` services use:

- UID/GID `10001:10001` by default;
- `no-new-privileges`;
- all Linux capabilities dropped;
- a read-only root filesystem;
- a small writable `/tmp` tmpfs;
- explicit writable volumes only where required.

The web process no longer writes source code or collected static files during
startup.

## Redis durability

Redis now uses AOF with `appendfsync everysec` and periodic RDB snapshots in the
persistent `redis_data` volume. This preserves rate-limit and AI budget state
across normal container restarts. Redis is still not a substitute for durable
business records; orders and idempotency remain in PostgreSQL.

## Rate limiting and proxy security

Application rate limits are shared through Redis. Authentication and AI fail
closed with HTTP 503 when the guard store is unavailable. QR menu and order
endpoints fail open because Nginx still applies edge limits and PostgreSQL
continues to enforce order idempotency.

Forwarded headers are accepted only from configured trusted proxy CIDRs.

## Browser security policies

Dynamic responses include CSP, Referrer-Policy, Permissions-Policy,
`X-Frame-Options: DENY`, and `X-Content-Type-Options: nosniff`. HSTS starts with
a conservative one-hour lifetime; increase it only after HTTPS has been
verified for every relevant host.

## Email

For SMTP:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=transactional-user
EMAIL_HOST_PASSWORD=transactional-password
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
DEFAULT_FROM_EMAIL="Caesar & Company <no-reply@example.com>"
SERVER_EMAIL=ops@example.com
```

## TLS profile

Place these files in `deploy/nginx/certs/`:

- `fullchain.pem`
- `privkey.pem`

Then start Nginx with the `tls` profile as shown in the release workflow.

## Healthchecks

- `GET /health/live/` checks the Django process;
- `GET /health/ready/` checks PostgreSQL and Redis;
- `GET /healthz/` is a backward-compatible liveness alias.

## Backups

Create a PostgreSQL custom-format dump:

```bash
sh ops/backup_postgres.sh
```

Restore only into a staging or newly created database first:

```bash
sh ops/restore_postgres.sh backups/pre-release.dump
```

Backup encryption, off-site storage, retention, and restore drills are handled
in the later storage/operations hardening package.
