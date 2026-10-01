"""The LLM provider keys, declared once and shared.

The router is not a tool, so it cannot declare ``config_fields`` itself. The
tools that go through the router (``llm_call``, ``llm_route``, ``agent_step``)
declare these on its behalf, which puts the provider keys on the same admin
screen as every other credential. The router reads them through the resolver
and rebuilds a provider's client when its key changes, so a key saved under
Admin -> Tool Configuration is live within the resolver's TTL.
"""

from __future__ import annotations

from engine.tools.base import ConfigField

PROVIDER_CONFIG_FIELDS: tuple[ConfigField, ...] = (
    ConfigField(
        "ANTHROPIC_API_KEY",
        label="API key",
        kind="secret",
        group="Anthropic",
        description="Claude models for every agent run and llm_call node. Also used by the vision and document tools. A Claude subscription token under Model Selection takes precedence.",
        signup_url="https://console.anthropic.com/settings/keys",
        dynamic=True,
    ),
    ConfigField(
        "OPENAI_API_KEY",
        label="API key",
        kind="secret",
        group="OpenAI",
        description="GPT models in the agent picker, text embeddings for knowledge bases, Whisper and TTS for meetings, and the moderation gate.",
        signup_url="https://platform.openai.com/api-keys",
        dynamic=True,
    ),
    ConfigField(
        "GOOGLE_API_KEY",
        label="API key",
        kind="secret",
        group="Google AI",
        description="Gemini models in the agent picker and the Gemini document path.",
        signup_url="https://aistudio.google.com/app/apikey",
        dynamic=True,
    ),
    ConfigField(
        "GEMINI_API_KEY",
        label="API key (alias)",
        kind="secret",
        group="Google AI",
        description="Alternative name for GOOGLE_API_KEY, read when that one is empty.",
        signup_url="https://aistudio.google.com/app/apikey",
        dynamic=True,
    ),
    ConfigField(
        "AZURE_OPENAI_API_KEY",
        label="API key",
        kind="secret",
        group="Azure OpenAI",
        description="Azure-hosted GPT deployments, the azure-* models in the picker.",
        signup_url="https://portal.azure.com/",
        dynamic=True,
    ),
    ConfigField(
        "AZURE_OPENAI_API_BASE",
        label="Endpoint",
        kind="url",
        group="Azure OpenAI",
        description="The resource endpoint, https://<resource>.openai.azure.com",
        dynamic=True,
    ),
    ConfigField(
        "AZURE_OPENAI_API_VERSION",
        label="API version",
        kind="string",
        group="Azure OpenAI",
        default="2024-10-01-preview",
        dynamic=True,
    ),
)

# provider name -> the keys that make it usable, in the order they are tried
PROVIDER_KEYS: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "azure": (
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_BASE",
        "AZURE_OPENAI_API_VERSION",
    ),
}
