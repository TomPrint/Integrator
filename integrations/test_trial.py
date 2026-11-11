from io import StringIO
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import CustomerProfile, Integration


class TrialPlanTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = override_settings(PRIVATE_DIR=Path(self.directory.name), ALLOWED_HOSTS=["testserver"])
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        users = get_user_model()
        self.admin = users.objects.create_superuser(
            username="admin", email="admin@example.com", password="TestAdminPassword123!",
        )
        self.customer = users.objects.create_user(
            username="customer", email="customer@example.com", password="TestCustomerPassword123!",
        )
        self.profile = CustomerProfile.objects.create(user=self.customer)

    def test_admin_activation_starts_seven_day_trial_and_limits_one_integration(self):
        self.client.force_login(self.admin)
        url = reverse("admin_client", args=[self.customer.pk])
        before = timezone.now()
        response = self.client.post(url, {
            "plan": "trial", "paid_from": "2026-01-01", "paid_until": "2026-12-31",
        })
        after = timezone.now()

        self.assertRedirects(response, url)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, "trial")
        self.assertTrue(before <= self.profile.trial_started_at <= after)
        self.assertEqual(self.profile.limit, 1)
        self.assertIsNone(self.profile.paid_from)
        self.assertIsNone(self.profile.paid_until)
        self.client.force_login(self.customer)
        self.assertContains(self.client.get(reverse("integration_list")), "Plan testowy")

    def test_trial_plan_hides_payment_dates_for_admin(self):
        self.profile.plan = "trial"
        self.profile.trial_started_at = timezone.now()
        self.profile.save(update_fields=["plan", "trial_started_at"])
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_client", args=[self.customer.pk]))

        self.assertContains(response, 'data-plan-payment-dates hidden')

    def test_admin_cannot_activate_trial_with_more_than_one_integration(self):
        for name in ("One", "Two"):
            Integration.objects.create(owner=self.customer, name=name, source_url=f"https://example.com/{name}")

        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin_client", args=[self.customer.pk]), {
            "plan": "trial", "paid_from": "", "paid_until": "",
        })

        self.assertContains(response, "usuń nadmiarowe integracje")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, "basic")
        self.assertIsNone(self.profile.trial_started_at)

    def test_cron_expires_trial_stops_integration_and_notifies_client(self):
        output_dir = Path(self.directory.name) / "outputs"
        output_dir.mkdir()
        output = output_dir / "trial.csv"
        output.write_bytes(b"test data")
        integration = Integration.objects.create(
            owner=self.customer, name="Test", source_url="https://example.com/test.csv",
            output_name=output.name, active=True,
        )
        self.profile.plan = "trial"
        self.profile.trial_started_at = timezone.now() - timedelta(days=7, seconds=1)
        self.profile.save(update_fields=["plan", "trial_started_at"])

        self.assertEqual(self.client.get(reverse("download", args=[integration.token])).status_code, 404)
        self.client.force_login(self.customer)
        self.assertRedirects(self.client.get(reverse("create")), reverse("integration_list"))

        call_command("update_integrations", stdout=StringIO())

        integration.refresh_from_db()
        self.assertFalse(integration.active)
        self.assertTrue(output.exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.customer.pk).exists())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, "trial")
        self.assertIsNotNone(self.profile.trial_ended_at)
        self.assertEqual(self.profile.limit, 0)
        self.assertContains(self.client.get(reverse("integration_list")), "Plan testowy zakończony.")
        self.assertContains(self.client.get(reverse("integration_list")), "Wstrzymana")

    def test_expired_trial_is_deleted_only_twenty_days_after_expiry(self):
        output_dir = Path(self.directory.name) / "outputs"
        output_dir.mkdir()
        output = output_dir / "trial.csv"
        output.write_bytes(b"test data")
        integration = Integration.objects.create(owner=self.customer, name="Test",
                                                 source_url="https://example.com/a", output_name=output.name)
        now = timezone.now()
        self.profile.plan = "trial"
        self.profile.trial_started_at = now - timedelta(days=27) + timedelta(seconds=1)
        self.profile.save(update_fields=["plan", "trial_started_at"])
        from .trials import expire_trials
        expire_trials(now)
        self.assertTrue(Integration.objects.filter(pk=integration.pk).exists())
        self.assertTrue(output.exists())
        expire_trials(now + timedelta(seconds=1))
        self.assertFalse(Integration.objects.filter(pk=integration.pk).exists())
        self.assertFalse(output.exists())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, "trial")
        self.assertTrue(self.profile.trial_expired)

    def test_upgrade_deletes_trial_integration_and_preserves_other_customers(self):
        other = get_user_model().objects.create_user("other")
        other_integration = Integration.objects.create(owner=other, name="Other", source_url="https://example.com/b")
        for plan, limit in (("basic", 2), ("plus", 4)):
            with self.subTest(plan=plan):
                self.profile.plan = "trial"
                self.profile.trial_started_at = timezone.now() - timedelta(days=8)
                self.profile.trial_ended_at = None
                self.profile.save()
                output_dir = Path(self.directory.name) / "outputs"
                output_dir.mkdir(exist_ok=True)
                output = output_dir / f"{plan}.csv"
                output.write_bytes(b"test data")
                integration = Integration.objects.create(owner=self.customer, name="Test",
                                                         source_url="https://example.com/a", output_name=output.name)
                self.client.force_login(self.admin)
                response = self.client.post(reverse("admin_client", args=[self.customer.pk]), {
                    "plan": plan, "paid_from": "", "paid_until": "",
                })
                self.assertRedirects(response, reverse("admin_client", args=[self.customer.pk]))
                self.profile.refresh_from_db()
                self.assertEqual((self.profile.plan, self.profile.limit), (plan, limit))
                self.assertFalse(Integration.objects.filter(pk=integration.pk).exists())
                self.assertFalse(output.exists())
                self.assertTrue(Integration.objects.filter(pk=other_integration.pk).exists())

    def test_upgrade_during_active_trial_deletes_test_integration(self):
        self.profile.plan = "trial"
        self.profile.trial_started_at = timezone.now()
        self.profile.save(update_fields=["plan", "trial_started_at"])
        integration = Integration.objects.create(owner=self.customer, name="Test", source_url="https://example.com/a")
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin_client", args=[self.customer.pk]), {
            "plan": "plus", "paid_from": "", "paid_until": "",
        })
        self.assertRedirects(response, reverse("admin_client", args=[self.customer.pk]))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.limit, 4)
        self.assertFalse(Integration.objects.filter(pk=integration.pk).exists())

    def test_paid_plan_upgrade_keeps_existing_integration(self):
        integration = Integration.objects.create(owner=self.customer, name="Existing", source_url="https://example.com/a")
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin_client", args=[self.customer.pk]), {
            "plan": "plus", "paid_from": "", "paid_until": "",
        })
        self.assertRedirects(response, reverse("admin_client", args=[self.customer.pk]))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.limit, 4)
        self.assertTrue(Integration.objects.filter(pk=integration.pk).exists())

    def test_upgrade_fails_when_trial_file_cannot_be_removed(self):
        self.profile.plan = "trial"
        self.profile.trial_started_at = timezone.now()
        self.profile.save(update_fields=["plan", "trial_started_at"])
        integration = Integration.objects.create(owner=self.customer, name="Test",
                                                 source_url="https://example.com/a", output_name="trial.csv")
        self.client.force_login(self.admin)
        with patch.object(Path, "unlink", side_effect=OSError("cannot delete")):
            with self.assertRaises(OSError):
                self.client.post(reverse("admin_client", args=[self.customer.pk]), {
                    "plan": "plus", "paid_from": "", "paid_until": "",
                })
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, "trial")
        self.assertTrue(Integration.objects.filter(pk=integration.pk).exists())

    def test_trial_status_in_client_and_admin_panels(self):
        self.profile.plan = "trial"
        self.profile.trial_started_at = timezone.now()
        self.profile.save(update_fields=["plan", "trial_started_at"])
        self.client.force_login(self.admin)
        detail = self.client.get(reverse("admin_client", args=[self.customer.pk]))
        self.assertContains(detail, "Status: aktywny.")
        self.assertNotContains(detail, "nieopłacone / wygasło")
        dashboard = self.client.get(reverse("admin_dashboard"))
        self.assertContains(dashboard, ">Aktywny<")
        self.client.force_login(self.customer)
        self.assertContains(self.client.get(reverse("integration_list")), "Plan testowy: aktywny")
        self.profile.trial_started_at = timezone.now() - timedelta(days=8)
        self.profile.save(update_fields=["trial_started_at"])
        self.assertContains(self.client.get(reverse("integration_list")), "Plan testowy zakończony")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("admin_client", args=[self.customer.pk])), "Status: zakończony.")
        self.assertContains(self.client.get(reverse("admin_dashboard")), ">Zakończony<")

    def test_expired_trial_cannot_publish(self):
        self.profile.plan = "trial"
        self.profile.trial_started_at = timezone.now() - timedelta(days=8)
        self.profile.save(update_fields=["plan", "trial_started_at"])
        integration = Integration.objects.create(owner=self.customer, name="Test", source_url="https://example.com/a")
        self.client.force_login(self.customer)
        session = self.client.session
        session[f"draft_{integration.pk}"] = {"columns": [{"source": "a"}]}
        session.save()
        with patch("integrations.views.fetch_csv") as fetch:
            response = self.client.post(reverse("confirm", args=[integration.pk]))
        self.assertRedirects(response, reverse("preview", args=[integration.pk]), fetch_redirect_response=False)
        fetch.assert_not_called()

    def test_cron_does_not_expire_trial_before_seven_days(self):
        self.profile.plan = "trial"
        self.profile.trial_started_at = timezone.now() - timedelta(days=7) + timedelta(seconds=30)
        self.profile.save(update_fields=["plan", "trial_started_at"])

        call_command("update_integrations", stdout=StringIO())

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, "trial")
        self.assertIsNone(self.profile.trial_ended_at)
        self.assertEqual(self.profile.limit, 1)
