from app.services.display_labels import (
    format_datetime_ru,
    format_duration_ru,
    label_audit_action,
    label_audit_entity_type,
    label_audit_status,
    label_bool_yes_no,
    label_confidence,
    label_readiness,
    label_reason_code,
    label_reason_codes,
)


def test_label_bool_yes_no():
    assert label_bool_yes_no(True) == "Да"
    assert label_bool_yes_no(False) == "Нет"


def test_label_confidence_known_values():
    assert label_confidence("high") == "Высокая"
    assert label_confidence("medium") == "Средняя"
    assert label_confidence("low") == "Низкая"


def test_label_confidence_unknown_value_falls_back_to_raw():
    assert label_confidence("future-value") == "future-value"


def test_label_readiness_known_values():
    assert label_readiness("ready") == "Готов"
    assert label_readiness("needs_clarification") == "Требует уточнений"
    assert label_readiness("not_ready") == "Не готов"


def test_label_reason_code_known_values():
    assert label_reason_code("LOW_CONFIDENCE") == "Низкая уверенность анализа"
    assert label_reason_code("TOO_VAGUE_INPUT") == "Недостаточно конкретный документ"
    assert label_reason_code("CONTRADICTORY_INPUT") == "Обнаружены противоречия"
    assert label_reason_code("MISSING_ACCEPTANCE_CRITERIA") == "Не хватает критериев приёмки"
    assert label_reason_code("INSUFFICIENT_QUESTIONS") == "Недостаточно уточняющих вопросов"
    assert label_reason_code("MODEL_ERROR") == "Ошибка ИИ-модели"


def test_label_reason_code_unknown_value_falls_back_to_raw():
    assert label_reason_code("FUTURE_UNKNOWN_CODE") == "FUTURE_UNKNOWN_CODE"


def test_label_reason_codes_joins_with_pipe_delimiter():
    result = label_reason_codes(["LOW_CONFIDENCE", "MISSING_ACCEPTANCE_CRITERIA"])
    assert result == "Низкая уверенность анализа|Не хватает критериев приёмки"


def test_label_reason_codes_empty_list():
    assert label_reason_codes([]) == ""


def test_label_audit_action_known_values():
    assert label_audit_action("document.create") == "Создание документа"
    assert label_audit_action("document.review") == "Проверка документа"
    assert label_audit_action("ai.review") == "Проверка текста без сохранения"


def test_label_audit_action_unknown_value_falls_back_to_raw():
    assert label_audit_action("future.action") == "future.action"


def test_label_audit_entity_type_known_values():
    assert label_audit_entity_type("document") == "Документ"
    assert label_audit_entity_type("review") == "Проверка"


def test_label_audit_entity_type_none_becomes_empty_string():
    assert label_audit_entity_type(None) == ""


def test_label_audit_status_known_values():
    assert label_audit_status("success") == "Успешно"
    assert label_audit_status("needs_review") == "Нужна экспертная проверка"
    assert label_audit_status("error") == "Техническая ошибка"


def test_format_datetime_ru_converts_utc_to_moscow_time():
    # UTC 06:32:07 -> MSK (UTC+3) 09:32, DD.MM.YYYY, HH:MM.
    assert format_datetime_ru("2026-08-07T06:32:07Z") == "07.08.2026, 09:32"


def test_format_datetime_ru_crosses_a_day_boundary():
    # UTC 22:15:00 -> MSK 01:15 the next day.
    assert format_datetime_ru("2026-08-07T22:15:00Z") == "08.08.2026, 01:15"


def test_format_datetime_ru_unparseable_value_falls_back_to_raw():
    assert format_datetime_ru("not-a-real-timestamp") == "not-a-real-timestamp"


def test_format_duration_ru_milliseconds_stay_milliseconds_under_one_second():
    assert format_duration_ru(5) == "5 мс"
    assert format_duration_ru(14) == "14 мс"
    assert format_duration_ru(999) == "999 мс"
    assert format_duration_ru(0) == "0 мс"


def test_format_duration_ru_switches_to_seconds_at_one_second():
    assert format_duration_ru(1000) == "1,0 с"


def test_format_duration_ru_rounds_to_one_decimal_with_comma_separator():
    assert format_duration_ru(36950) == "37,0 с"


def test_format_duration_ru_rounds_half_up():
    # 1250 ms -> 12.5 tenths of a second -> rounds up to 13 (1.3s), matching
    # the frontend's Math.round (round-half-away-from-zero) rather than
    # Python's `round()` banker's rounding (round-half-to-even), which would
    # give 1.2s (round 12.5 down to the even 12).
    assert format_duration_ru(1250) == "1,3 с"
