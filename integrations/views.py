import hashlib
import re
import time
from contextlib import ExitStack
from functools import wraps

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from django.forms import formset_factory
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import get_template
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .forms import (AccountEmailForm, ColumnForm, CustomerAccountEditForm, CustomerCreateForm,
                    CustomerProfileEditForm, InvoiceForm, OutputSettingsForm, PlanForm, SourceForm, TermsAcceptanceForm)
from .models import CustomerProfile, Integration, ProjectError, TermsAcceptance, new_token
from .services import (IntegrationError, fetch_csv, inspect_csv, integration_lock, large_source,
                       output_delimiter_character, publish, source_delimiter_label, source_file, source_size, transform)


def home(request):
    return render(request, "home.html")


def customer_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


@login_required
def integration_list(request):
    if request.user.is_superuser:
        return redirect("admin_dashboard")
    profile, _ = CustomerProfile.objects.get_or_create(user=request.user)
    return render(request, "integrations/list.html", {"integrations": request.user.integrations.all(), "profile": profile})


def add_source_error(form, exc):
    form.add_error("source_url", f"Nie udało się odczytać pliku CSV z tego adresu: {exc} Sprawdź pełny, bezpośredni link, np. https://hurtownia.pl/plik.csv.")


def current_terms():
    template = get_template("terms.html").template
    content = template.source
    return content, hashlib.sha256(content.encode("utf-8")).hexdigest()


def pending_acceptance(request, terms_sha256):
    return TermsAcceptance.objects.filter(
        pk=request.session.get("pending_terms_acceptance"),
        user=request.user, terms_sha256=terms_sha256, consumed_at__isnull=True,
    ).first()


@customer_required
def accept_terms(request):
    profile, _ = CustomerProfile.objects.get_or_create(user=request.user)
    if not InvoiceForm.is_complete(profile):
        request.session["invoice_before_create"] = True
        messages.error(request, "Przed dodaniem integracji uzupełnij dane do faktury.")
        return redirect("invoice")
    content, digest = current_terms()
    form = TermsAcceptanceForm(request.POST if request.method == "POST" else None,
                               initial={"terms_sha256": digest})
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["terms_sha256"] != digest:
            form = TermsAcceptanceForm(initial={"terms_sha256": digest})
            messages.error(request, "Regulamin został zmieniony. Zapoznaj się z aktualną wersją i potwierdź ją ponownie.")
        else:
            acceptance = TermsAcceptance.objects.create(user=request.user, terms_sha256=digest, terms_snapshot=content)
            request.session["pending_terms_acceptance"] = acceptance.pk
            return redirect("create")
    return render(request, "integrations/accept_terms.html", {"form": form})


@customer_required
def create(request):
    profile, _ = CustomerProfile.objects.get_or_create(user=request.user)
    if not InvoiceForm.is_complete(profile):
        request.session["invoice_before_create"] = True
        messages.error(request, "Przed dodaniem integracji uzupełnij dane do faktury: nazwę lub imię i nazwisko, adres oraz e-mail.")
        return redirect("invoice")
    _, digest = current_terms()
    acceptance = pending_acceptance(request, digest)
    if not acceptance:
        return redirect("accept_terms")
    form = SourceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with source_file(fetch_csv(form.cleaned_data["source_url"])) as source:
                size = source_size(source)
                headers, delimiter, encoding = inspect_csv(source)
        except (IntegrationError, OSError) as exc:
            add_source_error(form, exc)
        else:
            try:
                with transaction.atomic():
                    get_user_model().objects.filter(pk=request.user.pk).update(is_active=F("is_active"))
                    profile, _ = CustomerProfile.objects.get_or_create(user=request.user)
                    if not InvoiceForm.is_complete(profile):
                        request.session["invoice_before_create"] = True
                        messages.error(request, "Przed dodaniem integracji uzupełnij dane do faktury: nazwę lub imię i nazwisko, adres oraz e-mail.")
                        return redirect("invoice")
                    if Integration.objects.filter(owner=request.user).count() >= profile.limit:
                        raise IntegrationError(f"Osiągnięto limit {profile.limit} integracji dla Twojego planu.")
                    if TermsAcceptance.objects.filter(pk=acceptance.pk, user=request.user,
                                                      terms_sha256=current_terms()[1],
                                                      consumed_at__isnull=True).update(consumed_at=timezone.now()) != 1:
                        messages.error(request, "Potwierdź aktualny regulamin przed dodaniem integracji.")
                        return redirect("accept_terms")
                    obj = form.save(commit=False)
                    obj.owner = request.user
                    obj.headers, obj.delimiter, obj.encoding = headers, delimiter, encoding
                    obj.source_size_bytes = size
                    obj.save()
                    TermsAcceptance.objects.filter(pk=acceptance.pk).update(integration=obj)
                request.session.pop("pending_terms_acceptance", None)
                return redirect("configure", pk=obj.pk)
            except IntegrationError as exc:
                form.add_error(None, str(exc))
    return render(request, "integrations/create.html", {"form": form})


