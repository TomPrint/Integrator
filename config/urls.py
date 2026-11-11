from django.contrib.auth import views as auth_views
from django.conf.urls.i18n import i18n_patterns
from django.urls import include, path
from django.views.generic import TemplateView
from integrations import views
from integrations.seo import security_txt, sitemap_txt, sitemap_xml

application_patterns = [
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("polityka-prywatnosci/", views.privacy, name="privacy"),
    path("regulamin/", views.terms, name="terms"),
    path("", include("integrations.urls")),
]

urlpatterns = [
    path("robots.txt", TemplateView.as_view(template_name="robots.txt", content_type="text/plain")),
    path("sitemap.xml", sitemap_xml, name="sitemap_xml"),
    path("sitemap.txt", sitemap_txt, name="sitemap_txt"),
    path(".well-known/security.txt", security_txt, name="security_txt"),
    path("csv/<str:token>/", views.download, name="download"),
]
urlpatterns += i18n_patterns(*application_patterns, prefix_default_language=False)

handler404 = "integrations.views.custom_404"
