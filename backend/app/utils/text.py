def normalize_text(text: str) -> str:
    """Collapse whitespace runs to single spaces and trim ends (REVIEW_SCHEMA.md,
    "Exact vagueness definition"): normalized_text = " ".join(text.split())."""
    return " ".join(text.split())


def is_too_vague(text: str) -> bool:
    """Exact deterministic vagueness rule (REVIEW_SCHEMA.md, "Exact vagueness definition").

    too_vague = len(normalized_text) < 200 OR len(normalized_text.split(" ")) < 30

    An empty normalized string is always too_vague via the length branch, so the
    token-count branch is skipped for it: "".split(" ") returns [""] (length 1),
    which would misreport one token where there are actually zero.
    """
    normalized = normalize_text(text)
    if not normalized:
        return True
    return len(normalized) < 200 or len(normalized.split(" ")) < 30
