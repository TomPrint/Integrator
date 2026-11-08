from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("polityka-prywatnosci/", TemplateView.as_view(template_name="privacy.html"), name="privacy"),
    path("regulamin/", TemplateView.as_view(template_name="terms.html"), name="terms"),
    path("robots.txt", TemplateView.as_view(template_name="robots.txt", content_type="text/plain")),
    path("", include("integrations.urls")),
]
