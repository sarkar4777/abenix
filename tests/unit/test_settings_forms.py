"""Settings forms reject bad values with a plain reason: quotas, sandbox images."""

from __future__ import annotations

import pytest

from app.routers.settings import IMAGE_REF
from app.routers.team import quota_value


@pytest.mark.parametrize(
    "ref",
    [
        "alpine:3.20",
        "python:3.12-slim",
        "ghcr.io/navikt/mock-oauth2-server:2.1.10",
        "localhost:5000/abenix/api:latest",
        "busybox@sha256:" + "a" * 64,
    ],
)
def test_real_image_refs_pass(ref: str) -> None:
    assert IMAGE_REF.match(ref)


@pytest.mark.parametrize("ref", ["alpine 3.20", "foo;rm -rf", "UPPER:1", ":tag", ""])
def test_junk_image_refs_fail(ref: str) -> None:
    assert not IMAGE_REF.match(ref)


def test_quota_values() -> None:
    assert quota_value({}, "token_monthly_allowance", whole=True) == (None, None)
    assert quota_value({"k": ""}, "k", whole=True) == (None, None)
    assert quota_value({"k": 0}, "k", whole=True) == (0, None)
    assert quota_value({"k": "250000"}, "k", whole=True) == (250000, None)
    assert quota_value({"k": 12.345}, "k", whole=False) == (12.35, None)
    assert "negative" in quota_value({"k": -1}, "k", whole=False)[1]
    assert "whole" in quota_value({"k": 1.5}, "k", whole=True)[1]
    assert "number" in quota_value({"k": "ten"}, "k", whole=True)[1]
