import re

from app.llm.prompts import PROMPT_VERSION, REVIEW_SCHEMA_VERSION, SYSTEM_PROMPT

_CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")


def test_prompt_version_literal():
    assert PROMPT_VERSION == "spec-review-prompt-v1"


def test_review_schema_version_literal():
    assert REVIEW_SCHEMA_VERSION == "spec-review-schema-v1"


def test_system_prompt_is_non_empty_text():
    assert isinstance(SYSTEM_PROMPT, str)
    assert SYSTEM_PROMPT.strip() == SYSTEM_PROMPT
    assert len(SYSTEM_PROMPT) > 0


def test_system_prompt_is_written_in_russian():
    # A reasonable fraction of characters must be Cyrillic, not just an
    # incidental word or two, to confirm the prompt body itself is Russian.
    cyrillic_chars = len(_CYRILLIC_RE.findall(SYSTEM_PROMPT))
    assert cyrillic_chars > 200


def test_prompt_requires_treating_document_as_untrusted_data():
    assert "недоверенные данные" in SYSTEM_PROMPT


def test_prompt_requires_ignoring_embedded_instructions():
    assert "игнорируй" in SYSTEM_PROMPT
    assert "роль" in SYSTEM_PROMPT
    assert "prompt" in SYSTEM_PROMPT


def test_prompt_forbids_fabricated_content():
    assert "Не выдумывай" in SYSTEM_PROMPT


def test_prompt_requires_russian_output_language():
    assert "русском языке" in SYSTEM_PROMPT


def test_prompt_forbids_backend_reason_code_fields():
    assert "needs_review" in SYSTEM_PROMPT
    assert "review_reason_codes" in SYSTEM_PROMPT
    assert "backend-коды" in SYSTEM_PROMPT


def test_prompt_requires_empty_arrays_over_invented_items():
    assert "пустой массив" in SYSTEM_PROMPT


def test_prompt_covers_risk_and_contradiction_evidence_rules():
    assert "evidence" in SYSTEM_PROMPT
    assert "null" in SYSTEM_PROMPT


def test_prompt_requires_model_needs_review_flag_semantics():
    assert "model_needs_review=true" in SYSTEM_PROMPT
    assert "model_needs_review=false" in SYSTEM_PROMPT


def test_prompt_does_not_duplicate_json_schema_boilerplate():
    # The prompt must not embed a raw JSON Schema document (Structured
    # Outputs enforces the schema separately via `text_format`).
    assert '"type": "object"' not in SYSTEM_PROMPT
    assert '"properties"' not in SYSTEM_PROMPT
    assert "additionalProperties" not in SYSTEM_PROMPT
