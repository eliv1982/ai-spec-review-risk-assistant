"""Typed errors raised by the OpenAI Structured Outputs review client.

Categories are kept programmatically distinguishable (never collapsed into a
single generic exception) so callers can branch on failure type without
parsing message text. Human-readable messages are Russian and never include
API keys, authorization headers, full document text, raw provider response
bodies, or stack traces. Safe attributes (HTTP status code, provider request
id) may be attached where the provider exposes them.
"""

from typing import Optional


class LLMClientError(Exception):
    """Base class for all LLM client failures."""


class LLMConfigurationError(LLMClientError):
    """Required configuration (API key or model name) is missing or blank."""


class LLMProviderError(LLMClientError):
    """Provider/SDK failure that is not a transport or HTTP status error.

    Also covers a refusal, an incomplete response, or a response with no
    parsed structured output.
    """


class LLMAPIError(LLMClientError):
    """The provider responded with an HTTP 4xx/5xx status."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id


class LLMTransportError(LLMClientError):
    """Network-level failure: request timeout or connection error."""


class LLMInvalidJSONError(LLMClientError):
    """The model response text could not be parsed as JSON."""


class LLMSchemaMismatchError(LLMClientError):
    """The parsed JSON does not conform to the ModelReviewDraft schema."""
