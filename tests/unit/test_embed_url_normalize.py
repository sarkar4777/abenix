"""Defensive-strip helper for Azure OpenAI endpoint URLs.

Twin copies live in apps/worker/worker/tasks/document_processor.py and
apps/agent-runtime/engine/knowledge/hybrid_search.py (cross-process
robustness — neither imports the other). Both must behave identically;
this suite locks the contract in one place.
"""

from __future__ import annotations

import pytest

from worker.tasks.document_processor import (
    _normalize_azure_endpoint as worker_normalize,
)
from engine.knowledge.hybrid_search import (
    _normalize_azure_endpoint as runtime_normalize,
)


@pytest.fixture(params=[worker_normalize, runtime_normalize], ids=["worker", "runtime"])
def normalize(request):
    return request.param


def test_bare_url_unchanged(normalize):
    assert normalize("https://my-aoai.openai.azure.com") == (
        "https://my-aoai.openai.azure.com"
    )


def test_strips_openai_deployments_suffix(normalize):
    assert (
        normalize("https://my-aoai.openai.azure.com/openai/deployments")
        == "https://my-aoai.openai.azure.com"
    )


def test_strips_openai_suffix(normalize):
    # APIM rewrites sometimes drop the /deployments segment and leave /openai.
    assert (
        normalize("https://my-apim.azure-api.net/openai")
        == "https://my-apim.azure-api.net"
    )


def test_strips_trailing_slash(normalize):
    assert (
        normalize("https://my-aoai.openai.azure.com/")
        == "https://my-aoai.openai.azure.com"
    )


def test_strips_openai_deployments_with_trailing_slash(normalize):
    assert (
        normalize("https://my-aoai.openai.azure.com/openai/deployments/")
        == "https://my-aoai.openai.azure.com"
    )


def test_empty_string_returns_empty(normalize):
    assert normalize("") == ""
