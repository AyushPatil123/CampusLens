import logging
import os

from .config import Settings
from .errors import ServiceError
from .providers import GeminiProvider, ModelProvider, OpenAIProvider, ProviderError


logger = logging.getLogger(__name__)


class ModelGateway:
    """Create the selected provider lazily and translate provider failures."""

    def __init__(self, settings: Settings, provider: ModelProvider | None = None):
        self.settings = settings
        self.provider = provider

    def get_provider(self) -> ModelProvider:
        if self.provider is None:
            if self.settings.model_provider == "openai":
                if not os.getenv("OPENAI_API_KEY"):
                    raise ServiceError(503, "Set OPENAI_API_KEY for the selected model provider")
                self.provider = OpenAIProvider(self.settings.embedding_model, self.settings.answer_model)
            elif self.settings.model_provider == "gemini":
                api_key = os.getenv("GEMINI_API_KEY")
                if not api_key:
                    raise ServiceError(503, "Set GEMINI_API_KEY for the selected model provider")
                self.provider = GeminiProvider(
                    api_key, self.settings.gemini_embedding_model,
                    self.settings.gemini_answer_model, self.settings.gemini_embedding_dimensions,
                )
            else:
                raise ServiceError(503, "CAMPUSLENS_PROVIDER must be 'gemini' or 'openai'")
        return self.provider

    def call(self, method: str, *args):
        try:
            return getattr(self.get_provider(), method)(*args)
        except ServiceError:
            raise
        except ProviderError as exc:
            messages = {
                "authentication": (503, "Model service authentication failed; check the selected API key"),
                "rate_limit": (429, "Model service rate limit reached; try again later"),
                "configuration": (503, "Model service rejected its configuration; check model names"),
            }
            status, detail = messages.get(exc.kind, (502, "Model service request failed"))
            raise ServiceError(status, detail) from exc
        except Exception as exc:
            logger.exception("Unexpected model provider failure during %s", method)
            raise ServiceError(502, "Model service request failed") from exc
