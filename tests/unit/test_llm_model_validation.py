"""An unrecognised model id must be reported, not quietly swapped.

The router degrades onto whatever provider has a credential, which is what lets
a single-provider install run every seeded agent. The bug was that an id nobody
recognised took the same path: `_native_provider_name` ends with a bare
`return "anthropic"`, so a typo'd model was treated as an Anthropic request,
the subscription remapped it to its default, and a real model answered.

Observed before the fix — an agent configured with
`totally-not-a-real-model-xyz` returned "Hello! How can I help you today?" with
status=completed and failure_code=None. Nothing anywhere recorded that the
configured model had not been used, which quietly breaks cost attribution and
any assumption about which model produced an output.

Degradation for a known model is deliberate and stays. Only the unknown id
raises.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "apps" / "agent-runtime", ROOT / "apps" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from engine.llm_router import LLMRouter  # noqa: E402
from app.core.failure_codes import classify_exception  # noqa: E402


@pytest.fixture()
def router() -> LLMRouter:
    return LLMRouter()


KNOWN = [
    "claude-sonnet-4-5-20250929",
    "claude-haiku-3-5-20241022",
    "gpt-4o",
    "gpt-4o-mini",
    "gemini-2.0-flash",
    "gemini-2.5-pro",
    "azure-gpt-4o",
    # Prefix match, so a newer id the pricing table has not caught up with
    # still routes rather than failing a deploy.
    "claude-opus-5",
    "gpt-5-turbo",
]

UNKNOWN = [
    "totally-not-a-real-model-xyz",
    "model-that-does-not-exist",
    "sonnet",              # a plausible abbreviation, still not an id
    "claud-sonnet-4-5",    # one character off
    "",
    "   ",
]


@pytest.mark.parametrize("model", KNOWN)
def test_known_models_are_recognised(router: LLMRouter, model: str) -> None:
    assert router.is_known_model(model), f"{model} should be recognised"


@pytest.mark.parametrize("model", UNKNOWN)
def test_unknown_models_are_rejected(router: LLMRouter, model: str) -> None:
    assert not router.is_known_model(model), f"{model} should not be recognised"


@pytest.mark.parametrize("model", UNKNOWN)
def test_candidate_chain_raises_on_unknown(router: LLMRouter, model: str) -> None:
    with pytest.raises(ValueError, match="[Uu]nknown model"):
        router.candidate_chain(model)


def test_the_error_names_the_offending_model(router: LLMRouter) -> None:
    # Whoever reads the execution has to be able to tell which id was wrong.
    with pytest.raises(ValueError) as exc:
        router.candidate_chain("totally-not-a-real-model-xyz")
    assert "totally-not-a-real-model-xyz" in str(exc.value)


def test_the_error_classifies_as_a_config_problem() -> None:
    # A silent swap is the failure this guards, so the code has to say config
    # rather than land in UNKNOWN_ERROR with everything else.
    assert classify_exception(ValueError("Unknown model 'nope'.")) == "CONFIG_UNKNOWN_MODEL"


def test_a_known_model_still_builds_a_chain(router: LLMRouter) -> None:
    # The degradation behaviour is the point of the chain and must survive.
    chain = router.candidate_chain("claude-sonnet-4-5-20250929")
    assert chain, "a known model produced no candidates"
    assert all(len(entry) == 2 for entry in chain)
