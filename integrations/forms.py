import json
from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.utils import timezone
from .models import CustomerProfile, Integration
from .rules import compile_money_rule, compile_numeric_rules


class SourceURLField(forms.URLField):
    def clean(self, value):
        if value and not value.strip().lower().startswith(("https://", "http://")):
            raise forms.ValidationError("Podaj pełny adres pliku, zaczynający się od https:// (lub http://).")
        return super().clean(value)


class SourceForm(forms.ModelForm):
    source_url = SourceURLField(
        max_length=2048, label="Adres CSV hurtowni",
        widget=forms.TextInput(attrs={"inputmode": "url"}),
        help_text="Podaj pełny, bezpośredni adres pliku, np. https://hurtownia.pl/plik.csv. Adres http:// również jest obsługiwany.",
        error_messages={"invalid": "Podaj poprawny, pełny adres pliku, np. https://hurtownia.pl/plik.csv."},
    )
    class Meta:
        model = Integration
        fields = ["name", "source_url"]
        labels = {"name": "Nazwa", "source_url": "Adres CSV hurtowni"}


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
        labels = {"interval_hours": "Częstotliwość aktualizacji", "output_delimiter": "Separator pliku wyjściowego"}
        help_texts = {"output_delimiter": "Wybierz separator pliku wynikowego lub zachowaj separator wykryty w źródle."}
        widgets = {"interval_hours": forms.RadioSelect, "output_delimiter": forms.RadioSelect}


class CustomerCreateForm(forms.Form):
    username = forms.CharField(label="Login", max_length=150)
    company_name = forms.CharField(label="Nazwa firmy", max_length=200, required=False)
    email = forms.EmailField(label="E-mail", required=False)
    password = forms.CharField(label="Hasło startowe", widget=forms.PasswordInput)

    def clean_username(self):
        name = self.cleaned_data["username"]
        field = get_user_model()._meta.get_field("username")
        field.clean(name, None)
        if get_user_model().objects.filter(username=name).exists():
            raise forms.ValidationError("Login jest już zajęty.")
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


class AccountEmailForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ["email"]
        labels = {"email": "Adres e-mail konta"}
        help_texts = {"email": "Ten adres jest niezależny od adresu do faktury."}


class CustomerAccountEditForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ["username", "email"]
        labels = {"username": "Login", "email": "E-mail konta"}


class CustomerProfileEditForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = ["company_name", "invoice_name", "invoice_nip", "invoice_address", "invoice_email"]
        labels = {"company_name": "Nazwa firmy", "invoice_name": "Firma lub imię i nazwisko do faktury",
                  "invoice_nip": "NIP", "invoice_address": "Adres do faktury",
                  "invoice_email": "E-mail do faktury"}


class TermsAcceptanceForm(forms.Form):
    accepted = forms.BooleanField(
        required=True,
        label="Potwierdzam, że zapoznałem się z regulaminem i akceptuję jego warunki.",
        error_messages={"required": "Aby dodać integrację, potwierdź akceptację regulaminu."},
    )
    terms_sha256 = forms.CharField(widget=forms.HiddenInput)


class InvoiceForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("invoice_name", "invoice_address", "invoice_email"):
            self.fields[field].required = True

    @classmethod
    def is_complete(cls, profile):
        return cls(data={field: getattr(profile, field) for field in cls.Meta.fields}).is_valid()

    class Meta:
        model = CustomerProfile
        fields = ["invoice_name", "invoice_nip", "invoice_address", "invoice_email"]
        labels = {"invoice_name": "Firma lub imię i nazwisko", "invoice_nip": "NIP (opcjonalnie)",
                  "invoice_address": "Adres", "invoice_email": "E-mail do faktury"}


class PlanForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = ["plan", "paid_from", "paid_until"]
        labels = {"plan": "Plan", "paid_from": "Opłacone od", "paid_until": "Opłacone do"}
        widgets = {"plan": forms.RadioSelect,
                   "paid_from": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "paid_until": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def clean(self):
        data = super().clean()
        start, end = data.get("paid_from"), data.get("paid_until")
        if bool(start) != bool(end):
            raise forms.ValidationError("Podaj obie daty okresu albo pozostaw obie puste.")
        if start and end and end < start:
            raise forms.ValidationError("Data końcowa nie może być wcześniejsza od początkowej.")
        if self.instance.pk and self.instance.plan == "plus" and data.get("plan") == "basic":
            current = CustomerProfile.objects.get(pk=self.instance.pk)
            if current.paid_until and current.paid_until >= timezone.localdate():
                raise forms.ValidationError("Zmiana z Plus na podstawowy jest możliwa po zakończeniu opłaconego okresu.")
            if current.user.integrations.count() > 2:
                raise forms.ValidationError("Przed zmianą planu usuń nadmiarowe integracje, pozostawiając maksymalnie dwie.")
        return data


class ColumnForm(forms.Form):
    selected = forms.BooleanField(required=False, label="Dołącz")
    output_name = forms.CharField(max_length=200, required=False, label="Nazwa kolumny wyjściowej")
    mapping = forms.CharField(required=False, label="Zamiany (JSON)", widget=forms.Textarea(attrs={"rows": 3}),
                              help_text='Opcjonalnie, np. {"1":"10","2":"DOSTĘPNY"}. Puste = bez zmian.')
    numeric_rules = forms.CharField(required=False, label="Reguły liczbowe (JSON)", widget=forms.Textarea(attrs={"rows": 3}))
    money_direction = forms.ChoiceField(required=False, label="Reguła pieniężna",
        choices=[("", "Bez zmiany ceny"), ("increase", "Powiększ o procent"), ("decrease", "Pomniejsz o procent")],
        widget=forms.RadioSelect)
    money_percent = forms.CharField(required=False, max_length=100, label="Zmiana w procentach")

    def clean_mapping(self):
        text = self.cleaned_data["mapping"].strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"Niepoprawny JSON: {exc.msg}") from exc
        if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise forms.ValidationError("Podaj obiekt JSON z wartościami tekstowymi w cudzysłowach.")
        if any(len(k) > 1000 or len(v) > 1000 for k, v in value.items()):
            raise forms.ValidationError("Wartości w regułach mogą mieć maksymalnie 1000 znaków.")
        return value

    def clean_numeric_rules(self):
        text = self.cleaned_data["numeric_rules"].strip()
        if not text:
            return []
        try:
            value = json.loads(text)
            compile_numeric_rules(value)
        except (json.JSONDecodeError, ValueError) as exc:
            raise forms.ValidationError(f"Niepoprawne reguły liczbowe: {exc}") from exc
        return value

    def clean(self):
        data = super().clean()
        if data.get("selected") and not data.get("output_name", "").strip():
            self.add_error("output_name", "Podaj nazwę kolumny.")
        direction, percent = data.get("money_direction"), data.get("money_percent", "").strip()
        if direction:
            try:
                compile_money_rule({"direction": direction, "percent": percent})
            except ValueError as exc:
                self.add_error("money_percent", str(exc))
            if data.get("mapping") or data.get("numeric_rules"):
                self.add_error("money_direction", "Reguły pieniężnej nie można łączyć z zamianami ani regułami liczbowymi w tej samej kolumnie.")
        elif percent:
            self.add_error("money_direction", "Wybierz powiększenie albo pomniejszenie lub usuń procent.")
        if data.get("mapping") and data.get("numeric_rules"):
            try:
                old_mapping = json.loads(self.initial.get("mapping") or "{}")
                old_numeric_rules = json.loads(self.initial.get("numeric_rules") or "[]")
            except json.JSONDecodeError:
                old_mapping, old_numeric_rules = {}, []
            if not old_mapping or not old_numeric_rules or data["mapping"] != old_mapping or data["numeric_rules"] != old_numeric_rules:
                self.add_error(None, "Wybierz tylko jeden rodzaj reguły: prostą, liczbową albo pieniężną.")
        return data
