import logging
from django.contrib import messages
from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import Http404
from django.shortcuts import redirect
from django.urls import Resolver404, resolve
from django.utils import timezone
from .localization import localized
from .models import CustomerProfile, ProjectError

logger = logging.getLogger(__name__)

CUSTOMER_IDLE_TIMEOUT_SECONDS = 30 * 60
CUSTOMER_LAST_ACTIVITY_SESSION_KEY = "customer_last_activity_at"


class CustomerIdleTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.is_superuser:
            now = timezone.now().timestamp()
            last_activity = request.session.get(CUSTOMER_LAST_ACTIVITY_SESSION_KEY)
            if isinstance(last_activity, (int, float)) and now - last_activity >= CUSTOMER_IDLE_TIMEOUT_SECONDS:
                logout(request)
                messages.warning(
                    request,
                    localized(
                        "Wylogowano Cię po 30 minutach bezczynności. Zaloguj się ponownie.",
                        "You were logged out after 30 minutes of inactivity. Please log in again.",
                    ),
                )
                return redirect("login")
            request.session[CUSTOMER_LAST_ACTIVITY_SESSION_KEY] = now
        return self.get_response(request)


class PasswordChangeRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.is_superuser:
            profile = CustomerProfile.objects.filter(user=request.user).only("must_change_password").first()
            if profile and profile.must_change_password:
                try:
                    name = resolve(request.path_info).url_name
                except Resolver404:
                    name = None
                if name not in ("force_password", "logout", "download", "privacy", "terms"):
                    return redirect("force_password")
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, (Http404, PermissionDenied, SuspiciousOperation)):
            return None
        logger.exception("Nieobsłużony błąd aplikacji", exc_info=exception)
        try:
            ProjectError.objects.create(category=type(exception).__name__,
                                        message=localized("Nieobsłużony błąd żądania WWW. Szczegóły w logach serwera.",
                                                          "Unhandled web request error. See server logs for details."))
        except Exception:
            logger.exception("Nie udało się zapisać błędu do panelu administratora.")
        return None
