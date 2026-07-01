from allauth.account.models import EmailAddress
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist
from django.db import IntegrityError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from ai_assistant.models import ChatMessage, ChatSession
from menu.models import Allergen


User = get_user_model()


class UserModelTests(TestCase):
    def test_create_user_uses_email_as_identifier(self):
        user = User.objects.create_user(
            email="Guest@Example.COM",
            password="strong-pass-123",
        )

        self.assertEqual(user.email, "Guest@example.com")
        self.assertNotEqual(user.password, "strong-pass-123")
        self.assertTrue(user.check_password("strong-pass-123"))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(str(user), "Guest@example.com")

    def test_email_is_required(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password="strong-pass-123")

    def test_email_is_unique(self):
        User.objects.create_user(email="guest@example.com", password="strong-pass-123")

        with self.assertRaises(IntegrityError):
            User.objects.create_user(email="guest@example.com", password="strong-pass-123")

    def test_username_field_does_not_exist(self):
        with self.assertRaises(FieldDoesNotExist):
            User._meta.get_field("username")

    def test_create_superuser_sets_admin_flags(self):
        user = User.objects.create_superuser(
            email="admin@example.com",
            password="strong-pass-123",
        )

        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_active)


class AccountViewTests(TestCase):
    def test_auth_pages_are_available(self):
        url_names = [
            "account_login",
            "account_signup",
            "account_reset_password",
        ]

        for url_name in url_names:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)

    def test_auth_pages_include_client_language_variants(self):
        login_response = self.client.get(reverse("account_login"))
        signup_response = self.client.get(reverse("account_signup"))

        self.assertContains(login_response, "Şifreyi göster")
        self.assertContains(login_response, "Şifreyi gizle")
        self.assertContains(login_response, "Şifrenizi mi unuttunuz?")
        self.assertContains(signup_response, "Hesap oluştur")
        self.assertContains(signup_response, "En az 8 karakter kullanın")

    def test_signup_password_errors_and_placeholders_are_russian_by_default(self):
        get_response = self.client.get(reverse("account_signup"))

        self.assertContains(get_response, 'placeholder="Пароль"')
        self.assertContains(get_response, 'placeholder="Повторите пароль"')

        post_response = self.client.post(
            reverse("account_signup"),
            {
                "email": "asd@gmail.com",
                "password1": "password",
                "password2": "password",
            },
        )

        self.assertEqual(post_response.status_code, 200)
        content = post_response.content.decode()
        error_start = content.index('<ul class="errorlist"')
        error_end = content.index("</ul>", error_start)
        error_html = content[error_start:error_end]

        self.assertContains(post_response, "Введённый пароль")
        self.assertNotIn("This password", error_html)
        self.assertNotIn("The password", error_html)

    def test_signup_creates_user_and_unverified_email_address(self):
        response = self.client.post(
            reverse("account_signup"),
            {
                "email": "new@example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )

        self.assertRedirects(response, reverse("account_email_verification_sent"))
        user = User.objects.get(email="new@example.com")
        email_address = EmailAddress.objects.get(user=user, email="new@example.com")

        self.assertFalse(email_address.verified)
        self.assertTrue(email_address.primary)

    def test_invalid_password_does_not_login_user(self):
        user = User.objects.create_user(
            email="guest@example.com",
            password="StrongPass123!",
        )
        EmailAddress.objects.create(
            user=user,
            email=user.email,
            verified=True,
            primary=True,
        )

        self.client.post(
            reverse("account_login"),
            {
                "login": user.email,
                "password": "wrong-password",
            },
        )

        self.assertNotIn("_auth_user_id", self.client.session)

    def test_verified_user_can_login_with_email(self):
        user = User.objects.create_user(
            email="guest@example.com",
            password="StrongPass123!",
        )
        EmailAddress.objects.create(
            user=user,
            email=user.email,
            verified=True,
            primary=True,
        )

        self.client.post(
            reverse("account_login"),
            {
                "login": user.email,
                "password": "StrongPass123!",
            },
        )

        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_logout_ends_session(self):
        user = User.objects.create_user(
            email="guest@example.com",
            password="StrongPass123!",
        )
        self.client.force_login(user)

        self.client.post(reverse("account_logout"))

        self.assertNotIn("_auth_user_id", self.client.session)

    def test_allergy_editor_shows_allergen_product_icons(self):
        user = User.objects.create_user(
            email="allergy-icons@example.com",
            password="StrongPass123!",
        )
        Allergen.objects.update_or_create(
            code="milk",
            defaults={
                "name": "Молоко",
            },
        )
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:edit_allergies"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "allergen-chip__icon")
        self.assertContains(response, "allergen-chip__icon--milk")
        self.assertContains(response, "<svg viewBox=\"0 0 24 24\">")

    def test_allergy_editor_saves_ai_sharing_consent(self):
        user = User.objects.create_user(
            email="allergy-consent@example.com",
            password="StrongPass123!",
        )
        allergen = Allergen.objects.create(
            code="test-milk-consent",
            name="Тестовое молоко consent",
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:edit_allergies"),
            {
                "allergens": [str(allergen.id)],
                "share_allergies_with_ai": "on",
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertTrue(user.share_allergies_with_ai)

    def test_profile_links_data_export_and_ai_history_delete(self):
        user = User.objects.create_user(
            email="ai-data-profile@example.com",
            password="StrongPass123!",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("accounts:export_data"))
        self.assertContains(response, reverse("ai_assistant:delete_history"))

    def test_export_data_includes_allergies_consent_and_ai_history(self):
        user = User.objects.create_user(
            email="export-data@example.com",
            password="StrongPass123!",
            share_allergies_with_ai=True,
        )
        allergen = Allergen.objects.create(
            code="test-milk-export",
            name="Тестовое молоко export",
        )
        user.allergy_records.create(allergen=allergen)
        session = ChatSession.objects.create(
            user=user,
            session_key="account-export",
            title="Диалог",
        )
        ChatMessage.objects.create(
            session=session,
            role=ChatMessage.Role.USER,
            content="Что без молока?",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:export_data"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'attachment; filename="caesar-account-data.json"',
            response["Content-Disposition"],
        )
        payload = response.json()
        self.assertTrue(payload["account"]["share_allergies_with_ai"])
        self.assertEqual(
            payload["allergy_profile"][0]["allergen"],
            "Тестовое молоко export",
        )
        self.assertEqual(
            payload["ai_history"]["sessions"][0]["messages"][0]["text"],
            "Что без молока?",
        )


class GoogleAuthTests(TestCase):
    def test_login_page_contains_google_post_form(self):
        response = self.client.get(reverse("account_login"))

        self.assertContains(response, "Continue with Google")
        self.assertContains(response, reverse("google_login"))
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_google_login_get_does_not_start_oauth_redirect(self):
        response = self.client.get(reverse("google_login"))

        self.assertEqual(response.status_code, 200)

    def test_verified_google_email_matches_existing_user(self):
        user = User.objects.create_user(
            email="guest@example.com",
            password="StrongPass123!",
        )
        EmailAddress.objects.create(
            user=user,
            email=user.email,
            verified=True,
            primary=True,
        )

        request = RequestFactory().get(reverse("account_login"))
        provider = get_adapter(request).get_provider(request, "google")
        sociallogin = SocialLogin(
            account=SocialAccount(provider="google", uid="google-user-id"),
            email_addresses=[
                EmailAddress(
                    email="guest@example.com",
                    verified=True,
                    primary=True,
                )
            ],
            provider=provider,
        )

        matched_user, matched_email = get_adapter().authenticate_by_email(sociallogin)

        self.assertEqual(matched_user, user)
        self.assertEqual(matched_email, user.email)
        self.assertEqual(User.objects.filter(email=user.email).count(), 1)
