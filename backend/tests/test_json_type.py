import pytest

from app.utils.json_type import JSONText, NonFiniteJSONValueError

json_type = JSONText()


def test_rejects_nan():
    with pytest.raises(NonFiniteJSONValueError):
        json_type.process_bind_param(float("nan"), None)


def test_rejects_positive_infinity():
    with pytest.raises(NonFiniteJSONValueError):
        json_type.process_bind_param(float("inf"), None)


def test_rejects_negative_infinity():
    with pytest.raises(NonFiniteJSONValueError):
        json_type.process_bind_param(float("-inf"), None)


def test_rejects_nested_non_finite_value_in_dict():
    with pytest.raises(NonFiniteJSONValueError):
        json_type.process_bind_param({"a": [1, 2, {"b": float("nan")}]}, None)


def test_rejects_nested_non_finite_value_in_list():
    with pytest.raises(NonFiniteJSONValueError):
        json_type.process_bind_param([1, 2, float("inf")], None)


def test_allows_ordinary_dict_and_list_values():
    value = {"a": 1, "b": [1, 2, 3], "c": 3.14}
    dumped = json_type.process_bind_param(value, None)
    assert isinstance(dumped, str)
    assert json_type.process_result_value(dumped, None) == value


def test_allows_nested_none():
    value = {"summary": "s", "nested": {"note": None, "items": [None, 1, None]}}
    dumped = json_type.process_bind_param(value, None)
    assert json_type.process_result_value(dumped, None) == value


def test_allows_unicode_without_ascii_escaping():
    value = {"summary": "Пример проверки спецификации"}
    dumped = json_type.process_bind_param(value, None)
    assert "Пример проверки спецификации" in dumped
    assert "\\u" not in dumped
    assert json_type.process_result_value(dumped, None) == value


def test_compact_round_trip_serialization():
    value = {"a": 1, "b": [1, 2, 3], "c": {"d": True, "e": None}}
    dumped = json_type.process_bind_param(value, None)
    assert " " not in dumped
    assert json_type.process_result_value(dumped, None) == value


def test_none_round_trips_to_none():
    assert json_type.process_bind_param(None, None) is None
    assert json_type.process_result_value(None, None) is None


def test_process_result_value_rejects_corrupted_nan_constant():
    with pytest.raises(NonFiniteJSONValueError):
        json_type.process_result_value('{"a": NaN}', None)


def test_process_result_value_rejects_corrupted_infinity_constant():
    with pytest.raises(NonFiniteJSONValueError):
        json_type.process_result_value('{"a": Infinity}', None)


def test_process_result_value_rejects_corrupted_negative_infinity_constant():
    with pytest.raises(NonFiniteJSONValueError):
        json_type.process_result_value('{"a": -Infinity}', None)
