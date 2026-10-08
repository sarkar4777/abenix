#!/usr/bin/env python3
"""Every value a tool needs must be declared on the tool.

A tool declares its configuration as `config_fields` on the class and reads
each value through `self.cfg(...)` or `engine.credentials.get(...)`. The admin
screen, the catalogue badges and the Integrations page are all generated from
those declarations, so a tool that reads the environment directly is invisible
to all of them. This check is what keeps that from happening again.

Rules

  1. No `os.environ` or `os.getenv` under engine/tools, except for names in
     INFRA_ENV, which are deployment plumbing an admin never configures.
  2. Every key read through cfg() or credentials.get() with a literal name is
     declared by some tool class in the package.
  3. Every declared key is read somewhere, or is marked dynamic because the
     tool builds the name at run time from a table.
  4. Every BaseTool subclass under engine/tools is reachable from the registry
     or the lazy list the API reads, or carries `# tool-registry: exempt`.
  5. Every tool declares its risk_tier.
  6. Every tool at medium tier or above declares an `effect`, READ_ONLY for
     one that only reads, so the autonomy gate knows what it changes.

Reads are found on the AST, so a name inside a string literal or a call split
over several lines is seen for what it is.

    python scripts/check-tool-config.py            fail on any problem
    python scripts/check-tool-config.py --report   list every read, by file
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "apps" / "agent-runtime"
TOOLS = RUNTIME / "engine" / "tools"

# Deployment plumbing. Read from the environment, never shown to an admin.
INFRA_ENV = {
    "DATABASE_URL",
    "DATABASE_URL_ASYNC",
    "ASYNC_DATABASE_URL",
    "REDIS_URL",
    "NATS_URL",
    "EXPORT_DIR",
    "TENANT_ID",
    "INTERNAL_API_URL",
    "ABENIX_API_SERVICE_HOST",
    "ABENIX_API_SERVICE_PORT",
    "API_BASE_URL",
    "ABENIX_API_URL",
    "ABENIX_INTERNAL_URL",
    "ABENIX_PLATFORM_API_KEY",
    "INTERNAL_API_TOKEN",
    "ABENIX_INTERNAL_API_KEY",
    "PLATFORM_API_KEY",
    "TRAJECTORY_DIR",
    "BLPG_CURATED_PATH",
    "SENTIMENT_LEXICON_OVERRIDE_PATH",
    "OPENSANCTIONS_DATA_PATH",
    "SEARCH_PROVIDER",
    "OPENAI_TTS_VOICE",
    "TSDB_URL",
    "TIMESCALE_URL",
    "MQTT_URL",
    "MQTT_BROKER_URL",
    "KAFKA_BOOTSTRAP_SERVERS",
    "DEFER_NOTIFY_WEBHOOK_URL",
    "BROWSER_AUTOMATION_ALLOWED_HOSTS",
    "LLM_RETRY_COUNT",
    "TOOL_TIMEOUT_DEFAULT",
    "_DL_URL",
    "_DL_AUTH",
    "SECRET_KEY",
    "JWT_PRIVATE_KEY",
    "JWT_ALGORITHM",
}
INFRA_PREFIXES = (
    "CODE_ASSET_",
    "SANDBOXED_JOB_",
    "POSTGRES_",
    "RUNTIME_",
    "OTEL_",
    "LOG_",
)

# Modules the API reads lazily because the executor builds them with context.
# Mirrors _LAZY_MODULES in apps/api/app/routers/tools.py.
LAZY_MODULES = {
    "engine.tools.knowledge_search",
    "engine.tools.knowledge_store",
    "engine.tools.graph_explorer_tool",
    "engine.tools.atlas_tools",
    "engine.tools.schema_portfolio_tool",
}

EXEMPT = re.compile(r"#\s*tool-registry:\s*exempt")


def is_infra(name: str) -> bool:
    return name in INFRA_ENV or name.startswith(INFRA_PREFIXES)


class _Reads(ast.NodeVisitor):
    """os.environ reads and cfg()/credentials.get() reads in one module."""

    def __init__(self) -> None:
        self.env: list[tuple[int, str | None]] = []  # (line, literal name or None)
        self.cfg: list[tuple[int, str | None]] = []

    @staticmethod
    def _is_os_environ(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "environ"
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        )

    def visit_Call(self, node: ast.Call) -> None:
        f = node.func
        first = node.args[0] if node.args else None
        lit = (
            first.value
            if isinstance(first, ast.Constant) and isinstance(first.value, str)
            else None
        )
        if isinstance(f, ast.Attribute):
            if f.attr == "get" and self._is_os_environ(f.value):
                self.env.append((node.lineno, lit))
            elif (
                f.attr == "getenv"
                and isinstance(f.value, ast.Name)
                and f.value.id == "os"
            ):
                self.env.append((node.lineno, lit))
            elif (
                f.attr == "cfg"
                and isinstance(f.value, ast.Name)
                and f.value.id == "self"
            ):
                self.cfg.append((node.lineno, lit))
            elif (
                f.attr == "get"
                and isinstance(f.value, ast.Name)
                and f.value.id == "credentials"
            ):
                self.cfg.append((node.lineno, lit))
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self._is_os_environ(node.value):
            lit = (
                node.slice.value
                if isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
                else None
            )
            self.env.append((node.lineno, lit))
        self.generic_visit(node)


def scan_files():
    env_reads: dict[str, list[tuple[Path, int]]] = defaultdict(list)
    dynamic: list[tuple[Path, int]] = []
    cfg_reads: dict[str, set[Path]] = defaultdict(set)
    cfg_dynamic: list[tuple[Path, int]] = []
    for f in sorted(TOOLS.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8-sig"))
        except SyntaxError as e:
            dynamic.append((f, e.lineno or 0))
            continue
        r = _Reads()
        r.visit(tree)
        for ln, name in r.env:
            if name is None:
                dynamic.append((f, ln))
            else:
                env_reads[name].append((f, ln))
        for ln, name in r.cfg:
            if name is None:
                cfg_dynamic.append((f, ln))
            else:
                cfg_reads[name].add(f)
    return env_reads, dynamic, cfg_reads, cfg_dynamic


def tool_classes():
    """Every BaseTool subclass under engine/tools, by import, plus failures."""
    sys.path.insert(0, str(RUNTIME))
    from engine.tools.base import BaseTool  # noqa: E402

    found: dict[str, type] = {}
    exempt: set[str] = set()
    failed: list[tuple[str, str]] = []
    for f in sorted(TOOLS.rglob("*.py")):
        if f.name == "__init__.py":
            continue
        rel = f.relative_to(RUNTIME).with_suffix("")
        mod = ".".join(rel.parts)
        src = f.read_text(encoding="utf-8-sig", errors="replace")
        try:
            m = importlib.import_module(mod)
        except Exception as e:  # noqa: BLE001
            failed.append((mod, repr(e)[:100]))
            continue
        for attr in vars(m).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseTool)
                and attr is not BaseTool
                and attr.__module__ == mod
                and not attr.__name__.startswith("_")
            ):
                if EXEMPT.search(src):
                    exempt.add(attr.__name__)
                found[f"{mod}.{attr.__name__}"] = attr
    return found, exempt, failed


def registered_names() -> set[str]:
    # list_tool_classes returns the registered slugs, not the classes.
    from engine.agent_executor import list_tool_classes  # noqa: E402

    try:
        return set(list_tool_classes())
    except Exception:  # noqa: BLE001
        return set()


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def main(argv: list[str]) -> int:
    report = "--report" in argv
    env_reads, dynamic, cfg_reads, cfg_dynamic = scan_files()
    classes, exempt, failed = tool_classes()
    declared: dict[str, list[str]] = defaultdict(list)
    dynamic_keys: set[str] = set()
    for qual, cls in classes.items():
        for fld in getattr(cls, "config_fields", ()) or ():
            declared[fld.key].append(getattr(cls, "name", qual))
            if getattr(fld, "dynamic", False):
                dynamic_keys.add(fld.key)

    problems: list[str] = []

    # 1. direct environment reads
    for name, sites in sorted(env_reads.items()):
        if is_infra(name):
            continue
        for f, i in sites:
            problems.append(
                f"{rel(f)}:{i}: reads {name} from the environment. Declare it in config_fields and read it with self.cfg()."
            )
    for f, i in dynamic:
        problems.append(
            f"{rel(f)}:{i}: reads the environment under a name built at run time. Use credentials.get() and declare the keys with dynamic=True."
        )

    # 2. reads of undeclared keys
    for key, files in sorted(cfg_reads.items()):
        if key not in declared and not is_infra(key):
            problems.append(
                f"{', '.join(sorted(rel(p) for p in files))}: reads {key} through cfg() but no tool declares it."
            )

    # 3. declared but never read
    for key in sorted(declared):
        if key in dynamic_keys or key in cfg_reads:
            continue
        problems.append(
            f"{key} is declared by {', '.join(declared[key])} but nothing reads it. Remove it or mark it dynamic=True."
        )

    # 4. reachability
    registered = registered_names()
    if registered:
        for qual, cls in sorted(classes.items()):
            name = getattr(cls, "name", "")
            mod = qual.rsplit(".", 1)[0]
            if name in registered or mod in LAZY_MODULES or cls.__name__ in exempt:
                continue
            problems.append(
                f"{qual} ({name}) is a tool the registry never offers, so it cannot appear on the admin screen. Register it in _ensure_tool_classes or mark the module `# tool-registry: exempt <reason>`."
            )

    # 5. every tool says how risky it is
    tiers = ("low", "medium", "high", "critical")
    for qual, cls in sorted(classes.items()):
        tier = cls.__dict__.get("risk_tier")
        if tier is None:
            problems.append(
                f'{qual} does not declare risk_tier. Add risk_tier = "low", "medium", "high" or "critical" to the class, see engine/risk.py TIER_GUIDE.'
            )
        elif tier not in tiers:
            problems.append(
                f"{qual} has risk_tier {tier!r}, expected one of {', '.join(tiers)}."
            )

    # 6. medium and above say what they change
    from engine.tools.base import Effect  # noqa: E402

    for qual, cls in sorted(classes.items()):
        tier = cls.__dict__.get("risk_tier") or getattr(cls, "risk_tier", "low")
        if tier not in ("medium", "high", "critical"):
            continue
        eff = getattr(cls, "effect", None)
        if eff is None:
            problems.append(
                f"{qual} is {tier} risk and does not declare effect. Add effect = Effect(kind=..., label=...) "
                "for what it changes, or effect = READ_ONLY if it only reads, see engine/tools/base.py."
            )
        elif not isinstance(eff, Effect):
            problems.append(f"{qual} has effect {eff!r}, expected an Effect.")

    if report:
        by_file: dict[Path, list[str]] = defaultdict(list)
        for name, sites in env_reads.items():
            for f, i in sites:
                by_file[f].append(
                    f"  {i:>4}  {'infra' if is_infra(name) else 'MIGRATE':<8} {name}"
                )
        for f in sorted(by_file):
            print(rel(f))
            print("\n".join(sorted(by_file[f])))
        print(
            f"\n{sum(len(v) for v in env_reads.values())} env reads, "
            f"{sum(1 for n in env_reads if not is_infra(n))} names to migrate, "
            f"{len(classes)} tool classes, {len(declared)} declared keys, "
            f"{len(cfg_dynamic)} dynamic cfg reads"
        )

    for w in failed:
        print(f"warning: could not import {w[0]}: {w[1]}")
    for p in problems:
        print(p)
    print(f"\n{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