@customer_required
def configure(request, pk):
    obj = get_object_or_404(Integration, pk=pk, owner=request.user)
    FormSet = formset_factory(ColumnForm, extra=0, max_num=200, validate_max=True)
    rule_draft = request.session.get(f"draft_{pk}")
    existing_columns = rule_draft.get("columns", obj.columns) if isinstance(rule_draft, dict) else obj.columns
    existing = {c["source"]: c for c in existing_columns}
    initial = []
    import json
    source_draft = request.session.get(f"source_{pk}")
    headers = source_draft["headers"] if source_draft else obj.headers
    settings_initial = rule_draft.get("settings") if isinstance(rule_draft, dict) else None
    settings_form = OutputSettingsForm(request.POST if request.method == "POST" else None,
                                       instance=obj, initial=settings_initial,
                                       source_size_bytes=source_draft["size"] if source_draft and "size" in source_draft else obj.source_size_bytes,
                                       source_delimiter=source_draft["delimiter"] if source_draft else obj.delimiter)
    for header in headers:
        col = existing.get(header)
        initial.append({"selected": bool(col) if existing_columns else True,
                        "output_name": col["name"] if col else header,
                        "mapping": json.dumps(col["mapping"], ensure_ascii=False) if col and col["mapping"] else "",
                        "numeric_rules": json.dumps(col.get("numeric_rules", []), ensure_ascii=False) if col and col.get("numeric_rules") else "",
                        "money_direction": col.get("money_rule", {}).get("direction", "") if col else "",
                        "money_percent": col.get("money_rule", {}).get("percent", "") if col else ""})
    formset = FormSet(request.POST or None, initial=initial)
    error = None
    if request.method == "POST":
        request.session.pop(f"draft_{obj.pk}", None)
    formset_valid = formset.is_valid() if request.method == "POST" else False
    settings_valid = settings_form.is_valid() if request.method == "POST" else False
    if formset_valid and settings_valid:
        if len(formset.forms) != len(headers):
            error = "Liczba kolumn nie odpowiada plikowi źródłowemu."
        else:
            columns = [{"source": header, "name": f.cleaned_data["output_name"].strip(),
                        "mapping": f.cleaned_data["mapping"], "numeric_rules": f.cleaned_data["numeric_rules"],
                        **({"money_rule": {"direction": f.cleaned_data["money_direction"], "percent": f.cleaned_data["money_percent"].strip()}}
                           if f.cleaned_data["money_direction"] else {})}
                       for header, f in zip(headers, formset.forms) if f.cleaned_data["selected"]]
            names = [c["name"] for c in columns]
            try:
                if len(names) != len(set(names)):
                    raise IntegrationError("Nazwy kolumn wyjściowych muszą być unikalne.")
                source_url = source_draft["source_url"] if source_draft else obj.source_url
                settings = settings_form.cleaned_data
                output_delimiter = settings["output_delimiter"]
                with source_file(fetch_csv(source_url)) as source:
                    if large_source(source_size(source)) and settings["interval_hours"] < 24:
                        raise IntegrationError("Plik źródłowy ma co najmniej 5 MiB. Wybierz aktualizację co najmniej co 24 godziny.")
                    _, delimiter, _, count, rows = transform(source, columns, output_delimiter=output_delimiter)
                actual_delimiter = output_delimiter_character(output_delimiter, delimiter)
                delimiter_label = source_delimiter_label(actual_delimiter)
                request.session[f"draft_{obj.pk}"] = {"columns": columns, "source": source_draft, "settings": settings,
                                                     "preview": {"names": names, "rows": rows, "count": count, "delimiter": delimiter_label,
                                                                 "interval": dict(Integration.INTERVALS)[settings["interval_hours"]]}}
                return redirect("preview", pk=pk)
            except (IntegrationError, OSError) as exc:
                request.session.pop(f"draft_{obj.pk}", None)
                error = str(exc)
    return render(request, "integrations/configure.html", {
        "integration": obj, "items": zip(headers, formset.forms),
        "formset": formset, "settings_form": settings_form, "error": error,
    })


