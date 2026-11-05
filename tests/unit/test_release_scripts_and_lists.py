"""Shell cleanup and exit codes, and lists the web and the server must agree on."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _function(script: str, name: str) -> str:
    text = (ROOT / script).read_text()
    match = re.search(rf"^{name}\(\) {{.*?^}}$", text, re.S | re.M)
    assert match, name
    return match.group(0)


def _burst(wait_exit: int) -> subprocess.CompletedProcess:
    harness = "\n".join(
        [
            "set -euo pipefail",
            "TESTBED_CHART=x TESTBED_NS=ns",
            "_testbed_up_check() { :; }",
            "step() { :; }",
            'warn() { echo "warn $1"; }',
            'err() { echo "err $1"; }',
            "helm() { :; }",
            f'kubectl() {{ if [ "$1" = wait ]; then return {wait_exit}; fi; echo done; }}',
            _function("scripts/deploy.sh", "testbed_load"),
            "testbed_load 10 5",
            "echo after",
        ]
    )
    return subprocess.run(["bash", "-c", harness], capture_output=True, text=True)


def test_a_burst_that_did_not_finish_fails_with_a_message():
    out = _burst(1)
    assert out.returncode != 0
    assert "err the burst did not finish" in out.stdout
    assert "after" not in out.stdout


def test_a_burst_that_finished_passes():
    out = _burst(0)
    assert out.returncode == 0 and "after" in out.stdout


def test_every_release_installed_through_check_is_remembered_for_cleanup():
    lines = (ROOT / "scripts/edge-e2e.sh").read_text().splitlines()
    checked = [
        (i, m.group(1))
        for i, line in enumerate(lines)
        if (m := re.search(r'^\s*check .* install_release "([^"]+)"', line))
    ]
    assert len(checked) == 3
    for i, release in checked:
        assert lines[i - 1].strip() == f'remember_release "{release}"'


def test_web_languages_match_the_server_list():
    from chunks_store import SEARCH_LANGUAGES

    source = (ROOT / "apps/web/src/lib/knowledge-settings.ts").read_text()
    block = source[source.index("SEARCH_LANGUAGES = [") : source.index("] as const")]
    assert tuple(re.findall(r"'([a-z]+)'", block)) == SEARCH_LANGUAGES


def test_js_sdk_search_keeps_the_degraded_reason():
    source = (ROOT / "packages/sdk/js/src/index.ts").read_text()
    assert "degraded?: string | null;" in source
    assert "degraded: data.degraded ?? null," in source


def test_credit_risk_overview_explains_the_portfolio_not_one_counterparty():
    page = (ROOT / "contractiq/web/src/app/credit-risk/page.tsx").read_text()
    key = re.search(r'<PageExplainer routeKey="([^"]+)"', page).group(1)
    assert key == "credit-risk"
    explain = (ROOT / "contractiq/web/src/lib/page_explanations.ts").read_text()
    start = explain.index(f"  '{key}': {{")
    entry = explain[start : explain.index("\n  },\n", start)]
    assert "every counterparty" in entry
    assert "single counterparty" not in entry
