from django.test import SimpleTestCase
from django.test import override_settings
from django.urls import reverse


class SEOEndpointTests(SimpleTestCase):
    def test_public_pages_are_indexable_with_language_metadata(self):
        polish = self.client.get("/")
        self.assertContains(polish, '<meta name="robots" content="index,follow">')
        self.assertContains(polish, 'rel="canonical" href="http://testserver/">')
        self.assertContains(polish, 'hreflang="en" href="http://testserver/en/"')
        self.assertContains(polish, 'type="application/ld+json"')
        self.assertContains(polish, "Mid-Grator przekształca dane CSV")

        english = self.client.get("/en/")
        self.assertContains(english, '<meta name="robots" content="index,follow">')
        self.assertContains(english, 'rel="canonical" href="http://testserver/en/"')
        self.assertContains(english, 'hreflang="pl" href="http://testserver/"')
        self.assertContains(english, "Mid-Grator transforms wholesaler CSV")

    def test_robots_and_sitemaps_exclude_private_csv_endpoints(self):
        robots = self.client.get("/robots.txt")
        self.assertContains(robots, "Disallow: /csv/")
        self.assertContains(robots, "Sitemap: http://testserver/sitemap.xml")

        sitemap = self.client.get("/sitemap.xml")
        self.assertTrue(sitemap["Content-Type"].startswith("application/xml"))
        self.assertContains(sitemap, "http://testserver/")
        self.assertContains(sitemap, "http://testserver/en/")
        self.assertNotContains(sitemap, "/csv/")

        text_sitemap = self.client.get("/sitemap.txt")
        self.assertContains(text_sitemap, "http://testserver/regulamin/")
        self.assertNotContains(text_sitemap, "/csv/")

    def test_llms_txt_has_polish_and_english_public_descriptions(self):
        polish = self.client.get("/llms.txt")
        self.assertContains(polish, "Publiczne strony")
        self.assertContains(polish, "nie mogą być indeksowane")
        self.assertNotContains(polish, "/csv/")

        english = self.client.get("/en/llms.txt")
        self.assertContains(english, "Public pages")
        self.assertContains(english, "must not be indexed")
        self.assertNotContains(english, "/csv/")

    def test_authenticated_pages_are_not_indexable(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, '<meta name="robots" content="noindex,nofollow,noarchive">')

    def test_security_txt_has_reporting_contact_and_expiry(self):
        response = self.client.get("/.well-known/security.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertContains(response, "Contact: mailto:kontakt@wickywave.pl")
        self.assertContains(response, "Expires: ")
        self.assertContains(response, "Canonical: http://testserver/.well-known/security.txt")
        self.assertContains(response, "Preferred-Languages: pl, en")

    @override_settings(DEBUG=False)
    def test_unknown_pages_use_the_custom_not_found_page(self):
        polish = self.client.get("/does-not-exist/")
        self.assertEqual(polish.status_code, 404)
        self.assertContains(polish, "Nie znaleziono strony", status_code=404)

        english = self.client.get("/en/does-not-exist/")
        self.assertEqual(english.status_code, 404)
        self.assertContains(english, "Page not found", status_code=404)

    def test_favicon_is_available_from_staticfiles(self):
        from django.contrib.staticfiles import finders

        self.assertIsNotNone(finders.find("images/icon.png"))
