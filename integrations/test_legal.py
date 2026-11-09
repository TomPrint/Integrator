from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import CustomerProfile


class LegalPagesTests(TestCase):
    def test_terms_and_privacy_show_operational_conditions(self):
        response = self.client.get(reverse("terms"))
        for text in (
            "przed zawarciem umowy", "nie odnawia się automatycznie",
            "246 PLN brutto", "492 PLN brutto", "14 dni kalendarzowych",
            "niewykorzystana część opłaty nie podlega zwrotowi",
            "w ciągu 30 dni", "bez logowania", "przed rozpoczęciem przetwarzania",
            "co najmniej 30 dni", "dotyczące umów na odległość",
            "bezpłatnie przez 7 kolejnych dni", "Test nie przechodzi automatycznie",
            "W okresie testowym klient może korzystać z jednej integracji.",
            "integracja testowa i jej opublikowane pliki są wtedy usuwane, a konto klienta pozostaje aktywne",
            "Okres testowy nie skraca płatnego roku",
            "nie wcześniej niż po zakończeniu testu",
        ):
            with self.subTest(text=text):
                self.assertContains(response, text)
        privacy = self.client.get(reverse("privacy"))
        self.assertContains(privacy, "kopię źródła szablonu")
        self.assertContains(privacy, "przed rozpoczęciem przetwarzania")
        self.assertContains(privacy, "w ciągu 30 dni po zakończeniu umowy")

    def test_public_pages_and_footer_links(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'src="/static/images/mid-grator-logo.png"')
        self.assertIsNotNone(finders.find("images/mid-grator-logo.png"))
        self.assertContains(response, reverse("privacy"))
        self.assertContains(response, reverse("terms"))
        self.assertContains(response, 'href="https://wickywave.pl/"')
        self.assertContains(response, 'src="/static/images/wicky-wave-w.png"')
        self.assertContains(response, "data-cookie-banner")
        self.assertContains(response, "Przetestuj darmowo przez 7 dni — 1 integracja.")
        self.assertContains(response, "korzystając z 1 integracji")
        self.assertContains(response, "Możesz zrezygnować bez opłaty.")
        self.assertContains(response, "płatny rok rozpoczyna się wyłącznie po uzgodnieniu mailowym")
        self.assertContains(response, "<h3>Podstawowy</h3>", html=True)
        self.assertContains(response, "<strong>2</strong> integracje", html=True)
        self.assertContains(response, "<h3>Plus</h3>", html=True)
        self.assertContains(response, "<strong>4</strong> integracje", html=True)
        for price in ("200 PLN", "246 PLN brutto", "400 PLN", "492 PLN brutto"):
            self.assertContains(response, price)
        for name in ("privacy", "terms"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_legal_pages_accessible_during_required_password_change(self):
        user = get_user_model().objects.create_user(username="customer", password="test-password")
        CustomerProfile.objects.create(user=user, must_change_password=True)
        self.client.force_login(user)
        for name in ("privacy", "terms"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertRedirects(self.client.get(reverse("account")), reverse("force_password"))

    @override_settings(GOOGLE_ANALYTICS_ID="G-TEST123")
    def test_analytics_id_is_exposed_to_the_consent_script(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'data-google-analytics-id="G-TEST123"')
        self.assertNotContains(response, "googletagmanager.com")
