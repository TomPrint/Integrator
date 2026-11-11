import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import CustomerProfile, Integration, TermsAcceptance


class CustomerManagementTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = override_settings(PRIVATE_DIR=Path(self.directory.name))
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        users = get_user_model()
        self.admin = users.objects.create_superuser(username="admin", password="test-password")
        self.customer = users.objects.create_user(username="customer", password="test-password")
        self.profile = CustomerProfile.objects.create(user=self.customer, company_name="Firma")
        self.other = users.objects.create_user(username="other", password="test-password")
        self.client.force_login(self.admin)

    def edit_data(self):
        return {
            "account-username": "nowy-login", "account-email": "konto@example.com",
            "profile-company_name": "Nowa firma", "profile-invoice_name": "Dane faktury",
            "profile-invoice_nip": "123", "profile-invoice_address": "Warszawa",
            "profile-invoice_email": "faktury@example.com",
        }

    def test_edit_customer_fields_and_keep_plan(self):
        self.profile.plan = "plus"
        self.profile.save()
        url = reverse("admin_edit_client", args=[self.customer.pk])
        self.assertContains(self.client.get(url), "Dane firmy i faktury")
        self.assertRedirects(self.client.post(url, self.edit_data()), reverse("admin_client", args=[self.customer.pk]))
        self.customer.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual((self.customer.username, self.customer.email), ("nowy-login", "konto@example.com"))
        self.assertEqual((self.profile.company_name, self.profile.invoice_name), ("Nowa firma", "Dane faktury"))
        self.assertEqual((self.profile.invoice_nip, self.profile.invoice_address, self.profile.invoice_email),
                         ("123", "Warszawa", "faktury@example.com"))
        self.assertEqual(self.profile.plan, "plus")

    def test_invalid_edit_is_not_partially_saved(self):
        data = self.edit_data()
        data["account-username"] = self.other.username
        data["profile-invoice_email"] = "invalid"
        response = self.client.post(reverse("admin_edit_client", args=[self.customer.pk]), data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["account_form"].errors)
        self.assertTrue(response.context["profile_form"].errors)
        self.customer.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.customer.username, "customer")
        self.assertEqual(self.profile.company_name, "Firma")

    def test_admin_can_reset_customer_initial_password(self):
        self.profile.must_change_password = False
        self.profile.save(update_fields=["must_change_password"])
        url = reverse("admin_edit_client", args=[self.customer.pk])
        response = self.client.post(url, {
            "action": "reset_password",
            "password": "NewInitialPassword835!",
            "password_confirmation": "NewInitialPassword835!",
        })
        self.assertRedirects(response, url)
        self.customer.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertTrue(self.customer.check_password("NewInitialPassword835!"))
        self.assertTrue(self.profile.must_change_password)

    def test_delete_removes_only_selected_customer_and_files(self):
        output_dir = Path(self.directory.name) / "outputs"
        output_dir.mkdir()
        (output_dir / "customer.csv").write_bytes(b"customer")
        (output_dir / "other.csv").write_bytes(b"other")
        obj = Integration.objects.create(owner=self.customer, name="CSV", source_url="https://example.com/a",
                                         output_name="customer.csv")
        other = Integration.objects.create(owner=self.other, name="Other", source_url="https://example.com/b",
                                           output_name="other.csv")
        TermsAcceptance.objects.create(user=self.customer, terms_sha256="a" * 64, terms_snapshot="terms",
                                       integration=obj)
        url = reverse("admin_delete_client", args=[self.customer.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url), reverse("admin_dashboard"))
        self.assertFalse(get_user_model().objects.filter(pk=self.customer.pk).exists())
        self.assertFalse(Integration.objects.filter(pk=obj.pk).exists())
        self.assertFalse(TermsAcceptance.objects.filter(user_id=self.customer.pk).exists())
        self.assertFalse((output_dir / "customer.csv").exists())
        self.assertTrue(Integration.objects.filter(pk=other.pk).exists())
        self.assertTrue((output_dir / "other.csv").exists())

    def test_only_admin_can_manage_clients_and_superusers_are_excluded(self):
        edit = reverse("admin_edit_client", args=[self.customer.pk])
        delete = reverse("admin_delete_client", args=[self.customer.pk])
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(edit).status_code, 403)
        self.assertEqual(self.client.post(edit, self.edit_data()).status_code, 403)
        self.assertEqual(self.client.post(delete).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("admin_edit_client", args=[self.admin.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("admin_delete_client", args=[self.admin.pk])).status_code, 404)
        self.assertTrue(get_user_model().objects.filter(pk=self.customer.pk).exists())

    def test_delete_stops_if_integration_is_added_during_locking(self):
        Integration.objects.create(owner=self.customer, name="CSV", source_url="https://example.com/a")

        @contextmanager
        def lock_with_new_integration(pk):
            Integration.objects.create(owner=self.customer, name="New", source_url="https://example.com/b")
            yield

        with patch("integrations.views.integration_lock", lock_with_new_integration):
            response = self.client.post(reverse("admin_delete_client", args=[self.customer.pk]))
        self.assertRedirects(response, reverse("admin_client", args=[self.customer.pk]))
        self.assertTrue(get_user_model().objects.filter(pk=self.customer.pk).exists())
        self.assertEqual(self.customer.integrations.count(), 2)

    def test_delete_file_error_is_not_reported_as_success(self):
        obj = Integration.objects.create(owner=self.customer, name="CSV", source_url="https://example.com/a",
                                         output_name="customer.csv")
        with patch.object(Path, "unlink", side_effect=OSError("file error")):
            with self.assertRaises(OSError):
                self.client.post(reverse("admin_delete_client", args=[self.customer.pk]))
        self.assertTrue(get_user_model().objects.filter(pk=self.customer.pk).exists())
        self.assertTrue(Integration.objects.filter(pk=obj.pk).exists())

    def test_customer_can_permanently_delete_own_account_and_files(self):
        output_dir = Path(self.directory.name) / "outputs"
        output_dir.mkdir()
        customer_file = output_dir / "customer.csv"
        other_file = output_dir / "other.csv"
        customer_file.write_bytes(b"customer")
        other_file.write_bytes(b"other")
        integration = Integration.objects.create(
            owner=self.customer, name="CSV", source_url="https://example.com/a", output_name=customer_file.name,
        )
        other_integration = Integration.objects.create(
            owner=self.other, name="Other", source_url="https://example.com/b", output_name=other_file.name,
        )
        TermsAcceptance.objects.create(
            user=self.customer, terms_sha256="a" * 64, terms_snapshot="terms", integration=integration,
        )
        url = reverse("delete_account")
        self.client.force_login(self.customer)

        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url, follow=True)

        self.assertRedirects(response, reverse("home"))
        self.assertContains(response, "Usunięto konto klienta")
        self.assertFalse(get_user_model().objects.filter(pk=self.customer.pk).exists())
        self.assertFalse(Integration.objects.filter(owner=self.customer).exists())
        self.assertFalse(TermsAcceptance.objects.filter(user=self.customer).exists())
        self.assertFalse(customer_file.exists())
        self.assertTrue(Integration.objects.filter(pk=other_integration.pk).exists())
        self.assertTrue(other_file.exists())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_customer_account_deletion_is_not_available_to_admin(self):
        self.client.force_login(self.admin)

        self.assertEqual(self.client.get(reverse("delete_account")).status_code, 403)
        self.assertEqual(self.client.post(reverse("delete_account")).status_code, 403)
        self.assertTrue(get_user_model().objects.filter(pk=self.admin.pk).exists())

    def test_self_deletion_stops_if_integration_is_added_during_locking(self):
        Integration.objects.create(owner=self.customer, name="CSV", source_url="https://example.com/a")

        @contextmanager
        def lock_with_new_integration(pk):
            Integration.objects.create(owner=self.customer, name="New", source_url="https://example.com/b")
            yield

        self.client.force_login(self.customer)
        with patch("integrations.views.integration_lock", lock_with_new_integration):
            response = self.client.post(reverse("delete_account"))

        self.assertRedirects(response, reverse("account"))
        self.assertTrue(get_user_model().objects.filter(pk=self.customer.pk).exists())
        self.assertEqual(self.customer.integrations.count(), 2)

    def test_delete_confirmation_on_customer_and_integration_pages(self):
        obj = Integration.objects.create(owner=self.customer, name="CSV", source_url="https://example.com/a")
        own = Integration.objects.create(owner=self.admin, name="Starsza", source_url="https://example.com/b")
        response = self.client.get(reverse("admin_client", args=[self.customer.pk]))
        self.assertContains(response, reverse("admin_edit_client", args=[self.customer.pk]))
        self.assertContains(response, reverse("admin_delete_client", args=[self.customer.pk]))
        self.assertContains(response, 'data-delete-confirmation', count=2)
        self.assertContains(response, 'disabled data-delete-submit', count=2)
        self.assertContains(response, 'data-delete-cancel', count=2)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertContains(response, reverse("admin_delete", args=[own.pk]))
        self.assertContains(response, 'disabled data-delete-submit')
        self.assertContains(response, 'data-delete-cancel')
        self.client.force_login(self.customer)
        response = self.client.get(reverse("result", args=[obj.pk]))
        self.assertContains(response, reverse("delete", args=[obj.pk]))
        self.assertContains(response, 'disabled data-delete-submit')
        self.assertContains(response, 'data-delete-cancel')
        response = self.client.get(reverse("account"))
        self.assertContains(response, reverse("delete_account"))
        self.assertContains(response, "Trwale usuniesz swoje konto")
        self.assertContains(response, 'data-delete-confirmation')
        self.assertContains(response, 'disabled data-delete-submit')
        self.assertContains(response, 'data-delete-cancel')
