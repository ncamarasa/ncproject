from __future__ import annotations

from datetime import date


def parse_date_input(value: str | None) -> date | None:
    if not value:
        return None
    normalized = (value or "").strip()
    if "/" in normalized:
        parts = normalized.split("/")
        if len(parts) == 3:
            try:
                day, month, year = [int(part) for part in parts]
                return date(year, month, day)
            except ValueError:
                return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None

