from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import CustomerProfile, Integration, TermsAcceptance
from .views import current_terms


class TermsAcceptanceTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.user = users.objects.create_user(username="customer", password="ExamplePassword123!")
        self.admin = users.objects.create_superuser(username="admin", password="ExamplePassword123!")
        CustomerProfile.objects.create(user=self.user)
        self.client.force_login(self.user)
        self.invoice = {"invoice_name": "Firma", "invoice_nip": "123", "invoice_address": "Warszawa",
                        "invoice_email": "firma@example.com"}

    def accept(self):
        return self.client.post(reverse("accept_terms"), {"accepted": "on", "terms_sha256": current_terms()[1]})

    def test_invoice_then_unchecked_checkbox_then_acceptance(self):
        self.assertRedirects(self.client.get(reverse("create")), reverse("invoice"))
        self.assertRedirects(self.client.post(reverse("invoice"), self.invoice), reverse("accept_terms"))
        page = self.client.get(reverse("accept_terms"))
        self.assertContains(page, reverse("terms"))
        response = self.client.post(reverse("accept_terms"), {"terms_sha256": current_terms()[1]})
        self.assertContains(response, "Aby dodać integrację")
        self.assertFalse(TermsAcceptance.objects.exists())
        self.assertRedirects(self.accept(), reverse("create"))
        record = TermsAcceptance.objects.get()
        self.assertEqual(record.terms_sha256, current_terms()[1])
        self.assertEqual(record.terms_snapshot, current_terms()[0])
        self.assertIsNone(record.consumed_at)

    @patch("integrations.views.fetch_csv", return_value=b"SKU;NAME\nA;Example\n")
    def test_acceptance_required_once_per_created_integration(self, fetch):
        self.client.post(reverse("invoice"), self.invoice)
        data = {"name": "Pierwsza", "source_url": "https://example.com/data.csv"}
        self.assertRedirects(self.client.post(reverse("create"), data), reverse("accept_terms"))
        fetch.assert_not_called()
        self.accept()
        response = self.client.post(reverse("create"), data)
        first = Integration.objects.get(name="Pierwsza")
        self.assertRedirects(response, reverse("configure", args=[first.pk]))
        record = TermsAcceptance.objects.get()
        self.assertIsNotNone(record.consumed_at)
        self.assertEqual(record.integration, first)
        self.assertRedirects(self.client.post(reverse("create"), {**data, "name": "Druga"}), reverse("accept_terms"))
        self.accept()
        self.client.post(reverse("create"), {**data, "name": "Druga"})
        self.assertEqual(self.user.integrations.count(), 2)
        self.assertEqual(TermsAcceptance.objects.filter(consumed_at__isnull=False).count(), 2)

    def test_changed_terms_require_new_confirmation(self):
        self.client.post(reverse("invoice"), self.invoice)
        self.accept()
        with patch("integrations.views.current_terms", return_value=("new terms", "a" * 64)):
            self.assertRedirects(self.client.get(reverse("create")), reverse("accept_terms"))
            response = self.client.post(reverse("accept_terms"), {"accepted": "on", "terms_sha256": "b" * 64})
            self.assertContains(response, "Regulamin został zmieniony")
            self.assertContains(response, 'value="' + "a" * 64 + '"')
        self.assertEqual(TermsAcceptance.objects.count(), 1)

    def test_admin_sees_invoice_and_acceptance_other_customers_cannot(self):
        self.client.post(reverse("invoice"), self.invoice)
        self.accept()
        url = reverse("admin_client", args=[self.user.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get(url)
        for value in ("Firma", "123", "Warszawa", "firma@example.com", "Zaakceptowano:", current_terms()[1]):
            self.assertContains(response, value)

    def test_existing_integration_remains_accessible(self):
        obj = Integration.objects.create(owner=self.user, name="Istniejąca", source_url="https://example.com/x")
        self.assertEqual(self.client.get(reverse("configure", args=[obj.pk])).status_code, 200)
