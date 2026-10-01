"""Every tool declares what it needs. The lint, run as a test.

A tool that reads the environment directly is invisible to the admin screen,
the catalogue badges and the Integrations page, all of which are generated
from `config_fields`. CI runs scripts/check-tool-config.py as a step. This
runs the same check under pytest so a local run catches it before a push.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_check():
    spec = importlib.util.spec_from_file_location("check_tool_config", ROOT / "scripts" / "check-tool-config.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_every_tool_declares_its_configuration() -> None:
    check = _load_check()
    out = io.StringIO()
    with redirect_stdout(out):
        rc = check.main([])
    assert rc == 0, "\n" + out.getvalue()


def test_a_new_tool_with_a_declaration_is_visible_without_any_other_change() -> None:
    """The guarantee the admin screen rests on.

    Define a tool class, declare a field, and it is listed by the same
    collection the API uses. No catalogue entry, no UI change.
    """
    sys.path.insert(0, str(ROOT / "apps" / "agent-runtime"))
    from engine.tools.base import BaseTool, ConfigField, ToolResult

    class ProbeNewTool(BaseTool):
        name = "probe_new_tool"
        description = "exists only inside this test"
        input_schema = {"type": "object", "properties": {}}
        config_fields = (ConfigField("PROBE_NEW_TOOL_KEY", label="Key", kind="secret", required=True, group="Probe"),)

        async def execute(self, arguments):  # type: ignore[override]
            return ToolResult(content=self.cfg("PROBE_NEW_TOOL_KEY", required=True))

    fields = {f.key: f for f in ProbeNewTool.config_fields}
    assert fields["PROBE_NEW_TOOL_KEY"].required
    assert ProbeNewTool().to_dict()["config_fields"][0]["group"] == "Probe"
