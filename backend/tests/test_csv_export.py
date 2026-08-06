from app.services.csv_export import build_csv_bytes, sanitize_csv_cell, serialize_json_cell


def test_sanitize_csv_cell_escapes_equals_formula():
    assert sanitize_csv_cell("=SUM(1,1)") == "'=SUM(1,1)"


def test_sanitize_csv_cell_escapes_plus_formula():
    assert sanitize_csv_cell("+cmd") == "'+cmd"


def test_sanitize_csv_cell_escapes_minus_formula():
    assert sanitize_csv_cell("-10+20") == "'-10+20"


def test_sanitize_csv_cell_escapes_at_formula():
    assert sanitize_csv_cell("@formula") == "'@formula"


def test_sanitize_csv_cell_escapes_leading_whitespace_then_formula_marker():
    assert sanitize_csv_cell("   =SUM(1,1)") == "'   =SUM(1,1)"


def test_sanitize_csv_cell_escapes_tab_prefixed_value():
    assert sanitize_csv_cell("\t=cmd") == "'\t=cmd"


def test_sanitize_csv_cell_escapes_carriage_return_prefixed_value():
    assert sanitize_csv_cell("\r=cmd") == "'\r=cmd"


def test_sanitize_csv_cell_leaves_normal_text_untouched():
    assert sanitize_csv_cell("Обычный текст без формул") == "Обычный текст без формул"


def test_sanitize_csv_cell_leaves_russian_unicode_untouched():
    value = "Отчёт по проверке №42 — риски и требования"
    assert sanitize_csv_cell(value) == value


def test_sanitize_csv_cell_does_not_escape_internal_special_chars():
    # Only the first non-whitespace character matters — a value that merely
    # *contains* one of the trigger characters mid-string is not a formula.
    value = "Стоимость: 10-20 у.е. (email@example.com)"
    assert sanitize_csv_cell(value) == value


def test_serialize_json_cell_is_deterministic_ascii_false_sorted_keys():
    payload = {"b": 1, "a": "текст", "c": [3, 2, 1]}
    result = serialize_json_cell(payload)
    assert result == '{"a": "текст", "b": 1, "c": [3, 2, 1]}'


def test_serialize_json_cell_applies_formula_injection_protection():
    # Defense in depth: a bare negative-number JSON payload serializes to a
    # string starting with `-` (e.g. `-5`), which must still be escaped even
    # though this shape never occurs for the object/array payloads this
    # module actually calls serialize_json_cell with.
    result = serialize_json_cell(-5)
    assert result == "'-5"


def test_build_csv_bytes_has_utf8_bom():
    body = build_csv_bytes([["A", "B"], ["1", "2"]])
    assert body.startswith(b"\xef\xbb\xbf")


def test_build_csv_bytes_uses_semicolon_delimiter():
    body = build_csv_bytes([["A", "B"], ["1", "2"]])
    text = body.decode("utf-8-sig")
    assert "A;B" in text
    assert "1;2" in text


def test_build_csv_bytes_uses_crlf_line_endings():
    body = build_csv_bytes([["A", "B"], ["1", "2"]])
    text = body.decode("utf-8-sig")
    assert "A;B\r\n1;2\r\n" == text


def test_build_csv_bytes_quotes_value_containing_delimiter():
    body = build_csv_bytes([["A"], ["value;with;semicolons"]])
    text = body.decode("utf-8-sig")
    assert '"value;with;semicolons"' in text


def test_build_csv_bytes_quotes_value_containing_newline():
    body = build_csv_bytes([["A"], ["line1\nline2"]])
    text = body.decode("utf-8-sig")
    assert '"line1\nline2"' in text


def test_build_csv_bytes_quotes_value_containing_double_quote():
    body = build_csv_bytes([["A"], ['say "hi"']])
    text = body.decode("utf-8-sig")
    assert '"say ""hi"""' in text


