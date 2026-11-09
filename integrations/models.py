from datetime import timedelta
import secrets
from django.conf import settings
from django.db import models
from django.utils import timezone


def new_token():
    return secrets.token_urlsafe(32)


class CustomerProfile(models.Model):
    PLANS = [("basic", "Podstawowy"), ("plus", "Plus"), ("trial", "Testowy (7 dni)")]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="customer_profile")
    company_name = models.CharField(max_length=200, blank=True)
    plan = models.CharField(max_length=10, choices=PLANS, default="basic")
    trial_started_at = models.DateTimeField(null=True, blank=True)
    trial_ended_at = models.DateTimeField(null=True, blank=True)
    paid_from = models.DateField(null=True, blank=True)
    paid_until = models.DateField(null=True, blank=True)
    must_change_password = models.BooleanField(default=False)
    invoice_name = models.CharField(max_length=200, blank=True)
    invoice_nip = models.CharField(max_length=20, blank=True)
    invoice_address = models.TextField(blank=True)
    invoice_email = models.EmailField(blank=True)

    @property
    def limit(self):
        if self.trial_ended_at:
            return 0
        if self.plan == "trial":
            return 1 if self.trial_active else 0
        return 4 if self.plan == "plus" else 2

    @property
    def trial_expires_at(self):
        return self.trial_started_at + timedelta(days=7) if self.trial_started_at else None

    @property
    def trial_active(self):
        return bool(self.plan == "trial" and self.trial_expires_at and self.trial_expires_at > timezone.now())

    @property
    def trial_expired(self):
        return bool(self.trial_ended_at or (
            self.plan == "trial" and self.trial_expires_at and self.trial_expires_at <= timezone.now()
        ))

    @property
    def paid(self):
        today = timezone.localdate()
        return bool(self.paid_from and self.paid_until and self.paid_from <= today <= self.paid_until)


class ProjectError(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    category = models.CharField(max_length=100)
    message = models.CharField(max_length=500)


class Integration(models.Model):
    INTERVALS = [(2, "Co 2 godziny"), (4, "Co 4 godziny"), (8, "Co 8 godzin"),
                 (12, "Co 12 godzin"), (24, "Co 24 godziny"), (48, "Co 48 godzin"), (168, "Raz na tydzień")]
    OUTPUT_DELIMITERS = [
        ("source", "Taki jak w pliku źródłowym"),
        ("semicolon", "Średnik (;)"),
        ("comma", "Przecinek (,)"),
        ("tab", "Tabulator"),
        ("pipe", "Pionowa kreska (|)"),
    ]
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="integrations")
    name = models.CharField(max_length=100)
    source_url = models.URLField(max_length=2048)
    interval_hours = models.PositiveIntegerField(choices=INTERVALS, default=12)
    headers = models.JSONField(default=list)
    delimiter = models.CharField(max_length=1, default=";")
    output_delimiter = models.CharField(max_length=9, choices=OUTPUT_DELIMITERS, default="source")
    encoding = models.CharField(max_length=30, default="utf-8-sig")
    columns = models.JSONField(default=list)
    token = models.CharField(max_length=64, unique=True, default=new_token, editable=False)
    active = models.BooleanField(default=False)
    admin_disabled = models.BooleanField(default=False)
    last_success = models.DateTimeField(null=True, blank=True)
    last_attempt = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    output_name = models.CharField(max_length=200, blank=True)
    last_duration_seconds = models.FloatField(null=True, blank=True)
    source_size_bytes = models.PositiveIntegerField(null=True, blank=True)
    interval_auto_adjusted = models.BooleanField(default=False)
    last_update_delay_seconds = models.PositiveIntegerField(null=True, blank=True)

    @property
    def update_delay_display(self):
        if self.last_update_delay_seconds is None or self.last_update_delay_seconds <= 15 * 60:
            return ""
        hours, remainder = divmod(self.last_update_delay_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours} godz. {minutes} min {seconds} s"
        return f"{minutes} min {seconds} s"

    def __str__(self):
        return self.name


class TermsAcceptance(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="terms_acceptances")
    accepted_at = models.DateTimeField(default=timezone.now)
    terms_sha256 = models.CharField(max_length=64)
    terms_snapshot = models.TextField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    integration = models.ForeignKey(Integration, on_delete=models.SET_NULL, null=True, blank=True)
