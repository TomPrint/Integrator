import csv
import codecs
import errno
import http.client
import io
import ipaddress
import logging
import os
import socket
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone

MAX_BYTES = 20 * 1024 * 1024
MAX_COLUMNS = 200
MAX_ROWS = 200_000
MAX_OUTPUT_BYTES = 20 * 1024 * 1024
LARGE_SOURCE_BYTES = 5 * 1024 * 1024
LARGE_SOURCE_INTERVAL = 24
logger = logging.getLogger(__name__)


class IntegrationError(Exception):
    pass


def source_size(source):
    position = source.tell()
    source.seek(0, os.SEEK_END)
    size = source.tell()
    source.seek(position)
    return size


def large_source(size):
    return size is not None and size >= LARGE_SOURCE_BYTES


def adjust_large_source_schedule(integration, size):
    integration.source_size_bytes = size
    if large_source(size) and integration.interval_hours < LARGE_SOURCE_INTERVAL:
        integration.interval_hours = LARGE_SOURCE_INTERVAL
        integration.interval_auto_adjusted = True
        return True
    return False


class LimitedOutput:
    def __init__(self, output):
        self.output = output
        self.size = 3
        if output is not None:
            output.write(codecs.BOM_UTF8)

    def write(self, text):
        data = text.encode("utf-8")
        self.size += len(data)
        if self.size > MAX_OUTPUT_BYTES:
            raise IntegrationError("Plik wynikowy przekracza limit 20 MiB.")
        if self.output is not None:
            self.output.write(data)
        return len(text)


@contextmanager
def source_file(data):
    if isinstance(data, bytes):
        with io.BytesIO(data) as source:
            yield source
    else:
        with data:
            yield data