@customer_required
@require_POST
def confirm(request, pk):
    obj = get_object_or_404(Integration, pk=pk, owner=request.user)
    draft = request.session.get(f"draft_{pk}")
    if not isinstance(draft, dict) or not draft.get("columns"):
        messages.error(request, "Najpierw sprawdź reguły.")
        return redirect("configure", pk=pk)
    try:
        with integration_lock(pk):
            obj = get_object_or_404(Integration, pk=pk, owner=request.user)
            if obj.admin_disabled:
                raise IntegrationError("Integracja została wyłączona przez administratora.")
            values = draft.get("source")
            source_url = values["source_url"] if values else obj.source_url
            settings = draft.get("settings")
            if settings:
                values = {"name": values["name"] if values else obj.name, "source_url": source_url, **settings}
            start = time.monotonic()
            with source_file(fetch_csv(source_url)) as source:
                publish(obj, source, draft["columns"], source_settings=values,
                        started_at=start)
        request.session.pop(f"draft_{pk}", None)
        request.session.pop(f"source_{pk}", None)
        messages.success(request, "Integracja została uruchomiona, a plik opublikowany.")
        if obj.interval_auto_adjusted:
            messages.warning(request, "Plik źródłowy osiągnął 5 MiB. Częstotliwość zmieniono automatycznie na co 24 godziny.")
    except (IntegrationError, OSError) as exc:
        messages.error(request, f"Nie opublikowano pliku: {exc}")
        return redirect("preview", pk=pk)
    return redirect("result", pk=pk)


@customer_required
def edit_source(request, pk):
    obj = get_object_or_404(Integration, pk=pk, owner=request.user)
    if obj.admin_disabled:
        messages.error(request, "Integracja została wyłączona przez administratora.")
        return redirect("result", pk=pk)
    draft = request.session.get(f"source_{pk}")
    form = SourceForm(request.POST or None, instance=obj, initial=draft)
    if request.method == "POST" and form.is_valid():
        try:
            with source_file(fetch_csv(form.cleaned_data["source_url"])) as source:
                size = source_size(source)
                headers, delimiter, encoding = inspect_csv(source)
            request.session[f"source_{pk}"] = {**{k: form.cleaned_data[k] for k in ("name", "source_url")},
                                               "headers": headers, "delimiter": delimiter, "encoding": encoding, "size": size}
            request.session.pop(f"draft_{pk}", None)
            return redirect("configure", pk=pk)
        except (IntegrationError, OSError) as exc:
            add_source_error(form, exc)
    return render(request, "integrations/create.html", {"form": form, "editing": True})


@customer_required
def preview(request, pk):
    obj = get_object_or_404(Integration, pk=pk, owner=request.user)
    draft = request.session.get(f"draft_{pk}")
    if not isinstance(draft, dict) or not draft.get("preview"):
        messages.error(request, "Najpierw sprawdź reguły.")
        return redirect("configure", pk=pk)
    return render(request, "integrations/preview.html", {"integration": obj, "preview": draft["preview"]})


@customer_required
def result(request, pk):
    obj = get_object_or_404(Integration, pk=pk, owner=request.user)
    profile, _ = CustomerProfile.objects.get_or_create(user=request.user)
    count = request.user.integrations.count()
    return render(request, "integrations/result.html", {"integration": obj, "can_create": count < profile.limit,
                                                        "count": count, "limit": profile.limit})


@customer_required
@require_POST
def schedule(request, pk):
    get_object_or_404(Integration, pk=pk, owner=request.user)
    try:
        interval = int(request.POST.get("interval_hours", ""))
    except ValueError:
        interval = 0
    if interval not in dict(Integration.INTERVALS):
        messages.error(request, "Wybierz poprawny interwał.")
    else:
        with integration_lock(pk):
            obj = get_object_or_404(Integration, pk=pk, owner=request.user)
            if large_source(obj.source_size_bytes) and interval < 24:
                messages.error(request, "Plik źródłowy ma co najmniej 5 MiB. Wybierz aktualizację co najmniej co 24 godziny.")
            else:
                obj.interval_hours = interval
                obj.interval_auto_adjusted = False
                obj.save(update_fields=["interval_hours", "interval_auto_adjusted"])
                messages.success(request, "Zmieniono częstotliwość aktualizacji.")
    return redirect("configure", pk=pk)


