import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext


OPERATORS = ("<", "<=", "=", ">", ">=")
NUMBER_PATTERN = re.compile(r"[+-]?(?:[0-9]+(?:[.,][0-9]+)?|[.,][0-9]+)\Z")


def parse_number(value):
    value = value.strip()
    if len(value) > 100 or not NUMBER_PATTERN.fullmatch(value):
        raise ValueError("Podaj liczbę dziesiętną, np. 10 lub 1,5.")
    try:
        return Decimal(value.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("Podaj poprawną liczbę.") from exc


def compile_numeric_rules(rules):
    if not isinstance(rules, list) or len(rules) > 100:
        raise ValueError("Podaj listę maksymalnie 100 reguł liczbowych.")
    compiled = []
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {"operator", "threshold", "result"}:
            raise ValueError("Każda reguła musi zawierać operator, próg i wynik.")
        operator, threshold, result = rule["operator"], rule["threshold"], rule["result"]
        if not isinstance(operator, str) or operator not in OPERATORS:
            raise ValueError("Wybierz poprawny operator porównania.")
        if not isinstance(threshold, str):
            raise ValueError("Próg reguły musi być tekstem zawierającym liczbę.")
        if not isinstance(result, str) or len(result) > 1000:
            raise ValueError("Wynik reguły musi być tekstem o długości do 1000 znaków.")
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
        raise ValueError("Podaj kierunek i procent reguły pieniężnej.")
    direction, percent = rule["direction"], rule["percent"]
    if direction not in ("increase", "decrease") or not isinstance(percent, str):
        raise ValueError("Podaj poprawny kierunek i procent.")
    amount = parse_number(percent)
    if amount < 0:
        raise ValueError("Procent nie może być ujemny.")
    return direction, amount


def apply_money_rule(value, rule):
    number = parse_number(value)
    direction, percent = rule
    with localcontext() as context:
        context.prec = 220
        factor = Decimal(1) + (percent / 100 if direction == "increase" else -percent / 100)
        return format((number * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
