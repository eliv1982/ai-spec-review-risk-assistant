"""Russian display labels and formatting helpers for user-facing CSV cells.

Mirrors `frontend/src/utils/labels.ts`, `frontend/src/utils/reasonCodes.ts`
and `frontend/src/utils/formatting.ts` — the frontend and CSV export are two
independent renderers of the same closed backend enums (`app/enums.py`), so
both keep their own copy of this mapping rather than sharing code across the
Python/TypeScript boundary. Backend enum values themselves are never changed
here; this module only chooses the Russian text a human-facing CSV cell
should show for a given closed value, with an unrecognized value always
falling back to itself instead of raising.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

# Russia abolished daylight saving time in 2014; Moscow Standard Time (MSK)
# has been a fixed UTC+3 ever since. A fixed offset is used instead of
# `zoneinfo.ZoneInfo("Europe/Moscow")` because `zoneinfo` depends on the
# host's IANA time zone database, which Windows does not ship — using it
# here would require adding the `tzdata` package as a new dependency just
# for a timezone that never actually changes.
_MOSCOW_OFFSET = timedelta(hours=3)

_CONFIDENCE_LABELS = {"high": "Высокая", "medium": "Средняя", "low": "Низкая"}

_READINESS_LABELS = {
    "ready": "Готов",
    "needs_clarification": "Требует уточнений",
    "not_ready": "Не готов",
}

_REASON_CODE_LABELS = {
    "LOW_CONFIDENCE": "Низкая уверенность анализа",
    "TOO_VAGUE_INPUT": "Недостаточно конкретный документ",
    "CONTRADICTORY_INPUT": "Обнаружены противоречия",
    "MISSING_ACCEPTANCE_CRITERIA": "Не хватает критериев приёмки",
    "INSUFFICIENT_QUESTIONS": "Недостаточно уточняющих вопросов",
    "MODEL_ERROR": "Ошибка ИИ-модели",
    "INVALID_JSON": "Ответ модели не в формате JSON",
    "SCHEMA_MISMATCH": "Ответ модели не соответствует схеме",
}

_AUDIT_ACTION_LABELS = {
    "document.create": "Создание документа",
    "document.review": "Проверка документа",
    "ai.review": "Проверка текста без сохранения",
}

_AUDIT_ENTITY_TYPE_LABELS = {"document": "Документ", "review": "Проверка"}

_AUDIT_STATUS_LABELS = {
    "success": "Успешно",
    "needs_review": "Нужна экспертная проверка",
    "error": "Техническая ошибка",
}


def label_bool_yes_no(value: bool) -> str:
    return "Да" if value else "Нет"


def label_confidence(value: str) -> str:
    return _CONFIDENCE_LABELS.get(value, value)


def label_readiness(value: str) -> str:
    return _READINESS_LABELS.get(value, value)


def label_reason_code(code: str) -> str:
    return _REASON_CODE_LABELS.get(code, code)


def label_reason_codes(codes: list[str], delimiter: str = "|") -> str:
    return delimiter.join(label_reason_code(code) for code in codes)


def label_audit_action(action: str) -> str:
    return _AUDIT_ACTION_LABELS.get(action, action)


def label_audit_entity_type(value: Optional[str]) -> str:
    if value is None:
        return ""
    return _AUDIT_ENTITY_TYPE_LABELS.get(value, value)


def label_audit_status(value: str) -> str:
    return _AUDIT_STATUS_LABELS.get(value, value)


def format_datetime_ru(value: str) -> str:
    """Formats a canonical UTC ISO 8601 string (`utils.time.utc_now_iso`,
    e.g. `"2026-08-07T06:32:07Z"`) as `"07.08.2026, 09:32"` — DD.MM.YYYY,
    HH:MM in Moscow local time. Falls back to the raw value unchanged if it
    cannot be parsed, so a malformed historical value never breaks CSV export.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    utc_naive = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    moscow = utc_naive + _MOSCOW_OFFSET
    return moscow.strftime("%d.%m.%Y, %H:%M")


def format_duration_ru(duration_ms: int) -> str:
    """Formats a millisecond duration for display: durations under one
    second stay in milliseconds (`"14 мс"`); one second and above switch to
    a one-decimal seconds value with a Russian comma separator (`"37,0 с"`).
    Rounds half up (via `floor(x + 0.5)`), matching the equivalent frontend
    helper (`formatDuration`) instead of Python's banker's-rounding `round()`.
    """
    if duration_ms < 1000:
        return f"{duration_ms} мс"
    tenths = math.floor(duration_ms / 100 + 0.5)
    seconds = tenths / 10
    formatted = f"{seconds:.1f}".replace(".", ",")
    return f"{formatted} с"
