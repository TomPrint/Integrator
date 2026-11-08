import io
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import OutputSettingsForm
from .models import CustomerProfile, Integration
from .services import LARGE_SOURCE_BYTES, adjust_large_source_schedule, large_source, source_size
from .views import current_terms

SMALL = b"SKU;NAME\nA;Example\n"
LARGE = b"SKU;NAME\n" + (b"A;" + b"x" * 100 + b"\n") * 51000


class LargeSourceTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = override_settings(PRIVATE_DIR=Path(self.temp.name), ALLOWED_HOSTS=["testserver"])
        settings.enable()
        self.addCleanup(settings.disable)
        self.user = get_user_model().objects.create_user(username="customer", password="ExamplePassword123!")
        CustomerProfile.objects.create(user=self.user, invoice_name="Firma", invoice_address="Warszawa",
                                       invoice_email="faktury@example.com")
        self.client.force_login(self.user)
        self.obj = Integration.objects.create(
            owner=self.user, name="Test", source_url="https://example.com/data.csv",
            headers=["SKU", "NAME"], interval_hours=2,
            columns=[{"source": "SKU", "name": "SKU", "mapping": {}}],
            active=True, last_success=timezone.now() - timedelta(hours=3),
            last_attempt=timezone.now() - timedelta(hours=3),
        )

    def test_exact_threshold_and_file_position(self):
        self.assertFalse(large_source(LARGE_SOURCE_BYTES - 1))
        self.assertTrue(large_source(LARGE_SOURCE_BYTES))
        with io.BytesIO(LARGE) as source:
            source.seek(10)
            self.assertEqual(source_size(source), len(LARGE))
            self.assertEqual(source.tell(), 10)

    def test_large_form_options_and_forged_interval(self):
        form = OutputSettingsForm(instance=self.obj, source_delimiter=";", source_size_bytes=len(LARGE))
        self.assertEqual([int(value) for value, _ in form.fields["interval_hours"].choices], [24, 48, 168])
        self.assertEqual(form.initial["interval_hours"], 24)
        form = OutputSettingsForm({"interval_hours": "2", "output_delimiter": "source"},
                                  instance=self.obj, source_delimiter=";", source_size_bytes=len(LARGE))
        self.assertFalse(form.is_valid())

    def test_schedule_endpoint_enforces_last_observed_size(self):
        self.obj.source_size_bytes = len(LARGE)
        self.obj.interval_hours = 24
        self.obj.save()
        self.client.post(reverse("schedule", args=[self.obj.pk]), {"interval_hours": 2})
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.interval_hours, 24)
        self.client.post(reverse("schedule", args=[self.obj.pk]), {"interval_hours": 48})
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.interval_hours, 48)

    @patch("integrations.views.fetch_csv", return_value=LARGE)
    def test_create_displays_only_long_intervals(self, fetch):
        self.client.post(reverse("accept_terms"), {"accepted": "on", "terms_sha256": current_terms()[1]})
        response = self.client.post(reverse("create"), {"name": "Duży", "source_url": "https://example.com/large.csv"})
        obj = self.user.integrations.get(name="Duży")
        self.assertRedirects(response, reverse("configure", args=[obj.pk]))
        self.assertEqual(obj.source_size_bytes, len(LARGE))
        response = self.client.get(reverse("configure", args=[obj.pk]))
        choices = response.context["settings_form"].fields["interval_hours"].choices
        self.assertEqual([int(value) for value, _ in choices], [24, 48, 168])
        self.assertContains(response, "co najmniej 5 MiB")

    @patch("integrations.views.fetch_csv", return_value=LARGE)
    def test_preview_rejects_fast_interval_if_source_grew(self, fetch):
        data = {"form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "2", "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "200", "interval_hours": "2", "output_delimiter": "source",
                "form-0-selected": "on", "form-0-output_name": "SKU", "form-0-mapping": "",
                "form-1-selected": "on", "form-1-output_name": "NAME", "form-1-mapping": ""}
        response = self.client.post(reverse("configure", args=[self.obj.pk]), data)
        self.assertContains(response, "Wybierz aktualizację co najmniej co 24 godziny.")
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.interval_hours, 2)

    @patch("integrations.management.commands.update_integrations.fetch_csv", return_value=LARGE)
    def test_cron_defers_growth_and_preserves_last_attempt(self, fetch):
        previous = self.obj.last_attempt
        call_command("update_integrations", stdout=io.StringIO())
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.interval_hours, 24)
        self.assertEqual(self.obj.last_attempt, previous)
        self.assertTrue(self.obj.interval_auto_adjusted)
        self.assertEqual(self.obj.source_size_bytes, len(LARGE))
        self.assertFalse(self.obj.output_name)
        self.assertContains(self.client.get(reverse("integration_list")), "Częstotliwość automatycznie zmieniono")
        call_command("update_integrations", stdout=io.StringIO())
        self.assertEqual(fetch.call_count, 1)

    @patch("integrations.management.commands.update_integrations.fetch_csv", return_value=LARGE)
    def test_cron_processes_growth_when_24_hours_have_elapsed(self, fetch):
        self.obj.last_attempt = timezone.now() - timedelta(hours=25)
        self.obj.save()
        call_command("update_integrations", stdout=io.StringIO())
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.interval_hours, 24)
        self.assertTrue(self.obj.interval_auto_adjusted)
        self.assertTrue(self.obj.output_name)
        self.assertGreaterEqual(self.obj.last_update_delay_seconds, 3600)
        self.assertLess(self.obj.last_update_delay_seconds, 3700)

    @patch("integrations.views.fetch_csv", return_value=LARGE)
    def test_confirm_rechecks_growth_since_preview(self, fetch):
        session = self.client.session
        session[f"draft_{self.obj.pk}"] = {
            "columns": self.obj.columns,
            "settings": {"interval_hours": 2, "output_delimiter": "source"},
        }
        session.save()
        response = self.client.post(reverse("confirm", args=[self.obj.pk]))
        self.assertRedirects(response, reverse("result", args=[self.obj.pk]))
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.interval_hours, 24)
        self.assertTrue(self.obj.interval_auto_adjusted)
        self.assertContains(self.client.get(reverse("result", args=[self.obj.pk])), "Częstotliwość automatycznie zmieniono")

    def test_shorter_interval_not_restored_when_source_shrinks(self):
        adjust_large_source_schedule(self.obj, len(LARGE))
        adjust_large_source_schedule(self.obj, len(SMALL))
        self.assertEqual(self.obj.interval_hours, 24)
        self.assertTrue(self.obj.interval_auto_adjusted)
