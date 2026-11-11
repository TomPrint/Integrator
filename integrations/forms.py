import json
from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.utils import timezone
from .models import CustomerProfile, Integration
from .localization import localized
from .rules import compile_money_rule, compile_numeric_rules


class SourceURLField(forms.URLField):
    def clean(self, value):
        if value and not value.strip().lower().startswith(("https://", "http://")):
            raise forms.ValidationError(localized("Podaj pełny adres pliku, zaczynający się od https:// (lub http://).", "Enter the full file address, starting with https:// (or http://)."))
        return super().clean(value)


class SourceForm(forms.ModelForm):
    source_url = SourceURLField(
        max_length=2048, label=localized("Adres CSV hurtowni", "Wholesaler CSV address"),
        widget=forms.TextInput(attrs={"inputmode": "url"}),
        help_text=localized("Podaj pełny, bezpośredni adres pliku, np. https://hurtownia.pl/plik.csv. Adres http:// również jest obsługiwany.", "Enter the full, direct file address, e.g. https://example.com/file.csv. HTTP addresses are also supported."),
        error_messages={"invalid": localized("Podaj poprawny, pełny adres pliku, np. https://hurtownia.pl/plik.csv.", "Enter a valid, full file address, e.g. https://example.com/file.csv.")},
    )
    class Meta:
        model = Integration
        fields = ["name", "source_url"]
        labels = {"name": localized("Nazwa", "Name"), "source_url": localized("Adres CSV hurtowni", "Wholesaler CSV address")}


