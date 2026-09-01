class AIServiceError(RuntimeError):
    """Base error for the AI analysis boundary."""


class AIConfigurationError(AIServiceError):
    """Required LLM configuration is missing or invalid."""


class LLMConnectionError(AIServiceError):
    """The LLM endpoint could not be reached within the configured timeout."""


class LLMAuthenticationError(AIServiceError):
    """The LLM endpoint rejected the configured credentials."""


class LLMRateLimitError(AIServiceError):
    """The LLM endpoint rejected the request because of rate limiting."""


class LLMResponseError(AIServiceError):
    """The LLM endpoint returned an unusable response."""


class LLMOutputValidationError(AIServiceError):
    """The LLM output did not match the required structured schema."""