def test_build_csv_bytes_empty_data_rows_still_has_header_and_bom():
    body = build_csv_bytes([["A", "B"]])
    assert body.startswith(b"\xef\xbb\xbf")
    text = body.decode("utf-8-sig")
    assert text == "A;B\r\n"


def test_build_csv_bytes_sanitizes_formula_injection_in_data_cells():
    body = build_csv_bytes([["A"], ["=SUM(1,1)"], ["+cmd"], ["-10+20"], ["@formula"]])
    text = body.decode("utf-8-sig")
    lines = text.strip("\r\n").split("\r\n")
    assert lines == ["A", "'=SUM(1,1)", "'+cmd", "'-10+20", "'@formula"]


def test_build_csv_bytes_bom_appears_exactly_once():
    body = build_csv_bytes([["A", "B"], ["1", "2"], ["3", "4"]])
    bom = b"\xef\xbb\xbf"
    assert body.startswith(bom)
    assert body.count(bom) == 1


# --- Direct control-character regression (values that were previously left
# unescaped because `lstrip()` strips ALL whitespace, including tab/CR/LF,
# before the trigger-character check ran) ---------------------------------


def test_sanitize_csv_cell_escapes_bare_tab_prefixed_value():
    assert sanitize_csv_cell("\tSAFE") == "'\tSAFE"


def test_sanitize_csv_cell_escapes_bare_carriage_return_prefixed_value():
    assert sanitize_csv_cell("\rSAFE") == "'\rSAFE"


def test_sanitize_csv_cell_escapes_bare_newline_prefixed_value():
    assert sanitize_csv_cell("\nSAFE") == "'\nSAFE"


def test_sanitize_csv_cell_escapes_spaces_then_tab_prefixed_value():
    assert sanitize_csv_cell("   \tSAFE") == "'   \tSAFE"


def test_sanitize_csv_cell_escapes_spaces_then_carriage_return_prefixed_value():
    assert sanitize_csv_cell("   \rSAFE") == "'   \rSAFE"


def test_sanitize_csv_cell_escapes_spaces_then_newline_prefixed_value():
    assert sanitize_csv_cell("   \nSAFE") == "'   \nSAFE"


def test_sanitize_csv_cell_escapes_plus_after_leading_spaces():
    assert sanitize_csv_cell("   +cmd") == "'   +cmd"


def test_sanitize_csv_cell_escapes_minus_after_leading_spaces():
    assert sanitize_csv_cell("   -10+20") == "'   -10+20"


def test_sanitize_csv_cell_escapes_at_after_leading_spaces():
    assert sanitize_csv_cell("   @formula") == "'   @formula"


def test_sanitize_csv_cell_is_idempotent_on_already_escaped_equals():
    once = sanitize_csv_cell("=SUM(A1:A2)")
    assert once == "'=SUM(A1:A2)"
    assert sanitize_csv_cell(once) == "'=SUM(A1:A2)"


def test_sanitize_csv_cell_is_idempotent_on_already_escaped_tab():
    once = sanitize_csv_cell("\tSAFE")
    assert once == "'\tSAFE"
    assert sanitize_csv_cell(once) == "'\tSAFE"


def test_sanitize_csv_cell_leaves_safe_relative_path_untouched():
    assert sanitize_csv_cell("/api/reviews") == "/api/reviews"


def test_sanitize_csv_cell_leaves_safe_absolute_path_untouched():
    assert sanitize_csv_cell("/path/to/file") == "/path/to/file"


def test_sanitize_csv_cell_leaves_safe_url_untouched():
    assert sanitize_csv_cell("https://example.com") == "https://example.com"


def test_sanitize_csv_cell_leaves_plain_text_untouched():
    assert sanitize_csv_cell("обычный текст") == "обычный текст"


def test_sanitize_csv_cell_preserves_leading_spaces_when_not_escaped():
    assert sanitize_csv_cell("   безопасный текст") == "   безопасный текст"
