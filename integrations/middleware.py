import logging
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import Http404
from django.shortcuts import redirect
from django.urls import Resolver404, resolve
from .models import CustomerProfile, ProjectError

logger = logging.getLogger(__name__)


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
                                        message="Nieobsłużony błąd żądania WWW. Szczegóły w logach serwera.")
        except Exception:
            logger.exception("Nie udało się zapisać błędu do panelu administratora.")
        return None
