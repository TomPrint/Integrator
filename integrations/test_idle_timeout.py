from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .middleware import CUSTOMER_IDLE_TIMEOUT_SECONDS, CUSTOMER_LAST_ACTIVITY_SESSION_KEY
from .models import CustomerProfile


class CustomerIdleTimeoutTests(TestCase):
    def setUp(self):
        self.customer = get_user_model().objects.create_user(
            username="customer",
            password="test-password-123",
        )
        CustomerProfile.objects.create(user=self.customer)
        self.client.force_login(self.customer)

    def set_last_activity(self, seconds_ago):
        session = self.client.session
        session[CUSTOMER_LAST_ACTIVITY_SESSION_KEY] = timezone.now().timestamp() - seconds_ago
        session.save()

    def test_customer_is_logged_out_after_thirty_minutes_of_inactivity(self):
        self.set_last_activity(CUSTOMER_IDLE_TIMEOUT_SECONDS)

        response = self.client.get("/account/")

        self.assertRedirects(response, "/login/", fetch_redirect_response=False)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        follow_response = self.client.get(response.url)
        self.assertContains(follow_response, "Wylogowano Cię po 30 minutach bezczynności.")

    def test_customer_activity_resets_idle_timeout(self):
        self.set_last_activity(CUSTOMER_IDLE_TIMEOUT_SECONDS - 1)

        response = self.client.get("/account/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        self.assertGreater(
            self.client.session[CUSTOMER_LAST_ACTIVITY_SESSION_KEY],
            timezone.now().timestamp() - 2,
        )

    def test_idle_timeout_message_uses_selected_language(self):
        self.set_last_activity(CUSTOMER_IDLE_TIMEOUT_SECONDS)

        response = self.client.get("/en/account/")

        self.assertRedirects(response, "/en/login/", fetch_redirect_response=False)
        follow_response = self.client.get(response.url)
        self.assertContains(follow_response, "You were logged out after 30 minutes of inactivity.")

    def test_admin_session_is_not_affected(self):
        admin = get_user_model().objects.create_superuser(
            username="admin",
            password="test-password-123",
        )
        self.client.force_login(admin)
        self.set_last_activity(CUSTOMER_IDLE_TIMEOUT_SECONDS + 60)

        response = self.client.get("/control/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.wsgi_request.user.is_authenticated)
