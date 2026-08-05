import json
from typing import Any, Optional

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator


class NonFiniteJSONValueError(ValueError):
    """Raised when a value cannot be represented as strict, finite-only JSON.

    Covers both directions: serializing a Python value containing NaN/Infinity,
    and deserializing stored text that contains those non-standard constants
    (e.g. from corrupted or manually edited rows).
    """


def _reject_non_finite_constant(constant: str) -> float:
    raise NonFiniteJSONValueError(f"non-finite JSON constant is not allowed: {constant!r}")


class JSONText(TypeDecorator):
    """Stores Python objects as compact, strictly-finite JSON text; returns native objects on read."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Optional[Any], dialect) -> Optional[str]:
        if value is None:
            return None
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        except ValueError as exc:
            raise NonFiniteJSONValueError(
                "JSON value contains a non-finite number (NaN/Infinity) and cannot be stored"
            ) from exc

    def process_result_value(self, value: Optional[str], dialect) -> Optional[Any]:
        if value is None:
            return None
        return json.loads(value, parse_constant=_reject_non_finite_constant)
