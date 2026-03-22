from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_decimal_input(value: str | None) -> Decimal | None:
    """Parsea números con separadores locales/internacionales a Decimal.

    Acepta ejemplos como:
    - 1234.56
    - 1,234.56
    - 1.234,56
    - $ 1.234,56
    - US$ 1,234.56
    - 150.000 / 150,000
    """
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if not raw:
        return None

    compact = "".join(ch for ch in raw if ch.isdigit() or ch in {".", ",", "-"})
    if not compact:
        return None
    if compact.count("-") > 1 or ("-" in compact and not compact.startswith("-")):
        return None

    cleaned = compact
    has_dot = "." in cleaned
    has_comma = "," in cleaned

    if has_dot and has_comma:
        last_dot = cleaned.rfind(".")
        last_comma = cleaned.rfind(",")
        decimal_sep = "." if last_dot > last_comma else ","
        thousands_sep = "," if decimal_sep == "." else "."
        cleaned = cleaned.replace(thousands_sep, "")
        if decimal_sep == ",":
            cleaned = cleaned.replace(",", ".")
    elif has_dot:
        dot_count = cleaned.count(".")
        if dot_count > 1:
            cleaned = cleaned.replace(".", "")
        else:
            left, right = cleaned.split(".", 1)
            if len(right) == 3 and left not in {"", "-"}:
                cleaned = f"{left}{right}"
    elif has_comma:
        comma_count = cleaned.count(",")
        if comma_count > 1:
            cleaned = cleaned.replace(",", "")
        else:
            left, right = cleaned.split(",", 1)
            if len(right) == 3 and left not in {"", "-"}:
                cleaned = f"{left}{right}"
            else:
                cleaned = cleaned.replace(",", ".")

    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def format_decimal_local(value, places: int = 2) -> str:
    if value in (None, ""):
        return "-"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    rendered = f"{amount:,.{places}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return rendered


def format_decimal_input(value, places: int = 2) -> str:
    if value in (None, ""):
        return ""
    return format_decimal_local(value, places)
