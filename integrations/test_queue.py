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

from .models import CustomerProfile, Integration
from .services import IntegrationError, publish

SOURCE = b"SKU;NAME\nA;Example\n"
COLUMNS = [{"source": "SKU", "name": "SKU", "mapping": {}}]


class UpdateQueueTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = override_settings(PRIVATE_DIR=Path(self.temp.name), ALLOWED_HOSTS=["testserver"])
        settings.enable()
        self.addCleanup(settings.disable)
        self.user = get_user_model().objects.create_user(username="customer", password="ExamplePassword123!")
        CustomerProfile.objects.create(user=self.user)
        self.client.force_login(self.user)
        self.now = timezone.now()

    def create_integration(self, name, hours_ago):
        return Integration.objects.create(
            owner=self.user, name=name, source_url=f"https://example.com/{name}",
            headers=["SKU", "NAME"], columns=COLUMNS, active=True, interval_hours=2,
            last_attempt=self.now - timedelta(hours=hours_ago),
            last_success=self.now - timedelta(hours=hours_ago),
        )

    def test_simultaneous_updates_ordered_by_due_time_and_delay_saved(self):
        items = [self.create_integration(str(i), hours) for i, hours in enumerate([3, 5, 2, 4, 6])]
        order = []
        current = [self.now]

        def fetch(url):
            order.append(url.rsplit("/", 1)[-1])
            current[0] += timedelta(minutes=5)
            return SOURCE

        with patch("integrations.management.commands.update_integrations.fetch_csv", side_effect=fetch), \
             patch("django.utils.timezone.now", side_effect=lambda: current[0]):
            call_command("update_integrations", stdout=io.StringIO())
        self.assertEqual(order, ["4", "1", "3", "0", "2"])
        for item, minutes in zip([items[4], items[1], items[3], items[0], items[2]], [245, 190, 135, 80, 25]):
            item.refresh_from_db()
            self.assertEqual(item.last_update_delay_seconds, minutes * 60)
            self.assertTrue(item.output_name)
        self.assertContains(self.client.get(reverse("integration_list")), "25 min 0 s")
        self.assertContains(self.client.get(reverse("result", args=[items[2].pk])), "25 min 0 s")

    def test_threshold_and_manual_publication_clears_previous_notice(self):
        item = self.create_integration("test", 2)
        for seconds, expected in [(None, ""), (900, ""), (901, "15 min 1 s"),
                                  (3661, "1 godz. 1 min 1 s")]:
            item.last_update_delay_seconds = seconds
            self.assertEqual(item.update_delay_display, expected)
        item.last_update_delay_seconds = 1800
        item.save()
        with io.BytesIO(SOURCE) as source:
            publish(item, source, COLUMNS)
        item.refresh_from_db()
        self.assertIsNone(item.last_update_delay_seconds)

    @patch("integrations.management.commands.update_integrations.fetch_csv")
    def test_failed_attempt_does_not_report_successful_update(self, fetch):
        item = self.create_integration("failure", 3)
        item.last_update_delay_seconds = 1200
        item.save()
        fetch.side_effect = IntegrationError("Błąd źródła")
        with self.assertRaises(SystemExit):
            call_command("update_integrations", stdout=io.StringIO(), stderr=io.StringIO())
        item.refresh_from_db()
        self.assertEqual(item.last_update_delay_seconds, 1200)
        self.assertEqual(item.last_error, "Błąd źródła")

    @patch("integrations.management.commands.update_integrations.fetch_csv", return_value=SOURCE)
    def test_unscheduled_and_future_integrations(self, fetch):
        no_date = self.create_integration("no-date", 3)
        no_date.last_attempt = None
        no_date.last_success = None
        no_date.save()
        future = self.create_integration("future", 1)
        call_command("update_integrations", stdout=io.StringIO())
        no_date.refresh_from_db()
        future.refresh_from_db()
        self.assertIsNone(no_date.last_update_delay_seconds)
        self.assertFalse(future.output_name)
        self.assertEqual(fetch.call_count, 1)
