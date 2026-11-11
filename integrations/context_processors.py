import json

from django.conf import settings
from django.urls import translate_url
from django.utils.http import url_has_allowed_host_and_scheme


def translated_path(request, language):
    path = translate_url(request.path, language)
    query = request.GET.copy()
    if "next" in query:
        values = query.getlist("next")
        query.setlist("next", [
            translate_url(value, language)
            if value.startswith("/") and not value.startswith("//")
            and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()})
            else value
            for value in values
        ])
    encoded = query.urlencode()
    return f"{path}?{encoded}" if encoded else path


def analytics(request):
    return {"google_analytics_id": settings.GOOGLE_ANALYTICS_ID}


def language_links(request):
    return {
        "polish_url": translated_path(request, "pl"),
        "english_url": translated_path(request, "en"),
    }


def seo(request):
    language = getattr(request, "LANGUAGE_CODE", "pl")
    url_name = getattr(getattr(request, "resolver_match", None), "url_name", None)
    indexable = url_name in {"home", "privacy", "terms"}
    site_url = settings.PUBLIC_SITE_URL or f"{request.scheme}://{request.get_host()}"
    path = request.path or "/"
    canonical_url = f"{site_url}{path}"
    if language == "en":
        title = {
            "home": "Mid-Grator — CSV data integration for businesses",
            "privacy": "Mid-Grator — Privacy policy",
            "terms": "Mid-Grator — Service terms",
        }.get(url_name, "Mid-Grator")
        description = {
            "home": "Mid-Grator transforms wholesaler CSV data into a ready-to-use file for your shop or business integrator.",
            "privacy": "Read the Mid-Grator privacy policy.",
            "terms": "Read the Mid-Grator service terms.",
        }.get(url_name, "")
    else:
        title = {
            "home": "Mid-Grator — integracja danych CSV dla firm",
            "privacy": "Mid-Grator — Polityka prywatności",
            "terms": "Mid-Grator — Regulamin usługi",
        }.get(url_name, "Mid-Grator")
        description = {
            "home": "Mid-Grator przekształca dane CSV z hurtowni w gotowy plik dla sklepu lub integratora firmowego.",
            "privacy": "Przeczytaj politykę prywatności Mid-Grator.",
            "terms": "Przeczytaj regulamin usługi Mid-Grator.",
        }.get(url_name, "")
    data = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "Mid-Grator",
        "url": f"{site_url}{'/en/' if language == 'en' else '/'}",
        "logo": f"{site_url}/static/images/mid-grator-logo.png",
        "email": "kontakt@wickywave.pl",
        "sameAs": ["https://wickywave.pl/"],
    }
    if url_name == "home":
        data = {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": "Mid-Grator",
            "url": f"{site_url}{'/en/' if language == 'en' else '/'}",
            "description": description,
            "publisher": {
                "@type": "Organization",
                "name": "Mid-Grator",
                "url": site_url,
            },
        }
    return {
        "seo_indexable": indexable,
        "seo_title": title,
        "seo_description": description,
        "seo_canonical_url": canonical_url,
        "seo_og_locale": "en_US" if language == "en" else "pl_PL",
        "seo_image_url": f"{site_url}/static/images/mid-grator-logo.png",
        "seo_polish_url": f"{site_url}{translate_url(path, 'pl')}",
        "seo_english_url": f"{site_url}{translate_url(path, 'en')}",
        "seo_json_ld": json.dumps(data, ensure_ascii=False),
    }