@customer_required
@require_POST
def delete(request, pk):
    obj = get_object_or_404(Integration, pk=pk, owner=request.user)
    with integration_lock(pk):
        from django.conf import settings
        if obj.output_name:
            (settings.PRIVATE_DIR / "outputs" / obj.output_name).unlink(missing_ok=True)
        obj.delete()
    messages.success(request, "Usunięto integrację.")
    return redirect("integration_list")


@customer_required
@require_POST
def rotate(request, pk):
    obj = get_object_or_404(Integration, pk=pk, owner=request.user)
    obj.token = new_token()
    obj.save(update_fields=["token"])
    messages.success(request, "Utworzono nowy link. Poprzedni przestał działać.")
    return redirect("result", pk=pk)


@never_cache
def download(request, token):
    obj = get_object_or_404(Integration.objects.select_related("owner"), token=token, active=True, admin_disabled=False)
    from django.conf import settings
    try:
        file = (settings.PRIVATE_DIR / "outputs" / obj.output_name).open("rb")
    except FileNotFoundError as exc:
        raise Http404("Plik nie jest dostępny.") from exc
    def filename_part(value, fallback):
        value = re.sub(r"\s+", "_", value.strip())
        value = re.sub(r"[^\w.-]", "", value).strip("._")
        return value[:80] or fallback

    customer = filename_part(obj.owner.get_username(), "klient")
    integration = filename_part(obj.name, "integracja")
    filename = f"{customer}_{integration}.csv"
    response = FileResponse(file, as_attachment=True, filename=filename, content_type="text/csv; charset=utf-8")
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@login_required
def force_password(request):
    if request.user.is_superuser:
        return redirect("admin_dashboard")
    profile, _ = CustomerProfile.objects.get_or_create(user=request.user)
    if not profile.must_change_password:
        return redirect("integration_list")
    form = SetPasswordForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            profile.must_change_password = False
            profile.save(update_fields=["must_change_password"])
        update_session_auth_hash(request, user)
        messages.success(request, "Hasło zostało zmienione.")
        return redirect("integration_list")
    return render(request, "integrations/form.html", {"form": form, "title": "Ustaw nowe hasło"})


@login_required
def account(request):
    action = request.POST.get("action") if request.method == "POST" else None
    email_form = AccountEmailForm(request.POST if action == "email" else None, instance=request.user, prefix="email")
    password_form = PasswordChangeForm(request.user, request.POST if action == "password" else None, prefix="password")
    if request.method == "POST":
        if action == "email":
            if email_form.is_valid():
                request.user.email = email_form.cleaned_data["email"]
                request.user.save(update_fields=["email"])
                messages.success(request, "Zapisano adres e-mail konta.")
                return redirect("account")
        elif action == "password":
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Hasło zostało zmienione.")
                return redirect("account")
        else:
            raise PermissionDenied
    return render(request, "integrations/account.html", {"email_form": email_form, "password_form": password_form})


@customer_required
def invoice(request):
    profile, _ = CustomerProfile.objects.get_or_create(user=request.user)
    form = InvoiceForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Zapisano dane do faktury.")
        if request.session.pop("invoice_before_create", False):
            return redirect("accept_terms")
        return redirect("invoice")
    return render(request, "integrations/form.html", {"form": form, "title": "Dane do faktury"})


def superuser_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def file_size(obj):
    from django.conf import settings
    if not obj.output_name:
        return None
    try:
        return (settings.PRIVATE_DIR / "outputs" / obj.output_name).stat().st_size
    except FileNotFoundError:
        return None


@superuser_required
def admin_dashboard(request):
    users = get_user_model().objects.filter(is_superuser=False).order_by("username")
    clients = []
    for user in users:
        profile, _ = CustomerProfile.objects.get_or_create(user=user)
        clients.append((user, profile, user.integrations.count()))
    integrations = list(Integration.objects.filter(owner__is_superuser=False).select_related("owner").order_by("owner__username", "name"))
    for obj in integrations:
        obj.file_size = file_size(obj)
    legacy_integrations = list(Integration.objects.filter(owner__is_superuser=True).select_related("owner").order_by("owner__username", "name"))
    for obj in legacy_integrations:
        obj.file_size = file_size(obj)
    errors = ProjectError.objects.order_by("-created_at")[:50]
    return render(request, "integrations/admin_dashboard.html", {"clients": clients, "integrations": integrations,
                                                                 "legacy_integrations": legacy_integrations, "errors": errors})


