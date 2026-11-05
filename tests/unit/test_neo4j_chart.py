"""The Neo4j chart renders the memory settings and refuses settings that cannot work."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

CHART = Path(__file__).resolve().parents[2] / "infra" / "helm" / "neo4j"
HELM = shutil.which("helm") or "/opt/homebrew/bin/helm"


def _template(*sets: str) -> subprocess.CompletedProcess:
    if not Path(HELM).exists():
        pytest.skip("helm is not installed")
    args = [HELM, "template", "t", str(CHART)]
    for s in sets:
        args += ["--set", s]
    return subprocess.run(args, capture_output=True, text=True)


def test_heap_page_cache_and_timeout_reach_the_pod():
    out = _template(
        "jvm.heap.max=4g",
        "jvm.pagecache=8g",
        "resources.limits.memory=16Gi",
        "transaction.timeout=120s",
    )
    assert out.returncode == 0, out.stderr
    for name, value in (
        ("NEO4J_server_memory_heap_max__size", "4g"),
        ("NEO4J_server_memory_pagecache_size", "8g"),
        ("NEO4J_db_transaction_timeout", "120s"),
    ):
        assert f'name: {name}\n              value: "{value}"' in out.stdout


def test_memory_that_cannot_fit_the_limit_fails_at_install():
    out = _template("jvm.heap.max=4g", "resources.limits.memory=2Gi")
    assert out.returncode != 0 and "memory limit" in out.stderr


def test_community_cannot_be_asked_for_replicas():
    out = _template("replicaCount=3")
    assert out.returncode != 0 and "replicaCount must be 1" in out.stderr


def test_enterprise_needs_the_license_and_changes_the_image():
    refused = _template("edition=enterprise")
    assert refused.returncode != 0 and "license" in refused.stderr
    ok = _template("edition=enterprise", "acceptLicenseAgreement=true")
    assert ok.returncode == 0, ok.stderr
    assert (
        "5.20.0-enterprise" in ok.stdout
        and "NEO4J_ACCEPT_LICENSE_AGREEMENT" in ok.stdout
    )


def test_default_is_community():
    out = _template()
    assert out.returncode == 0 and "enterprise" not in out.stdout.lower()
