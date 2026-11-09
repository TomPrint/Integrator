from contextlib import ExitStack
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import CustomerProfile, Integration
from .services import integration_lock


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
                profile = CustomerProfile.objects.select_for_update().filter(
                    pk=profile_id, plan="trial", trial_started_at__lte=cutoff,
                ).first()
                if profile is None:
                    continue
                integrations = list(Integration.objects.filter(owner_id=profile.user_id).order_by("pk"))
                if [item.pk for item in integrations] != integration_ids:
                    continue
                for item in integrations:
                    if item.output_name:
                        (settings.PRIVATE_DIR / "outputs" / item.output_name).unlink(missing_ok=True)
                Integration.objects.filter(owner_id=profile.user_id).delete()
                profile.plan = "basic"
                profile.trial_ended_at = now
                profile.paid_from = None
                profile.paid_until = None
                profile.save(update_fields=["plan", "trial_ended_at", "paid_from", "paid_until"])
                expired += 1
    return expired
