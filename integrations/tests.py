import csv
import io
import json
import socket
import tempfile
import tracemalloc
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import CustomerProfile, Integration, ProjectError
from .services import (
    IntegrationError, cron_lock, fetch_csv, inspect_csv as inspect_source,
    publish as publish_source, transform as transform_source,
)
from .views import current_terms

SOURCE = b"SKU;STOCK;NAME\r\nA;1;Pierwszy\r\nB;2;Drugi\r\n"
MAPPING = [{"source": "STOCK", "name": "DOSTEPNOSC", "mapping": {"1": "DOSTĘPNY", "2": "0"}},
           {"source": "SKU", "name": "KOD", "mapping": {}}]


def inspect_csv(data):
    with io.BytesIO(data) as source:
        return inspect_source(source)


def transform(data, columns):
    with io.BytesIO(data) as source, io.BytesIO() as output:
        result = transform_source(source, columns, output)
        return (output.getvalue(), *result)


def publish(integration, data, columns):
    with io.BytesIO(data) as source:
        return publish_source(integration, source, columns)


class CSVTests(TestCase):
    def test_numeric_equal_compares_decimal_values(self):
        column = {"source": "STOCK", "name": "STOCK", "mapping": {}, "numeric_rules": [
            {"operator": "=", "threshold": "10", "result": "równe"},
            {"operator": ">", "threshold": "10", "result": "więcej"},
            {"operator": "<", "threshold": "10", "result": "mniej"}]}
        output, *_ = transform(b"SKU;STOCK\nA;10,00\nB;11\nC;9\n", [column])
        self.assertEqual(list(csv.reader(io.StringIO(output.decode("utf-8-sig")), delimiter=";")),
                         [["STOCK"], ["równe"], ["więcej"], ["mniej"]])

    def test_money_rules_rounding_precision_and_invalid_input(self):
        column = {"source": "PRICE", "name": "PRICE", "mapping": {},
                  "money_rule": {"direction": "increase", "percent": "10"}}
        data = b"SKU;PRICE\nA;100\nB;12,345\nC;-12,345\n"
        result, *_ = transform(data, [column])
        self.assertEqual(list(csv.reader(io.StringIO(result.decode("utf-8-sig")), delimiter=";")),
                         [["PRICE"], ["110.00"], ["13.58"], ["-13.58"]])
        column["money_rule"] = {"direction": "decrease", "percent": "10,5"}
        result, *_ = transform(data, [column])
        self.assertEqual(list(csv.reader(io.StringIO(result.decode("utf-8-sig")), delimiter=";"))[1], ["89.50"])
        with self.assertRaisesRegex(IntegrationError, "niepoprawna wartość liczbowa"):
            transform(b"SKU;PRICE\nA;brak\n", [column])
        for rule in ({"direction": "increase", "percent": "-1"}, {"direction": "other", "percent": "10"}):
            with self.subTest(rule=rule), self.assertRaises(IntegrationError):
                transform(data, [{**column, "money_rule": rule}])
        with self.assertRaisesRegex(IntegrationError, "nie można łączyć"):
            transform(data, [{**column, "mapping": {"100": "x"}}])

    def test_html_response_is_not_mistaken_for_csv(self):
        for data in (b'<!DOCTYPE html><html><body>a,b;c</body></html>',
                     b'\xef\xbb\xbf  <HTML><body>a,b;c</body></HTML>'):
            with self.subTest(data=data), self.assertRaisesRegex(IntegrationError, "stronę HTML"):
                inspect_csv(data)

    def test_numeric_comparisons_boundaries_priority_and_exact_mapping(self):
        data = b'SKU;STOCK\nA;-1\nB;0\nC;1,5\nD;10\nE;11\nF;Brak\n'
        columns = [{"source": "STOCK", "name": "STOCK", "mapping": {"Brak": "0", "10": "specjalny"},
                    "numeric_rules": [
                        {"operator": ">=", "threshold": "10", "result": "dużo"},
                        {"operator": ">", "threshold": "0", "result": "dostępny"},
                        {"operator": "<=", "threshold": "0", "result": "niedostępny"},
                    ]}]
        output, *_ = transform(data, columns)
        rows = list(csv.reader(io.StringIO(output.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(rows, [["STOCK"], ["niedostępny"], ["niedostępny"], ["dostępny"],
                                ["specjalny"], ["dużo"], ["0"]])
        columns[0]["mapping"] = {}
        columns[0]["numeric_rules"] = [{"operator": "<", "threshold": "10", "result": "mniej"},
                                       {"operator": ">=", "threshold": "10", "result": "więcej"}]
        result, *_ = transform(b"SKU;STOCK\nA;9,99\nB;10\n", columns)
        self.assertEqual(list(csv.reader(io.StringIO(result.decode("utf-8-sig")), delimiter=";")),
                         [["STOCK"], ["mniej"], ["więcej"]])
        with self.assertRaisesRegex(IntegrationError, "brak reguły"):
            transform(data, columns)

    def test_numeric_rules_invalid_and_missing_matches_are_explicit_errors(self):
        data = b'SKU;STOCK\nA;10\nB;0\n'
        column = {"source": "STOCK", "name": "STOCK", "mapping": {}}
        for rule in [
            {"operator": "!=", "threshold": "10", "result": "x"},
            {"operator": ">", "threshold": "NaN", "result": "x"},
            {"operator": ">", "threshold": 10, "result": "x"},
            {"operator": ">", "threshold": "1e2", "result": "x"},
        ]:
            with self.subTest(rule=rule), self.assertRaisesRegex(IntegrationError, "reguły liczbowe"):
                transform(data, [{**column, "numeric_rules": [rule]}])
        with self.assertRaisesRegex(IntegrationError, "brak reguły"):
            transform(data, [{**column, "numeric_rules": [{"operator": ">", "threshold": "0", "result": "1"}]}])

    def test_output_delimiters_preserve_quoted_values(self):
        data = b'SKU;NAME\nA;"hello, world"\nB;"x|y"\n'
        columns = [{"source": "SKU", "name": "SKU", "mapping": {}},
                   {"source": "NAME", "name": "NAME", "mapping": {}}]
        for choice, delimiter in (("source", ";"), ("semicolon", ";"), ("comma", ","),
                                  ("tab", "\t"), ("pipe", "|")):
            with self.subTest(choice=choice), io.BytesIO(data) as source, io.BytesIO() as output:
                transform_source(source, columns, output, output_delimiter=choice)
                rows = list(csv.reader(io.StringIO(output.getvalue().decode("utf-8-sig")), delimiter=delimiter))
                self.assertEqual(rows, [["SKU", "NAME"], ["A", "hello, world"], ["B", "x|y"]])
        with io.BytesIO(data) as source, self.assertRaisesRegex(IntegrationError, "separator"):
            transform_source(source, columns, output_delimiter="invalid")

    def test_source_output_delimiter_tracks_each_source_file(self):
        columns = [{"source": "SKU", "name": "SKU", "mapping": {}},
                   {"source": "NAME", "name": "NAME", "mapping": {}}]
        for data, delimiter in ((b"SKU;NAME\nA;first\nB;second\n", ";"),
                                (b"SKU,NAME\nA,first\nB,second\n", ",")):
            with self.subTest(delimiter=delimiter), io.BytesIO(data) as source, io.BytesIO() as output:
                transform_source(source, columns, output)
                self.assertIn(f"A{delimiter}first", output.getvalue().decode("utf-8-sig"))

    def test_transform_order_mapping_and_unicode(self):
        result, headers, delimiter, encoding, count, preview = transform(SOURCE, MAPPING)
        rows = list(csv.reader(io.StringIO(result.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(headers, ["SKU", "STOCK", "NAME"])
        self.assertEqual((delimiter, encoding, count), (";", "utf-8-sig", 2))
        self.assertEqual(rows, [["DOSTEPNOSC", "KOD"], ["DOSTĘPNY", "A"], ["0", "B"]])
        self.assertEqual(preview, rows[1:])

    def test_rejects_unmapped_and_missing_columns(self):
        with self.assertRaisesRegex(IntegrationError, "brak reguły"):
            transform(SOURCE, [{"source": "STOCK", "name": "STOCK", "mapping": {"1": "10"}}])
        with self.assertRaisesRegex(IntegrationError, "Brakuje kolumn"):
            transform(SOURCE, [{"source": "UNKNOWN", "name": "X", "mapping": {}}])

    def test_rejects_malformed_and_empty_data(self):
        for data in [b"sku;stock\nA;1;extra\n", b"sku;stock\n"]:
            with self.subTest(data=data), self.assertRaises(IntegrationError):
                transform(data, [{"source": "sku", "name": "sku", "mapping": {}}])

    def test_rejects_duplicate_headers(self):
        with self.assertRaisesRegex(IntegrationError, "unikalne"):
            inspect_csv(b"stock;stock\n1;2\n")

    def test_windows_1250_and_quoted_multiline_fields(self):
        data = 'SKU;NAME\nA;"Zażółć\nGęślą"\n'.encode("cp1250")
        columns = [{"source": "NAME", "name": "Nazwa", "mapping": {}}]
        result, _, delimiter, encoding, count, _ = transform(data, columns)
        self.assertEqual((encoding, delimiter, count), ("cp1250", ";", 1))
        self.assertEqual(list(csv.reader(io.StringIO(result.decode("utf-8-sig")), delimiter=";")),
                         [["Nazwa"], ["Zażółć\nGęślą"]])

    def test_large_file_is_processed_with_bounded_python_memory(self):
        columns = [{"source": "SKU", "name": "SKU", "mapping": {}},
                   {"source": "STOCK", "name": "STOCK", "mapping": {"1": "10"}},
                   {"source": "NAME", "name": "NAME", "mapping": {}}]
        with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as output:
            source.write(b"SKU;STOCK;NAME\n")
            row = b"1234567890;1;" + b"x" * 80 + b"\n"
            for _ in range(60000):
                source.write(row)
            source.seek(0)
            tracemalloc.start()
            try:
                _, _, _, count, _ = transform_source(source, columns, output)
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            self.assertEqual(count, 60000)
            self.assertGreater(output.tell(), 5 * 1024 * 1024)
            self.assertLess(peak, 4 * 1024 * 1024)

    @patch("integrations.services.MAX_OUTPUT_BYTES", 10)
    def test_preview_and_publication_enforce_output_limit(self):
        columns = [{"source": "NAME", "name": "NAME", "mapping": {}}]
        with io.BytesIO(SOURCE) as source, self.assertRaisesRegex(IntegrationError, "plik wynikowy|Plik wynikowy"):
            transform_source(source, columns)
        with io.BytesIO(SOURCE) as source, io.BytesIO() as output, self.assertRaises(IntegrationError):
            transform_source(source, columns, output)

    @patch("integrations.services.socket.getaddrinfo")
    def test_rejects_private_dns_and_mixed_dns(self, lookup):
        for ips in [["127.0.0.1"], ["8.8.8.8", "10.0.0.1"], ["::1"]]:
            lookup.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 80)) for ip in ips]
            with self.subTest(ips=ips), self.assertRaises(IntegrationError):
                fetch_csv("https://example.com/data.csv")

    @patch("integrations.services.MAX_BYTES", 20)
    @patch("integrations.services.http.client.HTTPSConnection")
    @patch("integrations.services.socket.getaddrinfo")
    def test_fetch_streams_and_enforces_exact_limit(self, lookup, connection):
        lookup.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 443))]
        for data, allowed in [(b"x" * 20, True), (b"x" * 21, False)]:
            response = io.BytesIO(data)
            response.status = 200
            connection.return_value.getresponse.return_value = response
            if allowed:
                with fetch_csv("https://example.com/data.csv") as source:
                    self.assertEqual(source.read(), data)
            else:
                with self.assertRaisesRegex(IntegrationError, "przekracza limit"):
                    fetch_csv("https://example.com/data.csv")


class WorkflowTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = override_settings(PRIVATE_DIR=Path(self.temp.name), ALLOWED_HOSTS=["testserver"])
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.addCleanup(self.temp.cleanup)
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="ExamplePassword123!")
        self.other = User.objects.create_user(username="other", password="ExamplePassword123!")
        CustomerProfile.objects.create(user=self.owner, invoice_name="Firma", invoice_nip="1234567890", invoice_address="Warszawa",
                                       invoice_email="faktury@example.org")
        self.client.force_login(self.owner)
        self.client.post(reverse("accept_terms"), {"accepted": "on", "terms_sha256": current_terms()[1]})
        self.integration = Integration.objects.create(owner=self.owner, name="Test", source_url="https://example.com/csv",
                                                      headers=["SKU", "STOCK", "NAME"])

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_creation_requires_complete_invoice_data(self, fetch):
        profile = self.owner.customer_profile
        valid = {"invoice_name": "Firma", "invoice_nip": "1234567890", "invoice_address": "Warszawa", "invoice_email": "faktury@example.org"}
        for field, value in (("invoice_name", ""), ("invoice_name", "  "),
                             ("invoice_address", ""), ("invoice_email", ""), ("invoice_email", "bledny")):
            with self.subTest(field=field, value=value):
                CustomerProfile.objects.filter(pk=profile.pk).update(**{**valid, field: value})
                for method in ("get", "post"):
                    response = getattr(self.client, method)(reverse("create"), {"name": "Nowa", "source_url": "https://example.com/csv"})
                    self.assertRedirects(response, reverse("invoice"))
                self.assertEqual(self.owner.integrations.count(), 1)
                self.assertEqual(self.client.get(reverse("configure", args=[self.integration.pk])).status_code, 200)
        fetch.assert_not_called()
        CustomerProfile.objects.filter(pk=profile.pk).update(**valid)
        response = self.client.post(reverse("create"), {"name": "Nowa", "source_url": "https://example.com/csv"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.owner.integrations.count(), 2)
        fetch.assert_called_once()

    def test_invoice_required_fields_and_nip(self):
        profile = self.owner.customer_profile
        response = self.client.post(reverse("invoice"), {
            "invoice_name": " ", "invoice_address": "", "invoice_email": "zly", "invoice_nip": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.context["form"].errors), {"invoice_name", "invoice_nip", "invoice_address", "invoice_email"})
        profile.refresh_from_db()
        self.assertEqual(profile.invoice_name, "Firma")
        response = self.client.post(reverse("invoice"), {
            "invoice_name": "Nowa firma", "invoice_address": "Kraków", "invoice_email": "nowy@example.org", "invoice_nip": "123",
        })
        self.assertRedirects(response, reverse("invoice"))
        profile.refresh_from_db()
        self.assertEqual(profile.invoice_nip, "123")
        self.assertEqual(profile.invoice_name, "Nowa firma")

    def test_login_security_headers_and_csrf(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        login = client.get(reverse("login"))
        self.assertEqual(login.headers["Referrer-Policy"], "same-origin")
        self.assertContains(login, 'name="csrfmiddlewaretoken"')
        token = client.cookies["csrftoken"].value
        response = client.post(reverse("login"), {
            "username": "owner", "password": "ExamplePassword123!", "csrfmiddlewaretoken": token,
        }, HTTP_ORIGIN="http://testserver")
        self.assertRedirects(response, reverse("integration_list"))
        client.logout()
        login = client.get(reverse("login"))
        token = client.cookies["csrftoken"].value
        response = client.post(reverse("login"), {
            "username": "owner", "password": "ExamplePassword123!", "csrfmiddlewaretoken": token,
        }, HTTP_ORIGIN="null")
        self.assertEqual(response.status_code, 403)

    def data(self):
        data = {"form-TOTAL_FORMS": "3", "form-INITIAL_FORMS": "3", "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "200",
                "interval_hours": "12", "output_delimiter": "source"}
        for index, name in enumerate(["SKU", "STOCK", "NAME"]):
            data[f"form-{index}-selected"] = "on"
            data[f"form-{index}-output_name"] = name
            data[f"form-{index}-mapping"] = '{"1":"10","2":"0"}' if name == "STOCK" else ""
        return data

    def test_account_email_is_private_and_validated(self):
        response = self.client.get(reverse("integration_list"))
        self.assertContains(response, reverse("account"))
        self.assertContains(response, "Dane Faktury")
        response = self.client.post(reverse("account"), {"action": "email", "email-email": "invalid"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["email_form"].errors)
        self.owner.refresh_from_db()
        self.assertNotEqual(self.owner.email, "invalid")
        response = self.client.post(reverse("account"), {"action": "email", "email-email": "owner@example.com"})
        self.assertRedirects(response, reverse("account"))
        self.owner.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.owner.email, "owner@example.com")
        self.assertNotEqual(self.other.email, "owner@example.com")
        self.client.logout()
        response = self.client.get(reverse("account"))
        self.assertRedirects(response, f'{reverse("login")}?next={reverse("account")}')

    def test_account_password_change_requires_current_and_preserves_session(self):
        self.owner.set_password("ExistingStrongPassword412!")
        self.owner.save()
        self.client.force_login(self.owner)
        from django.test import Client
        other_session = Client()
        other_session.force_login(self.owner)
        data = {"action": "password", "password-old_password": "wrong",
                "password-new_password1": "NewStrongPassword348!", "password-new_password2": "NewStrongPassword348!"}
        response = self.client.post(reverse("account"), data)
        self.assertIn("old_password", response.context["password_form"].errors)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password("ExistingStrongPassword412!"))
        response = self.client.post(reverse("account"), {**data, "password-old_password": "ExistingStrongPassword412!",
                                    "password-new_password1": "short", "password-new_password2": "short"})
        self.assertIn("new_password2", response.context["password_form"].errors)
        response = self.client.post(reverse("account"), {**data, "password-old_password": "ExistingStrongPassword412!"})
        self.assertRedirects(response, reverse("account"))
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password("NewStrongPassword348!"))
        self.assertEqual(self.client.get(reverse("account")).status_code, 200)
        self.assertEqual(other_session.get(reverse("account")).status_code, 302)

    def test_account_requires_csrf_and_first_password_change(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(reverse("account"), {"action": "email", "email-email": "a@example.com"}).status_code, 403)
        CustomerProfile.objects.filter(user=self.owner).update(must_change_password=True)
        self.assertRedirects(client.get(reverse("account")), reverse("force_password"))
        self.assertRedirects(client.post(reverse("account"), {"action": "email", "email-email": "a@example.com"}), reverse("force_password"))

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_money_rule_preview_save_edit_and_cron(self, _fetch):
        data = self.data()
        data["form-1-mapping"] = ""
        data["form-1-money_direction"] = "increase"
        data["form-1-money_percent"] = "10"
        response = self.client.post(reverse("configure", args=[self.integration.pk]), data, follow=True)
        self.assertContains(response, "1.10")
        self.client.post(reverse("confirm", args=[self.integration.pk]))
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.columns[1]["money_rule"], {"direction": "increase", "percent": "10"})
        response = self.client.get(reverse("configure", args=[self.integration.pk]))
        self.assertEqual(response.context["formset"].forms[1]["money_direction"].value(), "increase")
        self.assertEqual(response.context["formset"].forms[1]["money_percent"].value(), "10")
        Integration.objects.filter(pk=self.integration.pk).update(last_attempt=timezone.now() - timedelta(days=1))
        with patch("integrations.management.commands.update_integrations.fetch_csv", return_value=SOURCE):
            call_command("update_integrations", stdout=io.StringIO())
        self.integration.refresh_from_db()
        path = Path(self.temp.name) / "outputs" / self.integration.output_name
        self.assertIn(b"A;1.10;Pierwszy", path.read_bytes())
        previous = path.read_bytes()
        Integration.objects.filter(pk=self.integration.pk).update(last_attempt=timezone.now() - timedelta(days=1))
        with patch("integrations.management.commands.update_integrations.fetch_csv", return_value=b"SKU;STOCK;NAME\nA;brak;Nazwa\n"):
            with self.assertRaises(SystemExit):
                call_command("update_integrations", stdout=io.StringIO(), stderr=io.StringIO())
        self.integration.refresh_from_db()
        self.assertIn("niepoprawna wartość liczbowa", self.integration.last_error)
        self.assertEqual(path.read_bytes(), previous)

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_money_rule_rejects_conflict_and_invalid_percent(self, fetch):
        data = {**self.data(), "form-1-money_direction": "increase", "form-1-money_percent": "10"}
        response = self.client.post(reverse("configure", args=[self.integration.pk]), data)
        self.assertContains(response, "nie można łączyć")
        fetch.assert_not_called()
        data["form-1-mapping"] = ""
        data["form-1-money_percent"] = "brak"
        response = self.client.post(reverse("configure", args=[self.integration.pk]), data)
        self.assertContains(response, "Podaj liczbę dziesiętną")
        fetch.assert_not_called()

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_numeric_and_mapping_are_exclusive_but_existing_combination_is_preserved(self, fetch):
        data = self.data()
        rules = [{"operator": ">", "threshold": "0", "result": "1"}]
        data["form-1-numeric_rules"] = json.dumps(rules)
        response = self.client.post(reverse("configure", args=[self.integration.pk]), data)
        self.assertContains(response, "Wybierz tylko jeden rodzaj reguły")
        fetch.assert_not_called()
        columns = [{"source": "SKU", "name": "SKU", "mapping": {}},
                   {"source": "STOCK", "name": "STOCK", "mapping": {"1": "10", "2": "0"}, "numeric_rules": rules},
                   {"source": "NAME", "name": "NAME", "mapping": {}}]
        publish(self.integration, SOURCE, columns)
        response = self.client.post(reverse("configure", args=[self.integration.pk]), data)
        self.assertRedirects(response, reverse("preview", args=[self.integration.pk]))
        data["form-1-numeric_rules"] = json.dumps([{"operator": ">", "threshold": "1", "result": "1"}])
        response = self.client.post(reverse("configure", args=[self.integration.pk]), data)
        self.assertContains(response, "Wybierz tylko jeden rodzaj reguły")

    @patch("integrations.views.fetch_csv")
    def test_source_url_validation_for_create_and_edit(self, fetch):
        data = {"name": "New", "source_url": "example.com/data.csv", "interval_hours": "12"}
        for name, args in (("create", []), ("edit_source", [self.integration.pk])):
            url = reverse(name, args=args)
            with self.subTest(view=name, case="missing scheme"):
                response = self.client.post(url, data)
                self.assertFormError(response.context["form"], "source_url",
                                     "Podaj pełny adres pliku, zaczynający się od https:// (lub http://).")
                self.assertContains(response, 'class="source-url-field"')
                self.assertContains(response, 'aria-invalid="true"')
                self.assertContains(response, 'id="id_source_url_helptext"')
                fetch.assert_not_called()
            with self.subTest(view=name, case="bad address"):
                response = self.client.post(url, {**data, "source_url": "https://"})
                self.assertIn("pełny adres", str(response.context["form"].errors["source_url"]))
                fetch.assert_not_called()
            with self.subTest(view=name, case="not found"):
                fetch.side_effect = IntegrationError("Źródło odpowiedziało kodem HTTP 404.")
                response = self.client.post(url, {**data, "source_url": "https://example.com/data.csv"})
                self.assertIn("HTTP 404", str(response.context["form"].errors["source_url"]))
                self.assertIn("https://", str(response.context["form"].errors["source_url"]))
                fetch.reset_mock()
            with self.subTest(view=name, case="html"):
                fetch.side_effect = None
                fetch.return_value = b"<!doctype html><html><body>a,b;c</body></html>"
                response = self.client.post(url, {**data, "source_url": "https://example.com/data.csv"})
                self.assertIn("stronę HTML", str(response.context["form"].errors["source_url"]))
                fetch.reset_mock()
        self.assertEqual(Integration.objects.filter(owner=self.owner).count(), 1)
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.source_url, "https://example.com/csv")
        for name, args in (("create", []), ("edit_source", [self.integration.pk])):
            response = self.client.get(reverse(name, args=args))
            self.assertContains(response, 'type="text" name="source_url"')
            self.assertContains(response, 'inputmode="url"')

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_source_url_supports_https_with_query_and_http(self, fetch):
        for url in ("https://example.com/download.php?file=items.csv", "http://example.com/items.csv"):
            with self.subTest(url=url):
                response = self.client.post(reverse("edit_source", args=[self.integration.pk]),
                                            {"name": "Test", "source_url": url, "interval_hours": "12"})
                self.assertRedirects(response, reverse("configure", args=[self.integration.pk]))
                fetch.assert_called_with(url)
        self.assertContains(self.client.get(reverse("create")), "Podaj pełny, bezpośredni adres pliku")

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_numeric_rules_create_preview_publish_edit_and_cron(self, _fetch):
        data = self.data()
        data["form-1-mapping"] = ""
        rules = [{"operator": ">=", "threshold": "2", "result": "Duża ilość"},
                 {"operator": "<", "threshold": "2", "result": "Mała ilość"}]
        data["form-1-numeric_rules"] = json.dumps(rules, ensure_ascii=False)
        response = self.client.post(reverse("configure", args=[self.integration.pk]), data, follow=True)
        self.assertContains(response, "Duża ilość")
        self.assertContains(response, "Mała ilość")
        self.assertEqual(self.client.post(reverse("confirm", args=[self.integration.pk])).status_code, 302)
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.columns[1]["numeric_rules"], rules)
        path = Path(self.temp.name) / "outputs" / self.integration.output_name
        self.assertIn("A;Mała ilość;Pierwszy", path.read_text(encoding="utf-8-sig"))
        response = self.client.get(reverse("configure", args=[self.integration.pk]))
        self.assertContains(response, "Duża ilość")
        Integration.objects.filter(pk=self.integration.pk).update(last_attempt=timezone.now() - timedelta(days=1))
        with patch("integrations.management.commands.update_integrations.fetch_csv", return_value=SOURCE):
            call_command("update_integrations", stdout=io.StringIO())
        self.integration.refresh_from_db()
        path = Path(self.temp.name) / "outputs" / self.integration.output_name
        self.assertIn("B;Duża ilość;Drugi", path.read_text(encoding="utf-8-sig"))
        previous = path.read_bytes()
        Integration.objects.filter(pk=self.integration.pk).update(last_attempt=timezone.now() - timedelta(days=1))
        with patch("integrations.management.commands.update_integrations.fetch_csv", return_value=b"SKU;STOCK;NAME\nA;brak;Nazwa\n"):
            with self.assertRaises(SystemExit):
                call_command("update_integrations", stdout=io.StringIO(), stderr=io.StringIO())
        self.integration.refresh_from_db()
        self.assertIn("brak reguły", self.integration.last_error)
        self.assertEqual(path.read_bytes(), previous)

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_numeric_rules_form_rejects_malformed_input(self, _fetch):
        data = self.data()
        data["form-1-numeric_rules"] = '[{"operator":">=","threshold":"abc","result":"x"}]'
        response = self.client.post(reverse("configure", args=[self.integration.pk]), data)
        self.assertContains(response, "Niepoprawne reguły liczbowe")
        self.integration.refresh_from_db()
        self.assertFalse(self.integration.active)

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_preview_confirm_download_and_access_control(self, fetch):
        response = self.client.post(reverse("configure", args=[self.integration.pk]), self.data(), follow=True)
        self.assertContains(response, "Weryfikacja poprawna")
        self.integration.refresh_from_db()
        self.assertFalse(self.integration.active)
        response = self.client.post(reverse("confirm", args=[self.integration.pk]))
        self.assertEqual(response.status_code, 302)
        self.integration.refresh_from_db()
        self.assertTrue(self.integration.active)
        self.assertEqual(fetch.call_count, 2)
        self.client.logout()
        response = self.client.get(reverse("download", args=[self.integration.token]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="owner_Test.csv"')
        self.assertIn(b"A;10;Pierwszy", b"".join(response.streaming_content))
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("configure", args=[self.integration.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("delete", args=[self.integration.pk])).status_code, 404)

    def test_download_filename_cleans_unsafe_characters_and_preserves_unicode(self):
        self.owner.username = "Zażółć"
        self.owner.save(update_fields=["username"])
        self.integration.name = "../Oferta / Warszawa"
        self.integration.save(update_fields=["name"])
        publish(self.integration, SOURCE, MAPPING)
        response = self.client.get(reverse("download", args=[self.integration.token]))
        self.addCleanup(response.close)
        self.assertEqual(
            response["Content-Disposition"],
            "attachment; filename*=utf-8''Za%C5%BC%C3%B3%C5%82%C4%87_Oferta__Warszawa.csv",
        )

    def test_result_displays_link_only_for_active_available_integration(self):
        publish(self.integration, SOURCE, MAPPING)
        url = reverse("download", args=[self.integration.token])
        response = self.client.get(reverse("result", args=[self.integration.pk]))
        self.assertContains(response, url)
        self.assertContains(response, "Wartości zostały zmienione zgodnie z określonymi regułami.")
        self.assertContains(response, "integratorze sklepu")
        self.assertContains(response, "Traktuj link jak hasło")
        self.integration.admin_disabled = True
        self.integration.save(update_fields=["admin_disabled"])
        response = self.client.get(reverse("result", args=[self.integration.pk]))
        self.assertContains(response, "Integracja wstrzymana przez administratora")
        self.assertNotContains(response, url)
        self.integration.admin_disabled = False
        self.integration.active = False
        self.integration.save(update_fields=["admin_disabled", "active"])
        response = self.client.get(reverse("result", args=[self.integration.pk]))
        self.assertContains(response, "Integracja nie została jeszcze opublikowana")
        self.assertNotContains(response, url)

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_edit_preserves_link_and_replaces_previous_output(self, fetch):
        publish(self.integration, SOURCE, MAPPING)
        token = self.integration.token
        url = reverse("download", args=[token])
        output_dir = Path(self.temp.name) / "outputs"
        old_path = output_dir / self.integration.output_name
        old_content = old_path.read_bytes()
        self.client.post(reverse("edit_source", args=[self.integration.pk]),
                         {"name": "Nowa nazwa", "source_url": "https://example.com/new"})
        response = self.client.post(reverse("configure", args=[self.integration.pk]), self.data())
        self.assertRedirects(response, reverse("preview", args=[self.integration.pk]))
        response = self.client.get(url)
        self.assertEqual(b"".join(response.streaming_content), old_content)
        fetch.return_value = b"bad"
        self.client.post(reverse("confirm", args=[self.integration.pk]))
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.token, token)
        self.assertEqual(old_path.read_bytes(), old_content)
        fetch.return_value = SOURCE
        self.assertRedirects(self.client.post(reverse("confirm", args=[self.integration.pk])),
                             reverse("result", args=[self.integration.pk]))
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.token, token)
        self.assertNotEqual(self.integration.output_name, old_path.name)
        self.assertFalse(old_path.exists())
        self.assertEqual([p.name for p in output_dir.iterdir()], [self.integration.output_name])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"A;10;Pierwszy", b"".join(response.streaming_content))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_download_filename_uses_fallback_for_empty_component(self):
        self.integration.name = "..."
        self.integration.save(update_fields=["name"])
        publish(self.integration, SOURCE, MAPPING)
        response = self.client.get(reverse("download", args=[self.integration.token]))
        self.addCleanup(response.close)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="owner_integracja.csv"')

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_two_integration_limit(self, _fetch):
        Integration.objects.create(owner=self.owner, name="second", source_url="https://example.com/x")
        response = self.client.post(reverse("create"), {"name": "third", "source_url": "https://example.com/csv", "interval_hours": "12"})
        self.assertContains(response, "limit 2 integracji")
        self.assertEqual(Integration.objects.filter(owner=self.owner).count(), 2)

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_basic_customer_can_add_second_but_not_third(self, _fetch):
        response = self.client.get(reverse("result", args=[self.integration.pk]))
        self.assertContains(response, reverse("create"))
        self.assertContains(response, "Wykorzystano 1 z 2")
        for path in (reverse("create"), reverse("edit_source", args=[self.integration.pk])):
            response = self.client.get(path)
            self.assertNotContains(response, 'name="interval_hours"')
            self.assertNotContains(response, 'name="output_delimiter"')
        response = self.client.get(reverse("configure", args=[self.integration.pk]))
        for value in (2, 4, 8, 12, 24, 168):
            self.assertContains(response, f'value="{value}"')
        data = {"name": "Second", "source_url": "https://example.com/csv", "interval_hours": "8"}
        response = self.client.post(reverse("create"), data)
        second = Integration.objects.get(owner=self.owner, name="Second")
        self.assertRedirects(response, reverse("configure", args=[second.pk]))
        self.assertEqual(second.interval_hours, 12)
        response = self.client.get(reverse("result", args=[self.integration.pk]))
        self.assertNotContains(response, reverse("create"))
        self.assertContains(response, "Wykorzystano 2 z 2")
        self.client.post(reverse("accept_terms"), {"accepted": "on", "terms_sha256": current_terms()[1]})
        response = self.client.post(reverse("create"), {**data, "name": "Third", "interval_hours": "24"})
        self.assertContains(response, "limit 2 integracji")
        self.assertEqual(Integration.objects.filter(owner=self.owner).count(), 2)

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_new_intervals_can_be_saved_on_create_and_edit(self, _fetch):
        data = {"name": "Daily", "source_url": "https://example.com/csv", "interval_hours": "24"}
        self.assertEqual(self.client.post(reverse("create"), data).status_code, 302)
        obj = Integration.objects.get(owner=self.owner, name="Daily")
        self.client.post(reverse("configure", args=[obj.pk]), {**self.data(), "interval_hours": "24"})
        self.client.post(reverse("confirm", args=[obj.pk]))
        obj.refresh_from_db()
        self.assertEqual(obj.interval_hours, 24)
        response = self.client.post(reverse("schedule", args=[obj.pk]), {"interval_hours": "8"})
        self.assertEqual(response.status_code, 302)
        obj.refresh_from_db()
        self.assertEqual(obj.interval_hours, 8)

    def test_new_intervals_are_respected_by_scheduler(self):
        from .services import due

        now = timezone.now()
        for hours in (8, 24):
            self.integration.interval_hours = hours
            self.integration.last_attempt = now - timedelta(hours=hours) + timedelta(minutes=5)
            self.assertFalse(due(self.integration))
            self.integration.last_attempt = now - timedelta(hours=hours) - timedelta(minutes=5)
            self.assertTrue(due(self.integration))

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_output_delimiter_edit_is_staged_and_used_in_preview_publication_and_cron(self, fetch):
        publish(self.integration, SOURCE, MAPPING)
        old_path = Path(self.temp.name) / "outputs" / self.integration.output_name
        old_data = old_path.read_bytes()
        response = self.client.post(reverse("edit_source", args=[self.integration.pk]), {
            "name": "Test", "source_url": "https://example.com/csv",
            "interval_hours": "12", "output_delimiter": "comma",
        })
        self.assertRedirects(response, reverse("configure", args=[self.integration.pk]))
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.output_delimiter, "source")
        self.assertEqual(old_path.read_bytes(), old_data)
        response = self.client.post(reverse("configure", args=[self.integration.pk]), {**self.data(), "output_delimiter": "comma", "interval_hours": "8"}, follow=True)
        self.assertContains(response, "przecinek ,")
        self.assertContains(response, "Co 8 godzin")
        response = self.client.get(reverse("configure", args=[self.integration.pk]))
        self.assertEqual(response.context["settings_form"]["output_delimiter"].value(), "comma")
        self.assertEqual(response.context["settings_form"]["interval_hours"].value(), 8)
        fetch.return_value = b"bad"
        self.client.post(reverse("confirm", args=[self.integration.pk]))
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.output_delimiter, "source")
        self.assertEqual(self.integration.interval_hours, 12)
        self.assertEqual(old_path.read_bytes(), old_data)
        fetch.return_value = SOURCE
        self.client.post(reverse("confirm", args=[self.integration.pk]))
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.output_delimiter, "comma")
        self.assertEqual(self.integration.interval_hours, 8)
        output = Path(self.temp.name) / "outputs" / self.integration.output_name
        self.assertIn(b"A,10,Pierwszy", output.read_bytes())
        Integration.objects.filter(pk=self.integration.pk).update(last_attempt=timezone.now() - timedelta(days=1))
        with patch("integrations.management.commands.update_integrations.fetch_csv", return_value=SOURCE):
            call_command("update_integrations", stdout=io.StringIO())
        self.integration.refresh_from_db()
        output = Path(self.temp.name) / "outputs" / self.integration.output_name
        self.assertIn(b"A,10,Pierwszy", output.read_bytes())

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_create_accepts_output_delimiter_and_rejects_invalid_choice(self, _fetch):
        data = {"name": "Z tabulatorem", "source_url": "https://example.com/csv",
                "interval_hours": "12", "output_delimiter": "tab"}
        response = self.client.post(reverse("create"), data)
        obj = Integration.objects.get(owner=self.owner, name="Z tabulatorem")
        self.assertRedirects(response, reverse("configure", args=[obj.pk]))
        self.assertEqual(obj.output_delimiter, "source")
        response = self.client.post(reverse("configure", args=[obj.pk]), {**self.data(), "output_delimiter": "invalid"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["settings_form"].errors.as_data()["output_delimiter"][0].code, "invalid_choice")
        response = self.client.post(reverse("configure", args=[obj.pk]), {**self.data(), "output_delimiter": "tab", "interval_hours": "4"})
        self.assertRedirects(response, reverse("preview", args=[obj.pk]))
        self.client.post(reverse("confirm", args=[obj.pk]))
        obj.refresh_from_db()
        self.assertEqual((obj.output_delimiter, obj.interval_hours), ("tab", 4))
        self.assertEqual(Integration.objects.filter(owner=self.owner).count(), 2)

    @patch("integrations.views.fetch_csv")
    def test_detected_separator_for_new_and_staged_source(self, fetch):
        labels = ((";", "średnik ;"), (",", "przecinek ,"),
                  ("\t", "tabulator"), ("|", "pionowa kreska |"))
        for delimiter, label in labels:
            with self.subTest(delimiter=delimiter):
                fetch.return_value = f"SKU{delimiter}STOCK\nA{delimiter}1\nB{delimiter}2\n".encode()
                response = self.client.post(reverse("edit_source", args=[self.integration.pk]),
                                            {"name": "Test", "source_url": "https://example.com/csv"})
                self.assertRedirects(response, reverse("configure", args=[self.integration.pk]))
                response = self.client.get(reverse("configure", args=[self.integration.pk]))
                self.assertContains(response, f"Taki jak w pliku źródłowym ({label})")
                self.assertContains(response, 'type="radio" name="interval_hours"', count=7)
                self.assertContains(response, 'type="radio" name="output_delimiter"', count=5)

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_confirmation_revalidates_current_source(self, fetch):
        self.client.post(reverse("configure", args=[self.integration.pk]), self.data())
        fetch.return_value = b"SKU;STOCK;NAME\nA;5;Name\n"
        response = self.client.post(reverse("confirm", args=[self.integration.pk]), follow=True)
        self.assertContains(response, "brak reguły")
        self.integration.refresh_from_db()
        self.assertFalse(self.integration.active)

    @patch("integrations.management.commands.update_integrations.fetch_csv")
    def test_failed_cron_keeps_last_file_and_records_error(self, fetch):
        publish(self.integration, SOURCE, MAPPING)
        output_path = Path(self.temp.name) / "outputs" / self.integration.output_name
        old = output_path.read_bytes()
        Integration.objects.filter(pk=self.integration.pk).update(last_attempt=timezone.now() - timedelta(hours=13))
        fetch.return_value = b"SKU;STOCK;NAME\nA;5;Name\n"
        with self.assertRaises(SystemExit):
            call_command("update_integrations", stdout=io.StringIO(), stderr=io.StringIO())
        self.integration.refresh_from_db()
        self.assertIn("brak reguły", self.integration.last_error)
        self.assertEqual(output_path.read_bytes(), old)
        self.assertEqual(list(output_path.parent.iterdir()), [output_path])

    @patch("integrations.management.commands.update_integrations.fetch_csv")
    def test_cron_only_refreshes_when_due(self, fetch):
        publish(self.integration, SOURCE, MAPPING)
        first_name = self.integration.output_name
        call_command("update_integrations", stdout=io.StringIO())
        fetch.assert_not_called()
        Integration.objects.filter(pk=self.integration.pk).update(last_attempt=timezone.now() - timedelta(hours=13))
        fetch.return_value = SOURCE
        call_command("update_integrations", stdout=io.StringIO())
        self.integration.refresh_from_db()
        self.assertNotEqual(first_name, self.integration.output_name)
        self.assertEqual(self.integration.last_error, "")
        self.assertFalse((Path(self.temp.name) / "outputs" / first_name).exists())
        self.assertTrue((Path(self.temp.name) / "outputs" / self.integration.output_name).exists())

    def test_cron_overlap_is_skipped(self):
        with cron_lock() as acquired:
            self.assertTrue(acquired)
            output = io.StringIO()
            call_command("update_integrations", stdout=output)
            self.assertIn("pominięto", output.getvalue())

    def test_customer_can_pause_and_resume_integration(self):
        publish(self.integration, SOURCE, MAPPING)
        toggle_url = reverse("toggle_integration", args=[self.integration.pk])
        self.assertRedirects(self.client.post(toggle_url), reverse("result", args=[self.integration.pk]))
        self.integration.refresh_from_db()
        self.assertTrue(self.integration.customer_disabled)
        self.assertEqual(self.client.get(reverse("download", args=[self.integration.token])).status_code, 404)
        self.assertRedirects(self.client.post(toggle_url), reverse("result", args=[self.integration.pk]))
        self.integration.refresh_from_db()
        self.assertFalse(self.integration.customer_disabled)
        response = self.client.get(reverse("download", args=[self.integration.token]))
        self.assertEqual(response.status_code, 200)
        response.close()
        self.integration.admin_disabled = True
        self.integration.save(update_fields=["admin_disabled"])
        self.assertRedirects(self.client.post(toggle_url), reverse("result", args=[self.integration.pk]))
        self.integration.refresh_from_db()
        self.assertTrue(self.integration.admin_disabled)
        self.assertFalse(self.integration.customer_disabled)


class AdminAndPlanTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = override_settings(PRIVATE_DIR=Path(self.temp.name), ALLOWED_HOSTS=["testserver"])
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.addCleanup(self.temp.cleanup)
        User = get_user_model()
        self.admin = User.objects.create_superuser("admin", password="StrongPassword132!")
        self.client_user = User.objects.create_user("client", password="ClientPassword123!")
        self.profile = CustomerProfile.objects.create(user=self.client_user, invoice_name="Firma",
                                                      invoice_address="Warszawa", invoice_email="faktury@example.org")
        self.client.force_login(self.admin)

    def test_public_home_and_protected_panels(self):
        self.client.logout()
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Mid-Grator")
        self.assertContains(response, "Plik CSV hurtowni")
        self.assertContains(response, "Przetworzenie pól pliku")
        self.assertContains(response, "Wymagania integratora sklepu")
        html = response.content.decode()
        self.assertLess(html.index("01 · CSV hurtowni"), html.index('class="csv-flow-section"'))
        self.assertLess(html.index('class="csv-flow-section"'), html.index("Jak to działa"))
        self.assertContains(response, "kontakt@wickywave.pl")
        self.assertContains(response, "mailto:kontakt@wickywave.pl")
        self.assertContains(response, 'content="noindex,nofollow"')
        for name in ("integration_list", "create", "invoice", "admin_dashboard"):
            self.assertRedirects(self.client.get(reverse(name)), f'{reverse("login")}?next={reverse(name)}')
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)

    def test_admin_has_no_customer_panel_or_customer_actions(self):
        own = Integration.objects.create(owner=self.admin, name="Starsza", source_url="https://example.com/x")
        response = self.client.get(reverse("integration_list"))
        self.assertRedirects(response, reverse("admin_dashboard"))
        response = self.client.get(reverse("admin_dashboard"))
        self.assertContains(response, "Wcześniejsze integracje")
        self.assertContains(response, "Starsza")
        self.assertNotContains(response, f'href="{reverse("create")}"')
        self.assertNotContains(response, f'href="{reverse("invoice")}"')
        for name, args in (("create", []), ("invoice", []), ("configure", [own.pk]),
                           ("edit_source", [own.pk]), ("preview", [own.pk]), ("result", [own.pk])):
            with self.subTest(view=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)
        for name, args in (("create", []), ("invoice", []), ("configure", [own.pk]),
                           ("edit_source", [own.pk]), ("confirm", [own.pk]), ("schedule", [own.pk]),
                           ("delete", [own.pk]), ("toggle_integration", [own.pk])):
            with self.subTest(view=name):
                self.assertEqual(self.client.post(reverse(name, args=args)).status_code, 403)
        self.assertTrue(Integration.objects.filter(pk=own.pk).exists())
        self.assertFalse(CustomerProfile.objects.filter(user=self.admin).exists())

    def test_dashboard_shows_update_interval_and_last_success(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        Integration.objects.create(owner=self.client_user, name="Gotowa", source_url="https://example.com/x",
                                   interval_hours=2, active=True, last_success=datetime(2026, 11, 7, 21, 5, tzinfo=ZoneInfo("Europe/Warsaw")),
                                   last_attempt=datetime(2026, 11, 7, 23, 5, tzinfo=ZoneInfo("Europe/Warsaw")),
                                   last_duration_seconds=1.67, last_error="Błąd źródła")
        Integration.objects.create(owner=self.client_user, name="Nowa", source_url="https://example.com/y", interval_hours=168)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertContains(response, "Ostatnia poprawna aktualizacja")
        self.assertContains(response, "Częstotliwość aktualizacji")
        self.assertContains(response, "7 listopada 2026 21:05")
        self.assertNotContains(response, "7 listopada 2026 23:05")
        self.assertContains(response, "Co 2 godziny")
        self.assertContains(response, "Raz na tydzień")
        self.assertContains(response, "<td>brak</td>", html=True)
        self.assertContains(response, "Błąd źródła")

    def test_admin_login_reaches_admin_dashboard(self):
        self.admin.set_password("TestAdminPassword123!")
        self.admin.save()
        self.client.logout()
        response = self.client.post(reverse("login"), {"username": "admin", "password": "TestAdminPassword123!"}, follow=True)
        self.assertEqual(response.redirect_chain, [(reverse("integration_list"), 302), (reverse("admin_dashboard"), 302)])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Panel administratora")
        self.assertContains(response, reverse("account"))
        self.assertEqual(self.client.get(reverse("account")).status_code, 200)

    def test_legacy_admin_integration_can_be_stopped_and_deleted(self):
        own = Integration.objects.create(owner=self.admin, name="Starsza", source_url="https://example.com/x")
        publish(own, SOURCE, MAPPING)
        url = reverse("download", args=[own.token])
        self.client.logout()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response.close()
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.post(reverse("admin_disable", args=[own.pk])), reverse("admin_dashboard"))
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertRedirects(self.client.post(reverse("admin_delete", args=[own.pk])), reverse("admin_dashboard"))
        self.assertFalse(Integration.objects.filter(pk=own.pk).exists())

    def test_admin_can_upgrade_client_plan(self):
        response = self.client.get(reverse("admin_client", args=[self.client_user.pk]))
        self.assertContains(response, 'type="radio" name="plan" value="basic"')
        self.assertContains(response, 'type="radio" name="plan" value="plus"')
        today = timezone.localdate()
        response = self.client.post(reverse("admin_client", args=[self.client_user.pk]), {
            "plan": "plus", "paid_from": today.isoformat(), "paid_until": (today + timedelta(days=365)).isoformat(),
        })
        self.assertRedirects(response, reverse("admin_client", args=[self.client_user.pk]))
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.plan, self.profile.limit), ("plus", 4))

    def test_admin_can_upgrade_without_payment_dates_and_sees_invalid_period(self):
        url = reverse("admin_client", args=[self.client_user.pk])
        response = self.client.post(url, {"plan": "plus", "paid_from": "2026-01-01", "paid_until": ""})
        self.assertContains(response, "Podaj obie daty okresu albo pozostaw obie puste.")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, "basic")
        response = self.client.post(url, {"plan": "plus", "paid_from": "", "paid_until": ""})
        self.assertRedirects(response, url)
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.plan, self.profile.limit), ("plus", 4))

    def test_create_client_requires_password_change_and_denies_admin_access(self):
        self.assertContains(self.client.get(reverse("admin_create_client")), "Nazwa firmy")
        response = self.client.post(reverse("admin_create_client"), {
            "username": "nowy", "company_name": "Firma ABC", "email": "nowy@example.org", "password": "StrongInitialPassword982!",
        })
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username="nowy")
        self.assertTrue(user.customer_profile.must_change_password)
        self.assertEqual(user.customer_profile.company_name, "Firma ABC")
        self.assertEqual(user.customer_profile.invoice_name, "")
        self.assertEqual(user.customer_profile.plan, "trial")
        self.assertTrue(user.customer_profile.trial_active)
        self.assertContains(self.client.get(reverse("admin_dashboard")), "Firma ABC")
        self.assertContains(self.client.get(reverse("admin_client", args=[user.pk])), "Firma ABC")
        self.client.logout()
        self.assertTrue(self.client.login(username="nowy", password="StrongInitialPassword982!"))
        self.assertRedirects(self.client.get(reverse("integration_list")), reverse("force_password"))
        self.assertRedirects(self.client.get(reverse("admin_dashboard")), reverse("force_password"))
        response = self.client.post(reverse("force_password"), {
            "new_password1": "NewVeryStrongPassword835!", "new_password2": "NewVeryStrongPassword835!",
        })
        self.assertRedirects(response, reverse("integration_list"))
        user.customer_profile.refresh_from_db()
        self.assertFalse(user.customer_profile.must_change_password)
        self.assertEqual(self.client.get(reverse("admin_dashboard")).status_code, 403)
        self.assertRedirects(self.client.get(reverse("force_password")), reverse("integration_list"))
        self.assertFalse(self.client.login(username="nowy", password="StrongInitialPassword982!"))
        self.assertTrue(self.client.login(username="nowy", password="NewVeryStrongPassword835!"))

    def test_create_client_company_name_is_optional_and_limited(self):
        data = {"username": "nowy", "email": "", "password": "StrongInitialPassword982!"}
        response = self.client.post(reverse("admin_create_client"), {**data, "company_name": "x" * 201})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username="nowy").exists())
        response = self.client.post(reverse("admin_create_client"), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(get_user_model().objects.get(username="nowy").customer_profile.company_name, "")

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_plus_limit_is_four_even_if_expired(self, _fetch):
        self.profile.plan = "plus"
        self.profile.paid_until = timezone.localdate() - timedelta(days=1)
        self.profile.save()
        for i in range(3):
            Integration.objects.create(owner=self.client_user, name=str(i), source_url="https://example.com/x")
        self.client.force_login(self.client_user)
        self.client.post(reverse("accept_terms"), {"accepted": "on", "terms_sha256": current_terms()[1]})
        data = {"name": "fourth", "source_url": "https://example.com/csv", "interval_hours": "12"}
        self.assertEqual(self.client.post(reverse("create"), data).status_code, 302)
        self.assertEqual(self.client_user.integrations.count(), 4)
        self.client.post(reverse("accept_terms"), {"accepted": "on", "terms_sha256": current_terms()[1]})
        response = self.client.post(reverse("create"), data)
        self.assertContains(response, "limit 4 integracji")
        Integration.objects.create(owner=self.client_user, name="Starsza", source_url="https://example.com/x")
        self.assertEqual(self.client_user.integrations.count(), 5)
        self.assertContains(self.client.get(reverse("integration_list")), "Starsza")
        self.assertContains(self.client.post(reverse("create"), data), "limit 4 integracji")
        self.assertEqual(self.client_user.integrations.count(), 5)

    def test_plan_cannot_downgrade_until_expired_and_excess_removed(self):
        today = timezone.localdate()
        self.profile.plan = "plus"
        self.profile.paid_from = today - timedelta(days=3)
        self.profile.paid_until = today + timedelta(days=3)
        self.profile.save()
        objects = [Integration.objects.create(owner=self.client_user, name=str(i), source_url="https://example.com/x") for i in range(3)]
        data = {"plan": "basic", "paid_from": today.isoformat(), "paid_until": (today + timedelta(days=365)).isoformat()}
        response = self.client.post(reverse("admin_client", args=[self.client_user.pk]), data)
        self.assertContains(response, "po zakończeniu opłaconego okresu")
        self.profile.paid_until = today - timedelta(days=1)
        self.profile.save(update_fields=["paid_until"])
        response = self.client.post(reverse("admin_client", args=[self.client_user.pk]), data)
        self.assertContains(response, "usuń nadmiarowe")
        self.client.post(reverse("admin_delete", args=[objects[0].pk]))
        response = self.client.post(reverse("admin_client", args=[self.client_user.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.plan, "basic")
        self.assertEqual(self.profile.paid_until, today + timedelta(days=365))

    def test_disable_blocks_cron_download_then_reenable_and_delete(self):
        obj = Integration.objects.create(owner=self.client_user, name="Test", source_url="https://example.com/x")
        publish(obj, SOURCE, MAPPING)
        path = Path(self.temp.name) / "outputs" / obj.output_name
        url = reverse("download", args=[obj.token])
        self.client.post(reverse("admin_disable", args=[obj.pk]))
        self.assertEqual(self.client.get(url).status_code, 404)
        with patch("integrations.management.commands.update_integrations.fetch_csv") as fetch:
            Integration.objects.filter(pk=obj.pk).update(last_attempt=timezone.now() - timedelta(days=1))
            call_command("update_integrations", stdout=io.StringIO())
            fetch.assert_not_called()
        self.assertTrue(path.exists())
        self.client.post(reverse("admin_disable", args=[obj.pk]))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response.close()
        self.client.post(reverse("admin_delete", args=[obj.pk]))
        self.assertFalse(path.exists())
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertFalse(Integration.objects.filter(pk=obj.pk).exists())

    def test_invoice_private_and_displayed_to_admin(self):
        self.client.force_login(self.client_user)
        self.client.post(reverse("invoice"), {"invoice_name": "Firma ABC XYZ", "invoice_nip": "123",
                                               "invoice_address": "Warszawa", "invoice_email": "a@example.org"})
        other = get_user_model().objects.create_user("other", password="OtherPassword321!")
        self.client.force_login(other)
        self.assertNotContains(self.client.get(reverse("invoice")), "Firma ABC XYZ")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("admin_client", args=[self.client_user.pk])), "Firma ABC XYZ")
        self.assertContains(self.client.get(reverse("admin_dashboard")), "<td>Firma ABC XYZ</td>", html=True)
        self.client.force_login(self.client_user)
        self.client.post(reverse("invoice"), {"invoice_name": "Nowa firma", "invoice_nip": "123",
                                               "invoice_address": "Warszawa", "invoice_email": "a@example.org"})
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertContains(response, "<td>Nowa firma</td>", html=True)
        self.assertNotContains(response, "Firma ABC XYZ")

    @patch("integrations.views.fetch_csv", return_value=SOURCE)
    def test_edit_source_is_staged_until_confirm(self, fetch):
        obj = Integration.objects.create(owner=self.client_user, name="Old", source_url="https://example.com/old",
                                         headers=["SKU", "STOCK", "NAME"])
        publish(obj, SOURCE, MAPPING)
        self.client.force_login(self.client_user)
        response = self.client.post(reverse("edit_source", args=[obj.pk]),
                                    {"name": "New", "source_url": "https://example.com/new", "interval_hours": 4})
        self.assertEqual(response.status_code, 302)
        obj.refresh_from_db()
        self.assertEqual(obj.name, "Old")
        data = {"form-TOTAL_FORMS": "3", "form-INITIAL_FORMS": "3", "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "200",
                "interval_hours": "4", "output_delimiter": "source"}
        for i, header in enumerate(["SKU", "STOCK", "NAME"]):
            data[f"form-{i}-selected"] = "on"
            data[f"form-{i}-output_name"] = header
            data[f"form-{i}-mapping"] = ""
        response = self.client.post(reverse("configure", args=[obj.pk]), data)
        self.assertRedirects(response, reverse("preview", args=[obj.pk]))
        response = self.client.get(reverse("configure", args=[obj.pk]))
        self.assertContains(response, 'value="SKU"')
        fetch.return_value = b"bad"
        self.client.post(reverse("confirm", args=[obj.pk]))
        obj.refresh_from_db()
        self.assertEqual((obj.name, obj.source_url), ("Old", "https://example.com/old"))
        fetch.return_value = SOURCE
        self.client.post(reverse("confirm", args=[obj.pk]))
        obj.refresh_from_db()
        self.assertEqual((obj.name, obj.source_url, obj.interval_hours), ("New", "https://example.com/new", 4))

    def test_http_404_is_not_recorded_as_project_error(self):
        self.client.get(reverse("download", args=["not-a-token"]))
        self.assertFalse(ProjectError.objects.exists())

    def test_unhandled_error_is_recorded_without_sensitive_details(self):
        Integration.objects.create(owner=self.client_user, name="Test", source_url="https://example.com/x")
        self.client.raise_request_exception = False
        with patch("integrations.views.file_size", side_effect=RuntimeError("secret-internal-detail")):
            response = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(response.status_code, 500)
        error = ProjectError.objects.get()
        self.assertEqual(error.category, "RuntimeError")
        self.assertNotIn("secret-internal-detail", error.message)
