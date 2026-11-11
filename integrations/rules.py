import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from .localization import localized


OPERATORS = ("<", "<=", "=", ">", ">=")
NUMBER_PATTERN = re.compile(r"[+-]?(?:[0-9]+(?:[.,][0-9]+)?|[.,][0-9]+)\Z")


def parse_number(value):
    value = value.strip()
    if len(value) > 100 or not NUMBER_PATTERN.fullmatch(value):
        raise ValueError(localized("Podaj liczbę dziesiętną, np. 10 lub 1,5.", "Enter a decimal number, e.g. 10 or 1.5."))
    try:
        return Decimal(value.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(localized("Podaj poprawną liczbę.", "Enter a valid number.")) from exc


def compile_numeric_rules(rules):
    if not isinstance(rules, list) or len(rules) > 100:
        raise ValueError(localized("Podaj listę maksymalnie 100 reguł liczbowych.", "Enter a list of at most 100 numeric rules."))
    compiled = []
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {"operator", "threshold", "result"}:
            raise ValueError(localized("Każda reguła musi zawierać operator, próg i wynik.", "Each rule must contain an operator, threshold and result."))
        operator, threshold, result = rule["operator"], rule["threshold"], rule["result"]
        if not isinstance(operator, str) or operator not in OPERATORS:
            raise ValueError(localized("Wybierz poprawny operator porównania.", "Choose a valid comparison operator."))
        if not isinstance(threshold, str):
            raise ValueError(localized("Próg reguły musi być tekstem zawierającym liczbę.", "The rule threshold must be text containing a number."))
        if not isinstance(result, str) or len(result) > 1000:
            raise ValueError(localized("Wynik reguły musi być tekstem o długości do 1000 znaków.", "The rule result must be text of at most 1,000 characters."))
        compiled.append((operator, parse_number(threshold), result))
    return compiled


def matches_numeric_rule(value, operator, threshold):
    if operator == "<":
        return value < threshold
    if operator == "<=":
        return value <= threshold
    if operator == ">":
        return value > threshold
    if operator == "=":
        return value == threshold
    return value >= threshold


def compile_money_rule(rule):
    if rule is None:
        return None
    if not isinstance(rule, dict) or set(rule) != {"direction", "percent"}:
        raise ValueError(localized("Podaj kierunek i procent reguły pieniężnej.", "Enter the direction and percentage of the price rule."))
    direction, percent = rule["direction"], rule["percent"]
    if direction not in ("increase", "decrease") or not isinstance(percent, str):
        raise ValueError(localized("Podaj poprawny kierunek i procent.", "Enter a valid direction and percentage."))
    amount = parse_number(percent)
    if amount < 0:
        raise ValueError(localized("Procent nie może być ujemny.", "The percentage cannot be negative."))
    return direction, amount


def apply_money_rule(value, rule):
    number = parse_number(value)
    direction, percent = rule
    with localcontext() as context:
        context.prec = 220
        factor = Decimal(1) + (percent / 100 if direction == "increase" else -percent / 100)
        return format((number * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
