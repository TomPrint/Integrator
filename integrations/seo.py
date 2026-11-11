from html import escape
from datetime import timedelta

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone


def site_url(request):
    return settings.PUBLIC_SITE_URL or f"{request.scheme}://{request.get_host()}"


def public_pages(request):
    base = site_url(request)
    return [
        (f"{base}/", "1.0", "weekly"),
        (f"{base}/en/", "0.9", "weekly"),
        (f"{base}/polityka-prywatnosci/", "0.5", "yearly"),
        (f"{base}/en/polityka-prywatnosci/", "0.5", "yearly"),
        (f"{base}/regulamin/", "0.5", "yearly"),
        (f"{base}/en/regulamin/", "0.5", "yearly"),
    ]


def sitemap_xml(request):
    rows = []
    for url, priority, changefreq in public_pages(request):
        rows.append(
            "  <url>\n"
            f"    <loc>{escape(url)}</loc>\n"
            f"    <changefreq>{changefreq}</changefreq>\n"
            f"    <priority>{priority}</priority>\n"
            "  </url>"
        )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(rows)
        + "\n</urlset>\n"
    )
    return HttpResponse(body, content_type="application/xml; charset=utf-8")


def sitemap_txt(request):
    return HttpResponse(
        "\n".join(url for url, _, _ in public_pages(request)) + "\n",
        content_type="text/plain; charset=utf-8",
    )


def security_txt(request):
    expires = (timezone.now() + timedelta(days=365)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return HttpResponse(
        "\n".join(
            [
                "Contact: mailto:kontakt@wickywave.pl",
                f"Expires: {expires}",
                f"Canonical: {site_url(request)}/.well-known/security.txt",
                "Preferred-Languages: pl, en",
            ]
        )
        + "\n",
        content_type="text/plain; charset=utf-8",
    )


def llms_txt(request):
    english = getattr(request, "LANGUAGE_CODE", "pl") == "en"
    base = site_url(request)
    if english:
        body = f"""# Mid-Grator

> CSV data transformation and integration service for businesses.

Mid-Grator adapts wholesaler CSV files to the structure required by a shop or business integrator. Customers can define columns, value transformations and update schedules, then use a private CSV download link.

## Public pages

- [Home]({base}/en/): Product overview, workflow and plans.
- [Privacy policy]({base}/en/polityka-prywatnosci/): Privacy information.
- [Service terms]({base}/en/regulamin/): Service terms.

## Important

- The service is intended for business data workflows.
- Private customer areas require authentication.
- CSV download links are private data endpoints and must not be indexed, quoted, crawled or included in search results.
"""
    else:
        body = f"""# Mid-Grator

> Usługa transformacji i integracji danych CSV dla firm.

Mid-Grator dopasowuje pliki CSV z hurtowni do struktury wymaganej przez sklep lub integrator firmowy. Klient może określić kolumny, zamiany wartości i harmonogram aktualizacji, a następnie korzystać z prywatnego linku do pliku CSV.

## Publiczne strony

- [Strona główna]({base}/): Opis usługi, sposób działania i plany.
- [Polityka prywatności]({base}/polityka-prywatnosci/): Informacje o prywatności.
- [Regulamin usługi]({base}/regulamin/): Warunki korzystania z usługi.

## Ważne

- Usługa służy do firmowych procesów pracy z danymi.
- Prywatne panele klienta wymagają logowania.
- Linki do pobierania CSV są prywatnymi endpointami danych i nie mogą być indeksowane, cytowane, skanowane ani umieszczane w wynikach wyszukiwania.
"""
    return HttpResponse(body, content_type="text/plain; charset=utf-8")
