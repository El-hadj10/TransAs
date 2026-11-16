"""Parse pasted or CSV delivery lists without UI dependencies."""
from __future__ import annotations

import csv
import io


ADDRESS_HEADERS = {"adresse", "address", "adresse complète", "street"}


def parse_addresses(text: str, *, maximum: int = 500) -> list[str]:
    """Return distinct, non-empty addresses from plain text or a CSV column."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not raw_lines:
        return []
    addresses: list[str]
    if len(raw_lines) > 1 and any(delimiter in raw_lines[0] for delimiter in (",", ";", "\t")):
        dialect = csv.Sniffer().sniff("\n".join(raw_lines[:10]), delimiters=",;\t")
        rows = list(csv.reader(io.StringIO(text), dialect))
        header = [cell.strip().lower() for cell in rows[0]]
        index = next((i for i, cell in enumerate(header) if cell in ADDRESS_HEADERS), None)
        data = rows[1:] if index is not None else rows
        index = 0 if index is None else index
        addresses = [row[index].strip() for row in data if len(row) > index and row[index].strip()]
    else:
        addresses = raw_lines
    unique: list[str] = []
    seen: set[str] = set()
    for address in addresses:
        key = " ".join(address.split()).casefold()
        if key and key not in seen:
            seen.add(key)
            unique.append(" ".join(address.split()))
    if len(unique) > maximum:
        raise ValueError(f"Liste limitée à {maximum} adresses (reçues : {len(unique)})")
    return unique