@superuser_required
def admin_create_client(request):
    form = CustomerCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = get_user_model().objects.create_user(username=form.cleaned_data["username"],
                                                         email=form.cleaned_data["email"],
                                                         password=form.cleaned_data["password"])
            CustomerProfile.objects.create(user=user, company_name=form.cleaned_data["company_name"],
                                           must_change_password=True)
        messages.success(request, "Utworzono klienta. Przekaż hasło startowe bezpiecznym kanałem.")
        return redirect("admin_client", pk=user.pk)
    return render(request, "integrations/form.html", {"form": form, "title": "Utwórz klienta"})


@superuser_required
def admin_client(request, pk):
    user = get_object_or_404(get_user_model(), pk=pk, is_superuser=False)
    profile, _ = CustomerProfile.objects.get_or_create(user=user)
    form = PlanForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            get_user_model().objects.filter(pk=user.pk).update(is_active=F("is_active"))
            profile.refresh_from_db()
            form = PlanForm(request.POST, instance=profile)
            if form.is_valid():
                form.save()
                messages.success(request, "Zapisano plan i okres opłacenia.")
                return redirect("admin_client", pk=pk)
    integrations = list(user.integrations.all())
    for obj in integrations:
        obj.file_size = file_size(obj)
    acceptances = user.terms_acceptances.order_by("-accepted_at", "-pk")
    return render(request, "integrations/admin_client.html", {"client": user, "profile": profile,
                                                              "form": form, "integrations": integrations,
                                                              "acceptances": acceptances})


@superuser_required
def admin_edit_client(request, pk):
    user = get_object_or_404(get_user_model(), pk=pk, is_superuser=False)
    profile, _ = CustomerProfile.objects.get_or_create(user=user)
    account_form = CustomerAccountEditForm(request.POST if request.method == "POST" else None,
                                           instance=user, prefix="account")
    profile_form = CustomerProfileEditForm(request.POST if request.method == "POST" else None,
                                          instance=profile, prefix="profile")
    if request.method == "POST":
        account_valid = account_form.is_valid()
        profile_valid = profile_form.is_valid()
        if account_valid and profile_valid:
            with transaction.atomic():
                account_form.save()
                profile_form.save()
            messages.success(request, "Zapisano dane klienta.")
            return redirect("admin_client", pk=pk)
    return render(request, "integrations/admin_edit_client.html", {
        "client": user, "account_form": account_form, "profile_form": profile_form,
    })


@superuser_required
@require_POST
def admin_delete_client(request, pk):
    user = get_object_or_404(get_user_model(), pk=pk, is_superuser=False)
    ids = list(user.integrations.order_by("pk").values_list("pk", flat=True))
    with ExitStack() as locks:
        for integration_id in ids:
            locks.enter_context(integration_lock(integration_id))
        with transaction.atomic():
            if not get_user_model().objects.filter(pk=pk, is_superuser=False).update(is_active=F("is_active")):
                raise Http404
            integrations = list(Integration.objects.filter(owner_id=pk).order_by("pk"))
            if [obj.pk for obj in integrations] != ids:
                messages.error(request, "Lista integracji zmieniła się. Sprawdź dane i ponów usuwanie klienta.")
                return redirect("admin_client", pk=pk)
            from django.conf import settings
            for obj in integrations:
                if obj.output_name:
                    (settings.PRIVATE_DIR / "outputs" / obj.output_name).unlink(missing_ok=True)
            user.delete()
    messages.success(request, "Usunięto klienta, jego integracje i pliki.")
    return redirect("admin_dashboard")


@superuser_required
@require_POST
def admin_disable(request, pk):
    obj = get_object_or_404(Integration, pk=pk)
    with integration_lock(pk):
        obj = get_object_or_404(Integration, pk=pk)
        obj.admin_disabled = not obj.admin_disabled
        obj.save(update_fields=["admin_disabled"])
    messages.success(request, "Zmieniono dostępność integracji.")
    if obj.owner.is_superuser:
        return redirect("admin_dashboard")
    return redirect("admin_client", pk=obj.owner_id)


@superuser_required
@require_POST
def admin_delete(request, pk):
    obj = get_object_or_404(Integration, pk=pk)
    owner_id = obj.owner_id
    owner_is_superuser = obj.owner.is_superuser
    with integration_lock(pk):
        obj = get_object_or_404(Integration, pk=pk)
        from django.conf import settings
        if obj.output_name:
            (settings.PRIVATE_DIR / "outputs" / obj.output_name).unlink(missing_ok=True)
        obj.delete()
    messages.success(request, "Trwale usunięto integrację i jej plik.")
    if owner_is_superuser:
        return redirect("admin_dashboard")
    return redirect("admin_client", pk=owner_id)
