from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import translation

from .models import CustomerProfile, Integration, ProjectError, TermsAcceptance
from .views import current_terms


class LanguageRoutingTests(SimpleTestCase):
    def setUp(self):
        self.addCleanup(translation.deactivate)

    def test_existing_polish_urls_are_unchanged(self):
        with translation.override("pl"):
            self.assertEqual(reverse("home"), "/")
            self.assertEqual(reverse("login"), "/login/")
            self.assertEqual(reverse("terms"), "/regulamin/")
            self.assertEqual(reverse("integration_list"), "/integrations/")

    def test_prefix_selects_language_and_unprefixed_url_stays_polish(self):
        response = self.client.get("/", HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Language"], "pl")
        response = self.client.get("/en/", HTTP_ACCEPT_LANGUAGE="pl")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Language"], "en")
        self.assertContains(response, "CSV files ready for integration")
        self.assertContains(response, 'lang="en"')
        self.assertContains(response, "Your privacy")
        self.assertContains(response, 'href="/" lang="pl"')
        with translation.override("en"):
            self.assertEqual(reverse("home"), "/en/")
            self.assertEqual(reverse("login"), "/en/login/")
            self.assertEqual(reverse("terms"), "/en/regulamin/")

    def test_protected_page_redirects_to_english_login(self):
        response = self.client.get("/en/integrations/")
        self.assertRedirects(
            response,
            "/en/login/?next=/en/integrations/",
            fetch_redirect_response=False,
        )

    def test_public_pages_and_language_links(self):
        response = self.client.get("/en/login/?next=/en/integrations/")
        self.assertContains(response, "Welcome to Mid-Grator")
        self.assertContains(response, 'href="/login/?next=%2Fintegrations%2F"')
        self.assertContains(self.client.get("/en/polityka-prywatnosci/"), "Privacy policy")
        self.assertContains(self.client.get("/en/regulamin/"), "Service terms and conditions")
        self.assertContains(self.client.get("/regulamin/"), "Regulamin usługi")

    def test_header_uses_collapsible_mobile_menu(self):
        response = self.client.get("/en/")
        self.assertContains(response, '<details class="mobile-menu lg:hidden">')
        self.assertContains(response, 'class="mobile-menu-panel"')
        self.assertContains(response, 'class="mobile-menu-toggle"')
        self.assertContains(response, 'class="hidden items-center justify-end gap-3 lg:flex"')

    def test_language_switch_preserves_query_and_does_not_redirect_to_external_host(self):
        response = self.client.get("/en/login/", {"next": "//example.com/path", "filter": "one two"})
        self.assertContains(response, 'href="/login/?next=%2F%2Fexample.com%2Fpath&amp;filter=one+two"')


class LocalizedTermsTests(TestCase):
    def setUp(self):
        self.addCleanup(translation.deactivate)
        self.user = get_user_model().objects.create_user(username="customer")
        CustomerProfile.objects.create(
            user=self.user, invoice_name="Company", invoice_nip="1234567890", invoice_address="Address",
            invoice_email="customer@example.com",
        )
        self.client.force_login(self.user)

    def test_acceptance_saves_english_document_and_cannot_be_used_for_polish(self):
        content, digest = current_terms("en")
        page = self.client.get("/en/new/terms/")
        self.assertContains(page, "I confirm that I have read and accept the terms and conditions.")
        unchecked = self.client.post("/en/new/terms/", {"terms_sha256": digest})
        self.assertContains(unchecked, "Accept the terms and conditions to add an integration.")
        response = self.client.post("/en/new/terms/", {"accepted": "on", "terms_sha256": digest})
        self.assertRedirects(response, "/en/new/", fetch_redirect_response=False)
        record = TermsAcceptance.objects.get(user=self.user)
        self.assertEqual(record.terms_snapshot, content)
        self.assertEqual(record.terms_sha256, digest)
        self.assertIn("Service terms and conditions", record.terms_snapshot)
        self.assertNotEqual(digest, current_terms("pl")[1])
        self.assertRedirects(self.client.get("/new/"), "/new/terms/", fetch_redirect_response=False)

    def test_account_delete_confirmation_is_localized(self):
        response = self.client.get("/en/account/")
        self.assertContains(response, "Account email address")
        self.assertContains(response, "This permanently deletes your account")
        self.assertContains(response, 'data-confirm-label="Confirm deletion"')
        self.assertContains(response, "Enable JavaScript to confirm deletion.")

    @patch("integrations.views.fetch_csv", return_value=b"SKU;NAME\nA;Example\n")
    def test_customer_configuration_and_preview_switch_languages(self, fetch):
        obj = Integration.objects.create(owner=self.user, name="Example", source_url="https://example.com/data.csv",
                                         headers=["SKU", "NAME"])
        response = self.client.get("/en/integrations/")
        self.assertContains(response, "All integrations")
        self.assertContains(response, "Every 12 hours")
        response = self.client.get(f"/en/integration/{obj.pk}/")
        self.assertContains(response, "Columns and rules")
        self.assertContains(response, "Output file delimiter")
        self.assertContains(response, "Add numeric rule")
        data = {"form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "2", "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "200", "interval_hours": "12", "output_delimiter": "source",
                "form-0-selected": "on", "form-0-output_name": "SKU", "form-0-mapping": "",
                "form-1-selected": "on", "form-1-output_name": "NAME", "form-1-mapping": ""}
        response = self.client.post(f"/en/integration/{obj.pk}/", data)
        self.assertRedirects(response, f"/en/integration/{obj.pk}/preview/", fetch_redirect_response=False)
        preview = self.client.get(f"/en/integration/{obj.pk}/preview/")
        self.assertContains(preview, "Validation successful")
        self.assertContains(preview, "semicolon ;")
        self.assertContains(preview, "Every 12 hours")
        polish_preview = self.client.get(f"/integration/{obj.pk}/preview/")
        self.assertContains(polish_preview, "średnik ;")
        self.assertContains(polish_preview, "Co 12 godzin")

    def test_english_form_and_service_errors(self):
        response = self.client.post("/en/new/terms/", {"accepted": "on", "terms_sha256": current_terms("en")[1]})
        self.assertEqual(response.status_code, 302)
        response = self.client.post("/en/new/", {"name": "Bad", "source_url": "not-a-url"})
        self.assertContains(response, "Enter the full file address")
        with translation.override("en"):
            from .rules import parse_number
            from .services import IntegrationError, inspect_csv
            import io
            with self.assertRaisesMessage(ValueError, "Enter a decimal number"):
                parse_number("not-a-number")
            with self.assertRaisesMessage(IntegrationError, "HTML page instead of a CSV file"):
                inspect_csv(io.BytesIO(b"<html>not csv</html>"))

    def test_admin_pages_remain_available_without_translation(self):
        admin = get_user_model().objects.create_superuser(username="admin", password="valid-password-123")
        profile = self.user.customer_profile
        from django.utils import timezone
        profile.plan = "trial"
        profile.trial_started_at = timezone.now()
        profile.save()
        self.client.force_login(admin)
        dashboard = self.client.get("/en/control/")
        self.assertContains(dashboard, "Panel administratora")
        detail = self.client.get(f"/en/control/client/{self.user.pk}/")
        self.assertContains(detail, "Klient:")
        self.assertContains(detail, "Zapisz plan")

    def test_persisted_polish_cron_error_is_displayed_in_english(self):
        obj = Integration.objects.create(
            owner=self.user, name="Example", source_url="https://example.com/data.csv",
            last_error="Plik źródłowy jest pusty.",
        )
        self.assertContains(self.client.get("/en/integrations/"), "The source file is empty.")
        self.assertContains(self.client.get(f"/en/integration/{obj.pk}/result/"), "The source file is empty.")

    def test_persisted_polish_application_error_is_displayed_in_english(self):
        admin = get_user_model().objects.create_superuser(username="admin", password="valid-password-123")
        ProjectError.objects.create(
            category="RuntimeError",
            message="Nieobsłużony błąd żądania WWW. Szczegóły w logach serwera.",
        )
        self.client.force_login(admin)
        self.assertContains(self.client.get("/en/control/"), "Nieobsłużony błąd żądania WWW.")
