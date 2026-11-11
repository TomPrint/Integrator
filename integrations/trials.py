from contextlib import ExitStack
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import CustomerProfile, Integration
from .services import integration_lock


def delete_integrations(integrations):
    for item in integrations:
        if item.output_name:
            (settings.PRIVATE_DIR / "outputs" / item.output_name).unlink(missing_ok=True)
        item.delete()


def expire_trials(now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(days=7)
    profile_ids = CustomerProfile.objects.filter(
        plan="trial", trial_started_at__lte=cutoff,
    ).values_list("pk", flat=True)

    expired = 0
    for profile_id in profile_ids.iterator():
        integration_ids = list(
            Integration.objects.filter(owner__customer_profile__pk=profile_id)
            .order_by("pk").values_list("pk", flat=True)
        )
        with ExitStack() as locks:
            for integration_id in integration_ids:
                locks.enter_context(integration_lock(integration_id))
            with transaction.atomic():
                user_id = CustomerProfile.objects.filter(pk=profile_id).values_list("user_id", flat=True).first()
                if user_id is None:
                    continue
                get_user_model().objects.filter(pk=user_id).update(is_active=F("is_active"))
                profile = CustomerProfile.objects.select_for_update().filter(
                    pk=profile_id, plan="trial", trial_started_at__lte=cutoff,
                ).first()
                if profile is None:
                    continue
                integrations = list(Integration.objects.filter(owner_id=profile.user_id).order_by("pk"))
                if [item.pk for item in integrations] != integration_ids:
                    continue
                if profile.trial_started_at <= now - timedelta(days=27):
                    delete_integrations(integrations)
                else:
                    Integration.objects.filter(owner_id=profile.user_id).update(active=False)
                if not profile.trial_ended_at:
                    profile.trial_ended_at = profile.trial_expires_at
                    profile.save(update_fields=["trial_ended_at"])
                expired += 1
    return expired
