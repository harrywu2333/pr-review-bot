"""PR Review Bot — LLM provider registry and OpenAI-compatible client helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterator

import openai

# ---------------------------------------------------------------------------
# Provider dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Provider:
    key: str
    display_name: str
    env_var: str
    base_url: str
    default_model: str | None  # None = user must supply --model
    model_examples: tuple[str, ...]

    @property
    def api_key(self) -> str | None:
        """Return the API key from the environment, or None if unset/blank."""
        val = os.environ.get(self.env_var)
        if not val or not val.strip():
            return None
        return val


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, Provider] = {
    "gemini": Provider(
        key="gemini",
        display_name="Gemini",
        env_var="GEMINI_API_KEY",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-2.0-flash",
        model_examples=(
            "gemini-2.0-flash",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
        ),
    ),
    "groq": Provider(
        key="groq",
        display_name="Groq",
        env_var="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        model_examples=(
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
        ),
    ),
    "openrouter": Provider(
        key="openrouter",
        display_name="OpenRouter",
        env_var="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
        default_model=None,  # OpenRouter routes to many models — user must choose
        model_examples=(
            "google/gemini-2.0-flash-001",
            "google/gemini-2.5-pro-preview",
            "anthropic/claude-sonnet-4-5",
            "anthropic/claude-3-5-haiku",
            "meta-llama/llama-3.3-70b-instruct",
            "mistralai/mistral-small-3.2-24b-instruct:free",
        ),
    ),
}

PROVIDER_NAMES: list[str] = ["gemini", "groq", "openrouter"]


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------


def detect_provider() -> tuple[Provider | None, list[str]]:
    """Scan all providers for a non-None api_key.

    Returns ``(provider, found_env_vars)`` where:
    - *provider* is non-None **only** when exactly one key is found.
    - *found_env_vars* lists every env-var name whose value was present,
      regardless of how many were found.
    """
    found_providers: list[Provider] = []
    found_env_vars: list[str] = []

    for name in PROVIDER_NAMES:
        provider = PROVIDERS[name]
        if provider.api_key is not None:
            found_providers.append(provider)
            found_env_vars.append(provider.env_var)

    if len(found_providers) == 1:
        return found_providers[0], found_env_vars

    return None, found_env_vars


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def make_client(provider: Provider) -> openai.OpenAI:
    """Create an OpenAI-compatible client configured for *provider*."""
    kwargs: dict[str, Any] = {
        "api_key": provider.api_key,
        "base_url": provider.base_url,
    }
    if provider.key == "openrouter":
        kwargs["default_headers"] = {
            "HTTP-Referer": "https://github.com/pr-review-bot",
            "X-Title": "PR Review Bot",
        }
    return openai.OpenAI(**kwargs)


# ---------------------------------------------------------------------------
# Completion helpers
# ---------------------------------------------------------------------------


def stream_completion(
    client: openai.OpenAI,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
) -> Iterator[str]:
    """Stream a chat completion, yielding each non-empty content chunk."""
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        stream=True,
    )
    for chunk in response:
        content = chunk.choices[0].delta.content
        if content:
            yield content


def create_completion(
    client: openai.OpenAI,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
) -> str:
    """Non-streaming chat completion; returns the full response text."""
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        stream=False,
    )
    return response.choices[0].message.content or ""
