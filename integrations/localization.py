import re

from django.utils.functional import lazy
from django.utils.translation import get_language


def _localized(polish, english):
    return english if get_language() == "en" else polish


localized = lazy(_localized, str)


_ERROR_TRANSLATIONS = {
    "Plik wynikowy przekracza limit 20 MiB.": "The output file exceeds the 20 MiB limit.",
    "Podaj poprawny publiczny adres HTTP lub HTTPS bez danych logowania.": "Enter a valid public HTTP or HTTPS address without credentials.",
    "Adres źródła musi wskazywać wyłącznie publiczne adresy IP.": "The source address must resolve only to public IP addresses.",
    "Plik przekracza limit 20 MiB.": "The file exceeds the 20 MiB limit.",
    "Plik źródłowy jest pusty.": "The source file is empty.",
    "Nie rozpoznano kodowania pliku (obsługiwane: UTF-8 i Windows-1250).": "The file encoding could not be detected (supported: UTF-8 and Windows-1250).",
    "Adres zwraca stronę HTML zamiast pliku CSV.": "The address returns an HTML page instead of a CSV file.",
    "Nie można rozpoznać separatora lub nagłówka CSV.": "Could not detect the CSV delimiter or header.",
    "Nagłówek CSV jest pusty lub zawiera niepoprawne nazwy kolumn (limit 200).": "The CSV header is empty or contains invalid column names (limit 200).",
    "Nazwy kolumn w pliku źródłowym muszą być unikalne.": "Source column names must be unique.",
    "Nieznany separator pliku źródłowego.": "Unknown source file delimiter.",
    "Niepoprawny separator pliku wyjściowego.": "Invalid output file delimiter.",
    "Wybierz przynajmniej jedną kolumnę.": "Select at least one column.",
    "Plik przekracza limit 200 000 wierszy.": "The file exceeds the 200,000-row limit.",
    "Plik źródłowy nie zawiera żadnych wierszy danych.": "The source file contains no data rows.",
    "Sprawdź wszystkie wartości w tej kolumnie (pokazano maksymalnie 20 błędów).": "Check all values in this column (at most 20 errors are shown).",
    "Podaj liczbę dziesiętną, np. 10 lub 1,5.": "Enter a decimal number, e.g. 10 or 1.5.",
    "Podaj poprawną liczbę.": "Enter a valid number.",
    "Podaj listę maksymalnie 100 reguł liczbowych.": "Enter a list of at most 100 numeric rules.",
    "Każda reguła musi zawierać operator, próg i wynik.": "Each rule must contain an operator, threshold and result.",
    "Wybierz poprawny operator porównania.": "Choose a valid comparison operator.",
    "Próg reguły musi być tekstem zawierającym liczbę.": "The rule threshold must be text containing a number.",
    "Procent nie może być ujemny.": "The percentage cannot be negative.",
}


def translate_persisted_error(value):
    if get_language() != "en" or not value:
        return value
    if value in _ERROR_TRANSLATIONS:
        return _ERROR_TRANSLATIONS[value]
    patterns = (
        (r"^Źródło odpowiedziało kodem HTTP (\d+); przekierowania nie są obsługiwane\.$",
         r"The source returned HTTP \1; redirects are not supported."),
        (r"^Nie można pobrać pliku źródłowego: ", "Could not download the source file: "),
        (r"^Niepoprawny format CSV: ", "Invalid CSV format: "),
        (r"^Niepoprawne reguły liczbowe: ", "Invalid numeric rules: "),
        (r"^Brakuje kolumn w źródle: ", "Columns missing from the source: "),
        (r"^Wiersz (\d+) ma (\d+) pól zamiast (\d+)\.$",
         r"Row \1 has \2 fields instead of \3."),
        (r"^Niepoprawne reguły liczbowe: ", "Invalid numeric rules: "),
        (r"^Wynik reguły musi być tekstem o długości do 1000 znaków\.$",
         "The rule result must be text of at most 1,000 characters."),
        (r"^Podaj kierunek i procent reguły pieniężnej\.$",
         "Enter the direction and percentage of the price rule."),
        (r"^Podaj poprawny kierunek i procent\.$",
         "Enter a valid direction and percentage."),
        (r"^Wiersz (\d+), kolumna (.*?): niepoprawna wartość liczbowa (.*) dla reguły pieniężnej\.$",
         r"Row \1, column \2: invalid numeric value \3 for the price rule."),
        (r"^Wiersz (\d+), kolumna (.*?): brak reguły dla (.*)\.$",
         r"Row \1, column \2: no rule for \3."),
    )
    for pattern, replacement in patterns:
        translated = re.sub(pattern, replacement, value, count=1)
        if translated != value:
            return translated
    return value
