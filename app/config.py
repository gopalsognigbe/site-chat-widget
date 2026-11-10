"""Application settings loaded from environment variables and a .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_EMBEDDING_MODELS: dict[str, str] = {
    "local": "sentence-transformers/all-MiniLM-L6-v2",
    "openai": "text-embedding-3-small",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Key for the OpenAI-compatible LLM API: GROQ_API_KEY (Groq) or
    # OPENAI_API_KEY (Groq key, Hugging Face token, or any provider's key).
    openai_api_key: str = Field(validation_alias=AliasChoices("GROQ_API_KEY", "OPENAI_API_KEY"))
    openai_base_url: str = "https://router.huggingface.co/v1"
    llm_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    # Only for reasoning models (e.g. openai/gpt-oss-20b): "low", "medium" or
    # "high". Leave empty for regular models, which reject this parameter.
    llm_reasoning_effort: str | None = None

    embedding_provider: Literal["local", "openai"] = "local"
    embedding_model: str | None = None

    chroma_dir: str = "./data/chroma"
    max_pages: int = 50

    @model_validator(mode="after")
    def _defaults(self) -> "Settings":
        if not self.embedding_model:
            self.embedding_model = DEFAULT_EMBEDDING_MODELS[self.embedding_provider]
        # A Groq key ("gsk_...") with no explicit base URL means Groq.
        if "openai_base_url" not in self.model_fields_set and self.openai_api_key.startswith("gsk_"):
            self.openai_base_url = "https://api.groq.com/openai/v1"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
