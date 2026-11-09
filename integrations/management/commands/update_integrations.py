import logging
import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from integrations.models import Integration, ProjectError
from integrations.services import (IntegrationError, adjust_large_source_schedule, cron_lock, due,
                                   fetch_csv, integration_lock, publish, scheduled_at, source_file, source_size)
from integrations.trials import expire_trials

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Aktualizuje integracje, dla których upłynął wybrany interwał."

    def handle(self, *args, **options):
        with cron_lock() as acquired:
            if not acquired:
                self.stdout.write("Poprzednie zadanie aktualizacji nadal działa; pominięto uruchomienie.")
                return
            try:
                self.update_due_integrations()
            except Exception as exc:
                logger.exception("Nieobsłużony błąd procesu aktualizacji.")
                try:
                    ProjectError.objects.create(category=type(exc).__name__,
                                                message="Nieobsłużony błąd crona. Szczegóły w logach serwera.")
                except Exception:
                    logger.exception("Nie udało się zapisać błędu crona do panelu administratora.")
                raise

    def update_due_integrations(self):
        expired_trials = expire_trials()
        if expired_trials:
            self.stdout.write(f"Zakończono testy i usunięto integracje klientów: {expired_trials}.")
        failures = 0
        candidates = Integration.objects.filter(active=True, admin_disabled=False).only(
            "pk", "last_attempt", "last_success", "interval_hours"
        )
        pending = [item for item in candidates.iterator() if due(item)]
        pending.sort(key=lambda item: (scheduled_at(item) is not None, scheduled_at(item), item.pk))
        for item in pending:
            pk = item.pk
            with integration_lock(pk):
                integration = Integration.objects.filter(pk=pk, active=True, admin_disabled=False).first()
                if not integration or not due(integration):
                    continue
                started = time.monotonic()
                try:
                    with source_file(fetch_csv(integration.source_url)) as source:
                        adjusted = adjust_large_source_schedule(integration, source_size(source))
                        integration.save(update_fields=["source_size_bytes", "interval_hours", "interval_auto_adjusted"])
                        if adjusted and not due(integration):
                            self.stdout.write(f"Integracja {pk}: duży plik, interwał zmieniono na 24 godziny; aktualizacja odłożona.")
                            continue
                        scheduled_for = scheduled_at(integration)
                        integration.last_attempt = timezone.now()
                        integration.save(update_fields=["last_attempt"])
                        publish(integration, source, integration.columns, started_at=started,
                                scheduled_for=scheduled_for)
                    self.stdout.write(f"Integracja {pk}: zaktualizowano.")
                except (IntegrationError, OSError) as exc:
                    integration.last_attempt = timezone.now()
                    integration.last_error = str(exc)
                    integration.last_duration_seconds = time.monotonic() - started
                    integration.save(update_fields=["last_attempt", "last_error", "last_duration_seconds"])
                    logger.warning("Aktualizacja integracji %s nie powiodła się: %s", pk, exc)
                    self.stderr.write(f"Integracja {pk}: {exc}")
                    failures += 1
        if failures:
            raise SystemExit(1)
