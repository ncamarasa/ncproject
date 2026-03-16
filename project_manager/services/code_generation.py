from __future__ import annotations

import re
import unicodedata
from sqlalchemy import select

from project_manager.extensions import db

CLIENT_CODE_PATTERN = re.compile(r"^([A-Z0-9]{3})(\d{2})$")
PROJECT_CODE_PATTERN = re.compile(r"^([A-Z0-9]{3}\d{2})-(\d+)$")


def _prefix_from_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", (name or "").upper())
    ascii_only = "".join(ch for ch in normalized if ord(ch) < 128)
    alnum = "".join(ch for ch in ascii_only if ch.isalnum())
    if len(alnum) >= 3:
        return alnum[:3]
    return (alnum + "XXX")[:3]


def _next_numeric_suffix(model, code_field, like_prefix: str, pattern: re.Pattern[str], group_index: int) -> int:
    stmt = select(code_field).where(code_field.like(f"{like_prefix}%"))
    existing_codes = db.session.execute(stmt).scalars().all()
    max_seq = 0
    for code in existing_codes:
        if not code:
            continue
        match = pattern.match(code)
        if not match:
            continue
        try:
            seq = int(match.group(group_index))
            if seq > max_seq:
                max_seq = seq
        except ValueError:
            continue
    return max_seq + 1


def generate_client_code(model, code_field, name: str) -> str:
    prefix = _prefix_from_name(name)
    seq = _next_numeric_suffix(model, code_field, prefix, CLIENT_CODE_PATTERN, 2)
    if seq > 99:
        raise ValueError(f"No hay más correlativos disponibles para clientes con prefijo {prefix}.")
    return f"{prefix}{seq:02d}"


def generate_project_code(model, code_field, client_code: str) -> str:
    base_client_code = (client_code or "").strip().upper()
    if not CLIENT_CODE_PATTERN.match(base_client_code):
        raise ValueError("El código de cliente no cumple el formato esperado (AAA##).")

    like_prefix = f"{base_client_code}-"
    seq = _next_numeric_suffix(model, code_field, like_prefix, PROJECT_CODE_PATTERN, 2)
    if seq > 999:
        raise ValueError(f"No hay más correlativos disponibles para proyectos de {base_client_code}.")
    return f"{base_client_code}-{seq:03d}"
