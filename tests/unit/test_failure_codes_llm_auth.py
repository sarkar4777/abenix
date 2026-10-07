"""A revoked Claude token must read as an LLM credential problem, not cluster RBAC."""

from __future__ import annotations

import pytest

from app.core.failure_codes import classify_exception


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error', "
        "'message': 'OAuth access token has been revoked. Please obtain a new token.'}}",
        "OAuth access token has been revoked",
        "Incorrect API key provided",
    ],
)
def test_llm_credential_failures_are_llm_auth(message):
    assert classify_exception(Exception(message)) == "LLM_AUTH_ERROR"


def test_plain_401_stays_infra_auth():
    assert classify_exception(Exception("HTTP 401 Unauthorized")) == "INFRA_AUTH_ERROR"
