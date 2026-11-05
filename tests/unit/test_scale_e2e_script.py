"""scripts/scale-e2e.sh runs on the bash macOS ships, reads cluster answers right and never prints a secret."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/scale-e2e.sh"
BASH32 = Path("/bin/bash")
needs_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")


def _harness(body: str, tmp_path: Path) -> subprocess.CompletedProcess:
    shell = str(BASH32) if BASH32.exists() else "bash"
    code = f'TMPDIR="{tmp_path}" source "{SCRIPT}"\n{body}\n'
    return subprocess.run(
        [shell, "-c", code], capture_output=True, text=True, timeout=60
    )


def test_it_parses_on_the_system_bash():
    shell = str(BASH32) if BASH32.exists() else "bash"
    subprocess.run([shell, "-n", str(SCRIPT)], check=True)


def test_no_construct_newer_than_bash_32():
    text = SCRIPT.read_text()
    for banned in (
        r"declare -A",
        r"\bmapfile\b",
        r"\breadarray\b",
        r"\$\{[a-zA-Z_]+,,\}",
        r"\$\{[a-zA-Z_]+\^\^\}",
        r"wait -n",
        r"\|&",
        r"&>>",
        r"coproc",
    ):
        assert not re.search(banned, text), banned


def test_tracing_is_never_on_and_the_token_only_reaches_curl_through_a_config_file():
    text = SCRIPT.read_text()
    assert "set -x" not in text
    assert not re.search(
        r"Authorization: Bearer \$\{?(tok|TOKEN)",
        text.replace('header = "Authorization: Bearer %s', ""),
    )
    assert 'chmod 600 "${AUTH}"' in text
    assert 'rm -rf "${PRIVATE}"' in text


def test_deploy_has_the_thin_subcommand():
    text = (ROOT / "scripts/deploy.sh").read_text()
    assert 'scale-e2e)      exec bash "${ROOT_DIR}/scripts/scale-e2e.sh" ;;' in text


def test_the_overlay_turns_on_every_autoscaler_it_tests():
    values = yaml.safe_load(
        (ROOT / "infra/helm/abenix/values-scale-test.yaml").read_text()
    )
    pools = {p["key"]: p for p in values["scaling"]["pools"]}
    assert pools["long-running"]["min_replicas"] == 0
    assert pools["default"]["max_replicas"] >= 2
    assert values["scaling"]["keda"]["cooldownPeriod"] < 300
    assert values["scaling"]["poolEnv"]["ABENIX_LLM_STUB"] == "1"
    for part in ("api", "web", "worker", "cognifyWorker"):
        assert values[part]["autoscaling"]["enabled"] is True
    assert values["telemetryIngest"]["autoscaling"]["enabled"] is True
    assert values["telemetryRules"]["autoscaling"]["enabled"] is True
    assert values["improvements"]["proofPool"]["keda"]["enabled"] is True


@needs_jq
def test_scaler_ready_needs_every_object_ready_and_none_in_fallback(tmp_path):
    def so(ready, fallback="False", paused=False):
        meta = {"name": "x"}
        if paused:
            meta["annotations"] = {"autoscaling.keda.sh/paused-replicas": "0"}
        return {
            "metadata": meta,
            "status": {
                "conditions": [
                    {"type": "Ready", "status": ready},
                    {"type": "Fallback", "status": fallback},
                ]
            },
        }

    cases = [
        ([so("True"), so("True")], True),
        ([so("True"), so("False")], False),
        ([so("True", fallback="True")], False),
        ([so("True"), so("False", paused=True)], True),
        ([], False),
    ]
    for items, expected in cases:
        doc = tmp_path / "so.json"
        doc.write_text(json.dumps({"items": items}))
        out = _harness(f'kc() {{ cat "{doc}"; }}\nscaler_ready', tmp_path)
        assert (out.returncode == 0) is expected, (items, out.stderr)


@needs_jq
def test_lag_reads_the_named_durable_and_empty_when_it_is_missing(tmp_path):
    doc = tmp_path / "jsz.json"
    doc.write_text(
        json.dumps(
            {
                "account_details": [
                    {
                        "stream_detail": [
                            {
                                "consumer_detail": [
                                    {
                                        "name": "abenix-default-consumer",
                                        "num_pending": 4,
                                        "num_ack_pending": 2,
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        )
    )
    out = _harness(
        f'kc() {{ cat "{doc}"; }}\n'
        'echo "lag=$(durable_lag default)"\necho "none=$(durable_lag gpu)"',
        tmp_path,
    )
    assert "lag=6" in out.stdout
    assert "none=\n" in out.stdout


def test_samples_give_the_peak_and_the_first_time_at_a_count(tmp_path):
    out = _harness(
        'printf "100 1\\n102 2\\n104 3\\n106 1\\n" > "${OUT}/sample.x"\n'
        'echo "peak=$(sample_peak x) first=$(sample_first x 3) never=[$(sample_first x 4)]"',
        tmp_path,
    )
    assert "peak=3 first=104 never=[]" in out.stdout


def test_a_failed_check_makes_the_run_fail_and_the_table_names_it(tmp_path):
    out = _harness(
        'record a PASS "fine"\nrecord b FAIL "broken"\nrecord f SKIP "why"\n'
        'print_table\necho "failed=${FAILED}"',
        tmp_path,
    )
    assert "failed=1" in out.stdout
    assert re.search(r"^b\s+FAIL\s+broken$", out.stdout, re.M)
    assert re.search(r"^f\s+SKIP\s+why$", out.stdout, re.M)


def test_a_missing_tool_is_exit_2_not_a_failed_check(tmp_path):
    out = _harness("need scale-e2e-no-such-tool", tmp_path)
    assert out.returncode == 2


def test_the_table_prints_what_was_measured(tmp_path):
    out = _harness('number "wake seconds" "12"\nprint_table', tmp_path)
    assert "wake seconds" in out.stdout and "12" in out.stdout
