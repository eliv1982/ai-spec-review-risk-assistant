from app.utils.text import is_too_vague, normalize_text


def _build_text(token_count: int, total_length: int) -> str:
    """Build a string of exactly `token_count` single-space-separated tokens whose
    total length is exactly `total_length`. Self-verifying: asserts both the
    resulting length and token count before returning, so callers never rely on
    an unverified manual character/token count.
    """
    num_spaces = token_count - 1
    total_letters = total_length - num_spaces
    assert total_letters >= token_count, "total_length too small for token_count"
    base_len, remainder = divmod(total_letters, token_count)
    lengths = [base_len + 1 if i < remainder else base_len for i in range(token_count)]
    text = " ".join("a" * length for length in lengths)
    assert len(text) == total_length
    assert len(text.split(" ")) == token_count
    return text


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------


def test_normalize_text_empty_string():
    assert normalize_text("") == ""


def test_normalize_text_collapses_repeated_spaces():
    assert normalize_text("a    b") == "a b"


def test_normalize_text_collapses_tabs():
    assert normalize_text("a\t\tb") == "a b"


def test_normalize_text_collapses_newlines():
    assert normalize_text("a\n\nb") == "a b"


def test_normalize_text_collapses_mixed_whitespace_and_trims_ends():
    raw = "  Hello\t\tworld\n\nfoo   bar  "
    normalized = normalize_text(raw)
    assert normalized == "Hello world foo bar"
    assert len(normalized) == 19
    assert len(normalized.split(" ")) == 4


def test_normalize_text_already_normalized_is_unchanged():
    text = "already normalized text"
    assert normalize_text(text) == text


# ---------------------------------------------------------------------------
# is_too_vague — empty input
# ---------------------------------------------------------------------------


def test_empty_input_is_too_vague():
    assert is_too_vague("") == True  # noqa: E712 (explicit boolean intent)


def test_whitespace_only_input_normalizes_to_empty_and_is_too_vague():
    assert normalize_text("   \t\n  ") == ""
    assert is_too_vague("   \t\n  ") is True


# ---------------------------------------------------------------------------
# is_too_vague — exact length boundary (199 vs 200), token count fixed >= 30
# so only the length condition determines the outcome.
# ---------------------------------------------------------------------------


def test_length_199_with_sufficient_tokens_is_too_vague():
    text = _build_text(token_count=40, total_length=199)
    assert len(normalize_text(text)) == 199
    assert len(normalize_text(text).split(" ")) == 40  # token condition alone would pass
    assert is_too_vague(text) is True


def test_length_200_with_sufficient_tokens_is_not_too_vague():
    text = _build_text(token_count=40, total_length=200)
    assert len(normalize_text(text)) == 200
    assert len(normalize_text(text).split(" ")) == 40
    assert is_too_vague(text) is False


# ---------------------------------------------------------------------------
# is_too_vague — exact token-count boundary (29 vs 30), length fixed >= 200
# so only the token condition determines the outcome.
# ---------------------------------------------------------------------------


def test_29_tokens_with_sufficient_length_is_too_vague():
    text = _build_text(token_count=29, total_length=210)
    assert len(normalize_text(text)) == 210  # length condition alone would pass
    assert len(normalize_text(text).split(" ")) == 29
    assert is_too_vague(text) is True


def test_30_tokens_with_sufficient_length_is_not_too_vague():
    text = _build_text(token_count=30, total_length=210)
    assert len(normalize_text(text)) == 210
    assert len(normalize_text(text).split(" ")) == 30
    assert is_too_vague(text) is False


# ---------------------------------------------------------------------------
# One threshold passing while the other fails (both directions)
# ---------------------------------------------------------------------------


def test_length_fails_token_count_passes_is_too_vague():
    # 40 tokens (passes token threshold) but only 199 chars (fails length threshold)
    text = _build_text(token_count=40, total_length=199)
    assert is_too_vague(text) is True


def test_token_count_fails_length_passes_is_too_vague():
    # 210 chars (passes length threshold) but only 29 tokens (fails token threshold)
    text = _build_text(token_count=29, total_length=210)
    assert is_too_vague(text) is True


# ---------------------------------------------------------------------------
# Both thresholds failing / both passing
# ---------------------------------------------------------------------------


def test_both_thresholds_failing_is_too_vague():
    text = "Too short."
    normalized = normalize_text(text)
    assert len(normalized) < 200
    assert len(normalized.split(" ")) < 30
    assert is_too_vague(text) is True


def test_both_thresholds_passing_is_not_too_vague():
    text = _build_text(token_count=35, total_length=205)
    normalized = normalize_text(text)
    assert len(normalized) >= 200
    assert len(normalized.split(" ")) >= 30
    assert is_too_vague(text) is False


def test_both_thresholds_passing_with_realistic_sentence_is_not_too_vague():
    text = (
        "The system shall allow an authenticated administrator to configure "
        "notification delivery preferences, including channel selection, retry "
        "policy, and retention period, and every configuration change must be "
        "recorded in an audit log entry that is visible to operators within the "
        "administration panel for later review and compliance reporting purposes."
    )
    normalized = normalize_text(text)
    assert len(normalized) >= 200
    assert len(normalized.split(" ")) >= 30
    assert is_too_vague(text) is False
