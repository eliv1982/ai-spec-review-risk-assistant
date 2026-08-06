"""Compact, dependency-free CSV export helpers shared by every `/export` route.

Stdlib only (`csv` + `io` + `json`) — no pandas, no export framework, no class
hierarchy. Every string cell that reaches a spreadsheet is sanitized against
CSV/spreadsheet formula injection (CWE-1236): a cell whose first significant
character (after any leading ASCII spaces) is `= + - @ <TAB> <CR> <LF>` is
treated as a formula by Excel/LibreOffice/Sheets unless neutralized.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Sequence

from fastapi import Response

_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r", "\n")


def sanitize_csv_cell(value: str) -> str:
    """Escapes a string cell against spreadsheet formula injection.

    A leading apostrophe forces every major spreadsheet application to read
    the cell back as literal text. Only ordinary ASCII spaces (`" "`) are
    skipped when looking for the first significant character — other
    whitespace (tab, CR, LF) is itself a trigger character, matching how
    spreadsheet applications sniff formulas. The apostrophe is prepended to
    the original value unchanged (leading spaces and control characters are
    never stripped). A value that already starts with `'` is assumed to be
    already sanitized and is returned unchanged, keeping the function
    idempotent.
    """
    if value.startswith("'"):
        return value
    stripped = value.lstrip(" ")
    if stripped and stripped[0] in _FORMULA_TRIGGER_CHARS:
        return "'" + value
    return value


def serialize_json_cell(value: Any) -> str:
    """Deterministic single-cell JSON: `ensure_ascii=False`, `sort_keys=True`.

    Also passed through `sanitize_csv_cell` for defense in depth — a JSON
    document always starts with `{`, `[`, a quote, or a literal, none of
    which trigger the formula check, but this keeps the safety guarantee
    independent of `json.dumps`'s exact output shape.
    """
    return sanitize_csv_cell(json.dumps(value, ensure_ascii=False, sort_keys=True))


def build_csv_bytes(rows: Sequence[Sequence[str]]) -> bytes:
    """Builds a complete CSV document (header row included) as UTF-8-SIG bytes.

    Semicolon delimiter and CRLF line endings so the file opens correctly in
    Excel under a Russian locale. Every cell — header included — is passed
    through `sanitize_csv_cell`: a no-op for this module's static Russian
    header labels, but it keeps a single code path instead of a header/data
    special case.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    for row in rows:
        writer.writerow([sanitize_csv_cell(cell) for cell in row])
    return buffer.getvalue().encode("utf-8-sig")


def build_csv_response(filename: str, rows: Sequence[Sequence[str]]) -> Response:
    """Wraps `build_csv_bytes` in a `text/csv` FastAPI `Response` with a safe,
    ASCII, attachment `Content-Disposition` (`filename` is always one of this
    app's own static literals — never document title or other user text).
    """
    body = build_csv_bytes(rows)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