def fetch_csv(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise IntegrationError("Podaj poprawny publiczny adres HTTP lub HTTPS bez danych logowania.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        addresses = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
        ips = {item[4][0] for item in addresses}
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise IntegrationError("Adres źródła musi wskazywać wyłącznie publiczne adresy IP.")
        address = sorted(ips)[0]
        cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        conn = cls(parts.hostname, port, timeout=30)
        # Pin the validated address; HTTPSConnection still verifies the original hostname.
        conn._create_connection = lambda _addr, timeout, source_address: socket.create_connection(
            (address, port), timeout, source_address
        )
        try:
            target = parts.path or "/"
            if parts.query:
                target += "?" + parts.query
            conn.request("GET", target, headers={"User-Agent": "CSV-Integrator/1.0", "Accept": "text/csv,*/*"})
            response = conn.getresponse()
            if response.status != 200:
                raise IntegrationError(f"Źródło odpowiedziało kodem HTTP {response.status}; przekierowania nie są obsługiwane.")
            temp = tempfile.TemporaryFile(mode="w+b")
            try:
                size = 0
                while True:
                    chunk = response.read(min(65536, MAX_BYTES + 1 - size))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise IntegrationError("Plik przekracza limit 20 MiB.")
                    temp.write(chunk)
                if not size:
                    raise IntegrationError("Plik źródłowy jest pusty.")
                temp.seek(0)
                return temp
            except BaseException:
                temp.close()
                raise
        finally:
            conn.close()
    except IntegrationError:
        raise
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise IntegrationError(f"Nie można pobrać pliku źródłowego: {exc}") from exc


def inspect_csv(source):
    for encoding in ("utf-8-sig", "cp1250"):
        source.seek(0)
        decoder = codecs.getincrementaldecoder(encoding)()
        try:
            while True:
                chunk = source.read(65536)
                if not chunk:
                    decoder.decode(b"", final=True)
                    break
                decoder.decode(chunk)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise IntegrationError("Nie rozpoznano kodowania pliku (obsługiwane: UTF-8 i Windows-1250).")
    source.seek(0)
    text = io.TextIOWrapper(source, encoding=encoding, newline="")
    try:
        sample = text.read(16384)
        if sample.lstrip().lower().startswith(("<!doctype html", "<html")):
            raise IntegrationError("Adres zwraca stronę HTML zamiast pliku CSV.")
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        text.seek(0)
        reader = csv.reader(text, delimiter=dialect.delimiter, strict=True)
        headers = next(reader)
    except (csv.Error, StopIteration) as exc:
        raise IntegrationError("Nie można rozpoznać separatora lub nagłówka CSV.") from exc
    finally:
        text.detach()
    if not headers or len(headers) > MAX_COLUMNS or any(not h or len(h) > 200 for h in headers):
        raise IntegrationError("Nagłówek CSV jest pusty lub zawiera niepoprawne nazwy kolumn (limit 200).")
    if len(set(headers)) != len(headers):
        raise IntegrationError("Nazwy kolumn w pliku źródłowym muszą być unikalne.")
    source.seek(0)
    return headers, dialect.delimiter, encoding


OUTPUT_DELIMITER_CHARACTERS = {"semicolon": ";", "comma": ",", "tab": "\t", "pipe": "|"}
DELIMITER_LABELS = {";": "średnik ;", ",": "przecinek ,", "\t": "tabulator", "|": "pionowa kreska |"}


def source_delimiter_label(delimiter):
    try:
        return DELIMITER_LABELS[delimiter]
    except KeyError as exc:
        raise IntegrationError("Nieznany separator pliku źródłowego.") from exc


def output_delimiter_character(selection, source_delimiter):
    if selection == "source":
        return source_delimiter
    try:
        return OUTPUT_DELIMITER_CHARACTERS[selection]
    except KeyError as exc:
        raise IntegrationError("Niepoprawny separator pliku wyjściowego.") from exc


def transform(source, columns, output=None, output_delimiter="source"):
    headers, delimiter, encoding = inspect_csv(source)
    if not columns:
        raise IntegrationError("Wybierz przynajmniej jedną kolumnę.")
    missing = [c["source"] for c in columns if c["source"] not in headers]
    if missing:
        raise IntegrationError("Brakuje kolumn w źródle: " + ", ".join(missing))
    from .rules import apply_money_rule, compile_money_rule, compile_numeric_rules, matches_numeric_rule, parse_number
    try:
        numeric_rules = [compile_numeric_rules(col.get("numeric_rules", [])) for col in columns]
        money_rules = [compile_money_rule(col.get("money_rule")) for col in columns]
        if any(money and (col["mapping"] or numeric) for col, numeric, money in zip(columns, numeric_rules, money_rules)):
            raise ValueError("Reguły pieniężnej nie można łączyć z innymi regułami tej kolumny.")
    except ValueError as exc:
        raise IntegrationError(f"Niepoprawne reguły liczbowe: {exc}") from exc
    out = LimitedOutput(output)
    writer = csv.writer(out, delimiter=output_delimiter_character(output_delimiter, delimiter), lineterminator="\r\n")
    writer.writerow([c["name"] for c in columns])
    indexes = [headers.index(c["source"]) for c in columns]
    errors = []
    preview = []
    count = 0
    text = io.TextIOWrapper(source, encoding=encoding, newline="")
    try:
        reader = csv.reader(text, delimiter=delimiter, strict=True)
        next(reader)
        for row in reader:
            count += 1
            if count > MAX_ROWS:
                raise IntegrationError("Plik przekracza limit 200 000 wierszy.")
            if len(row) != len(headers):
                raise IntegrationError(f"Wiersz {reader.line_num} ma {len(row)} pól zamiast {len(headers)}.")
            result = []
            for index, col, rules, money in zip(indexes, columns, numeric_rules, money_rules):
                value = row[index]
                mapping = col["mapping"]
                if money:
                    try:
                        result.append(apply_money_rule(value, money))
                    except ValueError:
                        if len(errors) < 20:
                            errors.append(f"Wiersz {reader.line_num}, kolumna {col['source']}: niepoprawna wartość liczbowa {value!r} dla reguły pieniężnej.")
                        result.append(value)
                    continue
                matched = False
                if value in mapping:
                    value = mapping[value]
                    matched = True
                elif rules:
                    try:
                        number = parse_number(value)
                    except ValueError:
                        number = None
                    if number is not None:
                        for operator, threshold, replacement in rules:
                            if matches_numeric_rule(number, operator, threshold):
                                value = replacement
                                matched = True
                                break
                if (mapping or rules) and not matched:
                    if len(errors) < 20:
                        errors.append(f"Wiersz {reader.line_num}, kolumna {col['source']}: brak reguły dla {value!r}.")
                result.append(value)
            writer.writerow(result)
            if len(preview) < 10:
                preview.append(result)
    except csv.Error as exc:
        raise IntegrationError(f"Niepoprawny format CSV: {exc}") from exc
    finally:
        text.detach()
    if errors:
        raise IntegrationError("\n".join(errors) + "\nSprawdź wszystkie wartości w tej kolumnie (pokazano maksymalnie 20 błędów).")
    if not count:
        raise IntegrationError("Plik źródłowy nie zawiera żadnych wierszy danych.")
    return headers, delimiter, encoding, count, preview


@contextmanager
def integration_lock(pk):
    lock_dir = settings.PRIVATE_DIR / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    with open(lock_dir / f"{pk}.lock", "a+b") as lock:
        if os.name == "nt":
            import msvcrt
            if os.fstat(lock.fileno()).st_size == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


@contextmanager
def cron_lock():
    lock_dir = settings.PRIVATE_DIR / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    with open(lock_dir / "cron.lock", "a+b") as lock:
        if os.name == "nt":
            import msvcrt
            if os.fstat(lock.fileno()).st_size == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                yield False
                return
        else:
            import fcntl
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
        try:
            yield True
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def publish(integration, source, columns, source_settings=None, started_at=None, scheduled_for=None):
    size = source_size(source)
    directory = settings.PRIVATE_DIR / "outputs"
    directory.mkdir(parents=True, exist_ok=True)
    old_name = integration.output_name
    path = directory / f"{integration.pk}-{uuid.uuid4().hex}.csv"
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temp:
            temp_name = temp.name
            output_delimiter = source_settings.get("output_delimiter", integration.output_delimiter) if source_settings else integration.output_delimiter
            headers, delimiter, encoding, count, preview = transform(source, columns, temp, output_delimiter)
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    integration.headers = headers
    integration.delimiter = delimiter
    integration.encoding = encoding
    integration.columns = columns
    integration.active = True
    integration.output_name = path.name
    integration.last_success = timezone.now()
    integration.last_update_delay_seconds = (
        max(0, int((integration.last_success - scheduled_for).total_seconds()))
        if scheduled_for else None
    )
    integration.last_attempt = integration.last_success
    integration.last_error = ""
    if source_settings:
        integration.name = source_settings["name"]
        integration.source_url = source_settings["source_url"]
        integration.interval_hours = source_settings["interval_hours"]
        integration.output_delimiter = output_delimiter
        integration.interval_auto_adjusted = False
    adjust_large_source_schedule(integration, size)
    if started_at is not None:
        integration.last_duration_seconds = time.monotonic() - started_at
    try:
        integration.save(update_fields=["headers", "delimiter", "encoding", "columns", "active", "output_name",
                                        "last_success", "last_attempt", "last_error", "name", "source_url",
                                        "interval_hours", "output_delimiter", "last_duration_seconds",
                                        "source_size_bytes", "interval_auto_adjusted", "last_update_delay_seconds"])
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if old_name and old_name != path.name:
        try:
            (directory / old_name).unlink(missing_ok=True)
        except OSError:
            logger.exception("Nie można usunąć poprzedniej wersji pliku integracji %s.", integration.pk)
    return count, preview


def scheduled_at(integration):
    previous = integration.last_attempt or integration.last_success
    return previous + timedelta(hours=integration.interval_hours) if previous else None


def due(integration):
    scheduled = scheduled_at(integration)
    return scheduled is None or scheduled <= timezone.now()