class OutputSettingsForm(forms.ModelForm):
    def __init__(self, *args, source_delimiter, source_size_bytes=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .services import large_source, source_delimiter_label
        label = source_delimiter_label(source_delimiter)
        self.fields["output_delimiter"].choices = [
            (value, f"{text} ({label})" if value == "source" else text)
            for value, text in Integration.OUTPUT_DELIMITERS
        ]
        if large_source(source_size_bytes):
            self.fields["interval_hours"].choices = [
                (value, label) for value, label in Integration.INTERVALS if value >= 24
            ]
            if not self.is_bound and int(self.initial.get("interval_hours", 12)) < 24:
                self.initial["interval_hours"] = 24

    class Meta:
        model = Integration
        fields = ["interval_hours", "output_delimiter"]
        labels = {"interval_hours": localized("Częstotliwość aktualizacji", "Update frequency"), "output_delimiter": localized("Separator pliku wyjściowego", "Output file delimiter")}
        help_texts = {"output_delimiter": localized("Wybierz separator pliku wynikowego lub zachowaj separator wykryty w źródle.", "Choose an output delimiter or keep the one detected in the source.")}
        widgets = {"interval_hours": forms.RadioSelect, "output_delimiter": forms.RadioSelect}


class CustomerCreateForm(forms.Form):
    username = forms.CharField(label=localized("Login", "Username"), max_length=150)
    company_name = forms.CharField(label=localized("Nazwa firmy", "Company name"), max_length=200, required=False)
    email = forms.EmailField(label=localized("E-mail", "Email"), required=False)
    password = forms.CharField(label=localized("Hasło startowe", "Initial password"), widget=forms.PasswordInput)

    def clean_username(self):
        name = self.cleaned_data["username"]
        field = get_user_model()._meta.get_field("username")
        field.clean(name, None)
        if get_user_model().objects.filter(username=name).exists():
            raise forms.ValidationError(localized("Login jest już zajęty.", "This username is already taken."))
        return name

    def clean(self):
        data = super().clean()
        if data.get("password") and data.get("username"):
            user = get_user_model()(username=data["username"], email=data.get("email", ""))
            try:
                password_validation.validate_password(data["password"], user)
            except forms.ValidationError as exc:
                self.add_error("password", exc)
        return data


class AdminResetPasswordForm(forms.Form):
    password = forms.CharField(
        label=localized("Hasło startowe", "Initial password"),
        widget=forms.PasswordInput,
    )
    password_confirmation = forms.CharField(
        label=localized("Powtórz hasło startowe", "Repeat initial password"),
        widget=forms.PasswordInput,
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        data = super().clean()
        password = data.get("password")
        confirmation = data.get("password_confirmation")
        if password and confirmation and password != confirmation:
            self.add_error("password_confirmation", localized("Hasła nie są takie same.", "The passwords do not match."))
        if password and not self.errors:
            try:
                password_validation.validate_password(password, self.user)
            except forms.ValidationError as exc:
                self.add_error("password", exc)
        return data


class AccountEmailForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ["email"]
        labels = {"email": localized("Adres e-mail konta", "Account email address")}
        help_texts = {"email": localized("Ten adres jest niezależny od adresu do faktury.", "This address is separate from the billing email address.")}


class CustomerAccountEditForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ["username", "email"]
        labels = {"username": localized("Login", "Username"), "email": localized("E-mail konta", "Account email")}


class CustomerProfileEditForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = ["company_name", "invoice_name", "invoice_nip", "invoice_address", "invoice_email"]
        labels = {"company_name": localized("Nazwa firmy", "Company name"), "invoice_name": localized("Firma lub imię i nazwisko do faktury", "Company or full name for invoice"),
                  "invoice_nip": "NIP / Tax ID", "invoice_address": localized("Adres do faktury", "Billing address"),
                  "invoice_email": localized("E-mail do faktury", "Billing email")}


class TermsAcceptanceForm(forms.Form):
    accepted = forms.BooleanField(
        required=True,
        label=localized("Potwierdzam, że zapoznałem się z regulaminem i akceptuję jego warunki.",
                        "I confirm that I have read and accept the terms and conditions."),
        error_messages={"required": localized("Aby dodać integrację, potwierdź akceptację regulaminu.",
                                              "Accept the terms and conditions to add an integration.")},
    )
    terms_sha256 = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

class InvoiceForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("invoice_name", "invoice_nip", "invoice_address", "invoice_email"):
            self.fields[field].required = True

    @classmethod
    def is_complete(cls, profile):
        return cls(data={field: getattr(profile, field) for field in cls.Meta.fields}).is_valid()

    class Meta:
        model = CustomerProfile
        fields = ["invoice_name", "invoice_nip", "invoice_address", "invoice_email"]
        labels = {"invoice_name": localized("Firma lub imię i nazwisko", "Company or full name"), "invoice_nip": "NIP / Tax ID",
                  "invoice_address": localized("Adres", "Address"), "invoice_email": localized("E-mail do faktury", "Billing email")}


class PlanForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = ["plan", "paid_from", "paid_until"]
        labels = {"plan": "Plan", "paid_from": localized("Opłacone od", "Paid from"), "paid_until": localized("Opłacone do", "Paid until")}
        widgets = {"plan": forms.RadioSelect,
                   "paid_from": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "paid_until": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def clean(self):
        data = super().clean()
        if data.get("plan") == "trial":
            data["paid_from"] = None
            data["paid_until"] = None
            return data
        start, end = data.get("paid_from"), data.get("paid_until")
        if bool(start) != bool(end):
            raise forms.ValidationError(localized("Podaj obie daty okresu albo pozostaw obie puste.", "Enter both period dates or leave both blank."))
        if start and end and end < start:
            raise forms.ValidationError(localized("Data końcowa nie może być wcześniejsza od początkowej.", "The end date cannot be earlier than the start date."))
        if self.instance.pk and self.instance.plan == "plus" and data.get("plan") == "basic":
            current = CustomerProfile.objects.get(pk=self.instance.pk)
            if current.paid_until and current.paid_until >= timezone.localdate():
                raise forms.ValidationError(localized("Zmiana z Plus na podstawowy jest możliwa po zakończeniu opłaconego okresu.", "You can change from Plus to Basic after the paid period ends."))
            if current.user.integrations.count() > 2:
                raise forms.ValidationError(localized("Przed zmianą planu usuń nadmiarowe integracje, pozostawiając maksymalnie dwie.", "Before changing plans, remove excess integrations so that at most two remain."))
        return data


class ColumnForm(forms.Form):
    selected = forms.BooleanField(required=False, label=localized("Dołącz", "Include"))
    output_name = forms.CharField(max_length=200, required=False, label=localized("Nazwa kolumny wyjściowej", "Output column name"))
    mapping = forms.CharField(required=False, label=localized("Zamiany (JSON)", "Replacements (JSON)"), widget=forms.Textarea(attrs={"rows": 3}),
                              help_text=localized('Opcjonalnie, np. {"1":"10","2":"DOSTĘPNY"}. Puste = bez zmian.', 'Optional, e.g. {"1":"10","2":"AVAILABLE"}. Leave blank for no changes.'))
    numeric_rules = forms.CharField(required=False, label=localized("Reguły liczbowe (JSON)", "Numeric rules (JSON)"), widget=forms.Textarea(attrs={"rows": 3}))
    money_direction = forms.ChoiceField(required=False, label=localized("Reguła pieniężna", "Price rule"),
        choices=[("", localized("Bez zmiany ceny", "Leave price unchanged")), ("increase", localized("Powiększ o procent", "Increase by a percentage")), ("decrease", localized("Pomniejsz o procent", "Decrease by a percentage"))],
        widget=forms.RadioSelect)
    money_percent = forms.CharField(required=False, max_length=100, label=localized("Zmiana w procentach", "Percentage change"))

    def clean_mapping(self):
        text = self.cleaned_data["mapping"].strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"{localized('Niepoprawny JSON', 'Invalid JSON')}: {exc.msg}") from exc
        if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise forms.ValidationError(localized("Podaj obiekt JSON z wartościami tekstowymi w cudzysłowach.", "Enter a JSON object with quoted text values."))
        if any(len(k) > 1000 or len(v) > 1000 for k, v in value.items()):
            raise forms.ValidationError(localized("Wartości w regułach mogą mieć maksymalnie 1000 znaków.", "Rule values may contain at most 1,000 characters."))
        return value

    def clean_numeric_rules(self):
        text = self.cleaned_data["numeric_rules"].strip()
        if not text:
            return []
        try:
            value = json.loads(text)
            compile_numeric_rules(value)
        except (json.JSONDecodeError, ValueError) as exc:
            raise forms.ValidationError(f"{localized('Niepoprawne reguły liczbowe', 'Invalid numeric rules')}: {exc}") from exc
        return value

    def clean(self):
        data = super().clean()
        if data.get("selected") and not data.get("output_name", "").strip():
            self.add_error("output_name", localized("Podaj nazwę kolumny.", "Enter a column name."))
        direction, percent = data.get("money_direction"), data.get("money_percent", "").strip()
        if direction:
            try:
                compile_money_rule({"direction": direction, "percent": percent})
            except ValueError as exc:
                self.add_error("money_percent", str(exc))
            if data.get("mapping") or data.get("numeric_rules"):
                self.add_error("money_direction", localized("Reguły pieniężnej nie można łączyć z zamianami ani regułami liczbowymi w tej samej kolumnie.", "A price rule cannot be combined with replacements or numeric rules in the same column."))
        elif percent:
            self.add_error("money_direction", localized("Wybierz powiększenie albo pomniejszenie lub usuń procent.", "Choose an increase or decrease, or remove the percentage."))
        if data.get("mapping") and data.get("numeric_rules"):
            try:
                old_mapping = json.loads(self.initial.get("mapping") or "{}")
                old_numeric_rules = json.loads(self.initial.get("numeric_rules") or "[]")
            except json.JSONDecodeError:
                old_mapping, old_numeric_rules = {}, []
            if not old_mapping or not old_numeric_rules or data["mapping"] != old_mapping or data["numeric_rules"] != old_numeric_rules:
                self.add_error(None, localized("Wybierz tylko jeden rodzaj reguły: prostą, liczbową albo pieniężną.", "Choose only one rule type: replacement, numeric or price."))
        return data
