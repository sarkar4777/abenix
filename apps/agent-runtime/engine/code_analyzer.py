"""Code asset analyzer — turn a user-uploaded repo into a runnable spec."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AnalysisNote:
    level: str  # "info" | "warn" | "error"
    message: str
    suggestion: str = ""


@dataclass
class RepoAnalysis:
    language: str = "unknown"
    version: str = ""
    package_manager: str = ""
    entrypoint: str = ""
    suggested_image: str = ""
    suggested_build_command: str = ""
    suggested_run_command: str = ""
    notes: list[AnalysisNote] = field(default_factory=list)
    # Schema discovery — populated by probe_schemas() when an author-
    # supplied contract is detectable (abenix.yaml, examples/,
    # README fenced blocks). Stays None if nothing convincing was
    # found; callers fall back to smoke-test at invocation time.
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    schema_source: str = ""  # "abenix.yaml" | "examples" | "readme" | ""
    example_input: dict[str, Any] | None = None
    example_output: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "version": self.version,
            "package_manager": self.package_manager,
            "entrypoint": self.entrypoint,
            "suggested_image": self.suggested_image,
            "suggested_build_command": self.suggested_build_command,
            "suggested_run_command": self.suggested_run_command,
            "notes": [asdict(n) for n in self.notes],
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "schema_source": self.schema_source,
            "example_input": self.example_input,
            "example_output": self.example_output,
        }


def _find_one(root: Path, names: list[str]) -> Path | None:
    for name in names:
        # top-level first (most repos) then 1 level deep (monorepos)
        direct = root / name
        if direct.is_file():
            return direct
        for child in root.iterdir() if root.is_dir() else []:
            if child.is_dir():
                candidate = child / name
                if candidate.is_file():
                    return candidate
    return None


def _read(path: Path | None, max_bytes: int = 200_000) -> str:
    if not path:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_bytes]
    except Exception:
        return ""


def _pick_python_image(version: str) -> str:
    """Pick the Python sandbox image."""
    # Accept `version` for caller symmetry / future per-version overrides.
    _ = version
    return "python:3.12-slim"


def _pick_node_image(version: str) -> str:
    if not version:
        return "node:20-alpine"
    m = re.search(r"(\d{1,2})", version)
    if m:
        major = int(m.group(1))
        if major in (18, 20, 22):
            return f"node:{major}-alpine"
    return "node:20-alpine"


def _pick_go_image(version: str) -> str:
    m = re.search(r"go\s*(\d+\.\d+)", version)
    return f"golang:{m.group(1)}-alpine" if m else "golang:1.22-alpine"


def _pick_rust_image(_version: str) -> str:
    return "rust:1.75-slim"


def _pick_ruby_image(version: str) -> str:
    m = re.search(r"(\d+\.\d+)", version or "")
    return f"ruby:{m.group(1)}-slim" if m else "ruby:3.3-slim"


def _pick_java_image(version: str) -> str:
    m = re.search(r"(\d{2})", version or "")
    if m:
        major = int(m.group(1))
        if major in (11, 17, 21):
            return f"eclipse-temurin:{major}-jdk"
    return "eclipse-temurin:17-jdk"


def _pick_perl_image(version: str) -> str:
    # perl:<major>.<minor> covers 5.32/5.34/5.36/5.38 as standard tags.
    m = re.search(r"5\.(\d{2})", version or "")
    if m:
        return f"perl:5.{m.group(1)}-slim"
    return "perl:5.38-slim"


def _analyze_python(root: Path, a: RepoAnalysis) -> None:
    a.language = "python"

    # Version + package manager from pyproject.toml / setup.py / requirements.txt
    pyproject = _find_one(root, ["pyproject.toml"])
    reqs = _find_one(root, ["requirements.txt"])
    setup_py = _find_one(root, ["setup.py"])

    if pyproject:
        txt = _read(pyproject)
        # python version: [tool.poetry.dependencies] python = "^3.11"
        # or [project] requires-python = ">=3.11"
        m = re.search(
            r"python\s*=\s*['\"]([^'\"]+)['\"]"  # poetry
            r"|requires-python\s*=\s*['\"]([^'\"]+)['\"]",  # PEP 621
            txt,
        )
        if m:
            a.version = (m.group(1) or m.group(2) or "").strip()
        if "[tool.poetry]" in txt:
            a.package_manager = "poetry"
        elif "[tool.uv]" in txt or "uv.lock" in {p.name for p in root.iterdir()}:
            a.package_manager = "uv"
        else:
            a.package_manager = "pip"
    elif reqs:
        a.package_manager = "pip"
    elif setup_py:
        a.package_manager = "pip"
    else:
        a.package_manager = "pip"
        a.notes.append(
            AnalysisNote(
                "warn",
                "No pyproject.toml, setup.py, or requirements.txt found.",
                "Add requirements.txt listing your dependencies so the sandbox can pip-install them.",
            )
        )

    # Entrypoint — prefer main.py, app.py, run.py, __main__.py
    for candidate in ("main.py", "app.py", "run.py", "cli.py", "__main__.py"):
        p = _find_one(root, [candidate])
        if p:
            a.entrypoint = str(p.relative_to(root))
            break
    if not a.entrypoint:
        # Find any .py file at top level
        top_py = [p for p in root.iterdir() if p.suffix == ".py"]
        if top_py:
            a.entrypoint = top_py[0].name
        else:
            a.notes.append(
                AnalysisNote(
                    "warn",
                    "No entrypoint .py file found at the top of the repo.",
                    "Add main.py that reads JSON from stdin and prints JSON to stdout.",
                )
            )

    a.suggested_image = _pick_python_image(a.version)

    # Build + run commands
    if a.package_manager == "poetry":
        a.suggested_build_command = (
            "pip install poetry && poetry install --no-interaction --no-root"
        )
        a.suggested_run_command = f"poetry run python {a.entrypoint or 'main.py'}"
    elif a.package_manager == "uv":
        a.suggested_build_command = "pip install uv && uv sync"
        a.suggested_run_command = f"uv run python {a.entrypoint or 'main.py'}"
    elif reqs:
        a.suggested_build_command = "pip install --no-cache-dir -r requirements.txt"
        a.suggested_run_command = f"python {a.entrypoint or 'main.py'}"
    else:
        a.suggested_build_command = "true"  # no deps
        a.suggested_run_command = f"python {a.entrypoint or 'main.py'}"


def _analyze_node(root: Path, a: RepoAnalysis) -> None:
    a.language = "node"
    pkg = _find_one(root, ["package.json"])
    if not pkg:
        a.notes.append(
            AnalysisNote(
                "error", "package.json not found.", "Is this really a Node project?"
            )
        )
        return
    try:
        pkg_data = json.loads(_read(pkg))
    except Exception:
        pkg_data = {}

    engines = (pkg_data.get("engines") or {}).get("node", "")
    a.version = engines or "20"

    # Package manager: prefer pnpm > yarn > npm based on lockfile
    if _find_one(root, ["pnpm-lock.yaml"]):
        a.package_manager = "pnpm"
    elif _find_one(root, ["yarn.lock"]):
        a.package_manager = "yarn"
    else:
        a.package_manager = "npm"

    # Entrypoint: package.json "main" or scripts.start
    main = pkg_data.get("main") or ""
    start_script = (pkg_data.get("scripts") or {}).get("start", "")
    if main:
        a.entrypoint = main
    elif start_script:
        a.entrypoint = "(via npm start)"
    else:
        # fallback scan
        for candidate in (
            "index.js",
            "index.mjs",
            "index.ts",
            "src/index.js",
            "src/index.ts",
        ):
            p = _find_one(root, [candidate])
            if p:
                a.entrypoint = str(p.relative_to(root))
                break

    a.suggested_image = _pick_node_image(a.version)

    # Build: install deps. Avoid --production so dev deps like TS compiler are included.
    if a.package_manager == "pnpm":
        a.suggested_build_command = (
            "npm install -g pnpm && pnpm install --frozen-lockfile"
        )
    elif a.package_manager == "yarn":
        a.suggested_build_command = (
            "npm install -g yarn && yarn install --frozen-lockfile"
        )
    else:
        a.suggested_build_command = (
            "npm ci --no-audit --no-fund || npm install --no-audit --no-fund"
        )

    if start_script:
        a.suggested_run_command = f"{a.package_manager} start"
    elif a.entrypoint.endswith(".ts"):
        # Need ts-node for .ts direct exec
        a.suggested_run_command = f"npx -y tsx {a.entrypoint}"
    elif a.entrypoint:
        a.suggested_run_command = f"node {a.entrypoint}"
    else:
        a.suggested_run_command = "node index.js"
        a.notes.append(
            AnalysisNote(
                "warn",
                "No main/entrypoint declared in package.json.",
                'Add "main": "index.js" or a "start" script so the runner knows what to invoke.',
            )
        )


def _analyze_go(root: Path, a: RepoAnalysis) -> None:
    a.language = "go"
    gomod = _find_one(root, ["go.mod"])
    if not gomod:
        a.notes.append(AnalysisNote("error", "go.mod not found."))
        return
    # Extract the `go 1.22` directive rather than blindly grabbing line 2.
    gmt = _read(gomod)
    mv = re.search(r"^go\s+(\d+\.\d+)", gmt, flags=re.MULTILINE)
    a.version = f"go {mv.group(1)}" if mv else ""
    a.package_manager = "go modules"
    a.suggested_image = _pick_go_image(a.version)

    # Entrypoint resolution:
    #   * Single-package repo → main.go at root → build path "."
    #   * cmd/<app>/main.go layout → find the first one, build that path
    #   * `cmd/main.go` (some older Go idioms) → "./cmd"
    build_path = "."
    # STRICTLY at-root — _find_one recurses one level deep which would
    # falsely match cmd/main.go and produce build_path="." (wrong; should
    # be "./cmd"). Only the exact path root/main.go means "build from
    # repo root".
    if (root / "main.go").is_file():
        a.entrypoint = "main.go"
        build_path = "."
    else:
        # Look for cmd/*/main.go — preferred for multi-binary repos.
        cmd_dir = root / "cmd"
        if cmd_dir.is_dir():
            for sub in sorted(cmd_dir.iterdir()):
                if sub.is_dir() and (sub / "main.go").is_file():
                    a.entrypoint = f"cmd/{sub.name}/main.go"
                    build_path = f"./cmd/{sub.name}"
                    break
        if not a.entrypoint:
            cmd_main = root / "cmd" / "main.go"
            if cmd_main.is_file():
                a.entrypoint = "cmd/main.go"
                build_path = "./cmd"

    a.suggested_build_command = (
        "export GOCACHE=/tmp/go-cache GOPATH=/tmp/go GOTMPDIR=/tmp && "
        f"go build -o /tmp/bin {build_path}"
    )
    a.suggested_run_command = "/tmp/bin"


def _analyze_rust(root: Path, a: RepoAnalysis) -> None:
    a.language = "rust"
    cargo = _find_one(root, ["Cargo.toml"])
    if not cargo:
        a.notes.append(AnalysisNote("error", "Cargo.toml not found."))
        return
    a.package_manager = "cargo"
    a.suggested_image = _pick_rust_image(a.version)
    a.suggested_build_command = "cargo build --release --quiet"
    a.suggested_run_command = "cargo run --release --quiet"
    main_rs = _find_one(root, ["src/main.rs"])
    if main_rs:
        a.entrypoint = "src/main.rs"


def _analyze_ruby(root: Path, a: RepoAnalysis) -> None:
    a.language = "ruby"
    gf = _find_one(root, ["Gemfile"])
    a.package_manager = "bundler" if gf else "gem"
    # Gemfile may specify ruby "3.2"
    if gf:
        m = re.search(r"ruby\s+['\"]([^'\"]+)['\"]", _read(gf))
        if m:
            a.version = m.group(1)
    a.suggested_image = _pick_ruby_image(a.version)
    a.suggested_build_command = "bundle install --quiet" if gf else "true"
    entry = _find_one(root, ["main.rb", "app.rb"])
    if entry:
        a.entrypoint = str(entry.relative_to(root))
    a.suggested_run_command = f"ruby {a.entrypoint or 'main.rb'}"


def _analyze_perl(root: Path, a: RepoAnalysis) -> None:
    a.language = "perl"
    # Evidence files in order: cpanfile (modern), Makefile.PL + META.json (classic),
    # .perl-version, shebang in main script.
    cpanfile = _find_one(root, ["cpanfile"])
    meta = _find_one(root, ["META.json", "META.yml"])
    pv = _find_one(root, [".perl-version"])

    # A cpanfile with no `requires` lines effectively declares "core-only".
    # Running `cpanm --installdeps` in that case is a waste and fails on
    # the slim image (cpanm not bundled). Detect by scanning the cpanfile.
    cpanfile_has_deps = False
    if cpanfile:
        txt = _read(cpanfile)
        cpanfile_has_deps = bool(
            re.search(r"^\s*(requires|recommends|suggests)\s+", txt, flags=re.MULTILINE)
        )

    if cpanfile and cpanfile_has_deps:
        a.package_manager = "cpanm"
        # cpanm isn't bundled in perl:*-slim; install it, then deps. HOME
        # writable because slim images run as root by default inside the
        # sandbox's nonroot-user — overridden to /tmp.
        a.suggested_build_command = (
            "export HOME=/tmp PERL_MM_USE_DEFAULT=1 && "
            "curl -sSL https://cpanmin.us | perl - App::cpanminus && "
            "cpanm --quiet --notest --installdeps ."
        )
    elif meta:
        a.package_manager = "cpanm"
        a.suggested_build_command = (
            "export HOME=/tmp PERL_MM_USE_DEFAULT=1 && "
            "curl -sSL https://cpanmin.us | perl - App::cpanminus && "
            "cpanm --quiet --notest --installdeps ."
        )
    else:
        # core-only, or cpanfile present but empty → no build needed.
        a.package_manager = "core" if not cpanfile else "cpanm"
        a.suggested_build_command = "true"
    if pv:
        a.version = _read(pv).strip()
    # Entrypoint heuristic
    for name in ("main.pl", "app.pl", "run.pl", "script.pl", "bin/main.pl"):
        p = _find_one(root, [name])
        if p:
            a.entrypoint = str(p.relative_to(root))
            break
    if not a.entrypoint:
        top = [p for p in root.iterdir() if p.suffix == ".pl"]
        if top:
            a.entrypoint = top[0].name
        else:
            a.notes.append(
                AnalysisNote(
                    "warn",
                    "No .pl entrypoint found at the repo root.",
                    "Add main.pl that reads JSON from stdin and prints JSON to stdout.",
                )
            )
    a.suggested_image = _pick_perl_image(a.version)
    # -I lib so `use TextSummary;` finds modules under ./lib without
    # requiring the user to tweak @INC themselves.
    a.suggested_run_command = f"perl -Ilib {a.entrypoint or 'main.pl'}"


def _analyze_java(root: Path, a: RepoAnalysis) -> None:
    a.language = "java"
    pom = _find_one(root, ["pom.xml"])
    gradle = _find_one(root, ["build.gradle", "build.gradle.kts"])
    if pom:
        a.package_manager = "maven"
        # Prefer <java.version> (common), fall back to
        # <maven.compiler.source> / <maven.compiler.target>, finally
        # <properties>/anything that names an integer Java major.
        txt = _read(pom)
        m = (
            re.search(r"<java\.version>(\d+)</java\.version>", txt)
            or re.search(
                r"<maven\.compiler\.source>(\d+)</maven\.compiler\.source>", txt
            )
            or re.search(
                r"<maven\.compiler\.target>(\d+)</maven\.compiler\.target>", txt
            )
        )
        if m:
            a.version = m.group(1)
        src_dir = root / "src" / "main" / "java"
        if src_dir.is_dir():
            a.suggested_build_command = (
                "export HOME=/tmp && "
                "find src/main/java -name '*.java' > /tmp/sources.list && "
                "mkdir -p /tmp/classes && "
                "javac -d /tmp/classes @/tmp/sources.list"
            )
            # Guess the main class from the pom.xml artifactId + entry heuristics.
            main_class = "App"
            # Scan for the class containing `public static void main(`
            for java_file in src_dir.rglob("*.java"):
                try:
                    content = java_file.read_text(encoding="utf-8", errors="replace")
                    if "public static void main(" in content:
                        # Reconstruct package.Class from path.
                        rel = java_file.relative_to(src_dir)
                        pkg = ".".join(rel.parts[:-1])
                        cls = rel.stem
                        main_class = f"{pkg}.{cls}" if pkg else cls
                        a.entrypoint = str(java_file.relative_to(root))
                        break
                except Exception:
                    continue
            a.suggested_run_command = f"java -cp /tmp/classes {main_class}"
        else:
            a.suggested_build_command = "export HOME=/tmp && mvn -q -DskipTests -Dmaven.repo.local=/tmp/.m2 package"
            a.suggested_run_command = "java -jar target/*.jar"
    elif gradle:
        a.package_manager = "gradle"
        a.suggested_build_command = "export HOME=/tmp GRADLE_USER_HOME=/tmp/.gradle && gradle build -q --no-daemon"
        a.suggested_run_command = "java -jar build/libs/*.jar"
    a.suggested_image = _pick_java_image(a.version)


_LANGUAGE_RULES: list[tuple[list[str], callable]] = [
    (["pyproject.toml", "requirements.txt", "setup.py", "Pipfile"], _analyze_python),
    (["package.json"], _analyze_node),
    (["go.mod"], _analyze_go),
    (["Cargo.toml"], _analyze_rust),
    (["Gemfile"], _analyze_ruby),
    (["pom.xml", "build.gradle", "build.gradle.kts"], _analyze_java),
    (["cpanfile", "META.json", "Makefile.PL", ".perl-version"], _analyze_perl),
]


def analyze_directory(root: Path) -> RepoAnalysis:
    """Inspect a directory and produce a RepoAnalysis."""
    root = Path(root)
    if not root.is_dir():
        return RepoAnalysis(
            notes=[AnalysisNote("error", f"Not a directory: {root}")],
        )

    a = RepoAnalysis()
    matched: list[str] = []
    for markers, fn in _LANGUAGE_RULES:
        if any((root / m).is_file() for m in markers):
            matched.append(markers[0])
            if a.language == "unknown":
                fn(root, a)

    if not matched:
        # Fallback: bare source files with no package manifest.
        py = list(root.glob("*.py"))
        js = list(root.glob("*.js"))
        pl = list(root.glob("*.pl"))
        if py:
            _analyze_python(root, a)
        elif js:
            _analyze_node(root, a)
        elif pl:
            _analyze_perl(root, a)
        else:
            a.notes.append(
                AnalysisNote(
                    "error",
                    "Couldn't detect a supported language from the files in this repo.",
                    "Supported: Python, Node.js, Go, Rust, Ruby, Java, Perl. "
                    "Add the appropriate manifest (pyproject.toml, package.json, "
                    "go.mod, Cargo.toml, Gemfile, pom.xml, cpanfile, etc.).",
                )
            )

    if len(matched) > 1:
        a.notes.append(
            AnalysisNote(
                "info",
                f"Multiple language markers present: {', '.join(matched)}.",
                "Analyzed as "
                f"{a.language}; specify the entrypoint manually if a different "
                "language is the main build target.",
            )
        )

    if a.language != "unknown" and a.suggested_image:
        a.notes.append(
            AnalysisNote(
                "info",
                f"Suggested image: {a.suggested_image}",
                "You can override this in the asset settings to pin a specific "
                "version tag (e.g. python:3.11.9-slim).",
            )
        )

    # Populate input/output schemas from author-supplied contracts.
    # Silent on miss — the API upload path follows up with a
    # smoke-test probe if schemas are still empty after this call.
    try:
        probe_schemas(root, a)
    except Exception as e:
        logger.debug("probe_schemas failed: %s", e)

    return a


def _infer_schema_from_example(obj: Any) -> dict[str, Any]:
    """Best-effort JSON-Schema draft-7 inference from a sample JSON."""

    def _schema_of(v: Any) -> dict[str, Any]:
        if isinstance(v, bool):
            return {"type": "boolean"}
        if isinstance(v, int):
            return {"type": "integer"}
        if isinstance(v, float):
            return {"type": "number"}
        if isinstance(v, str):
            return {"type": "string"}
        if v is None:
            return {"type": "null"}
        if isinstance(v, list):
            if not v:
                return {"type": "array", "items": {}}
            return {"type": "array", "items": _schema_of(v[0])}
        if isinstance(v, dict):
            return {
                "type": "object",
                "properties": {k: _schema_of(vv) for k, vv in v.items()},
                "required": list(v.keys()),
            }
        return {}

    return _schema_of(obj)


def _probe_abenix_yaml(
    root: Path,
) -> tuple[dict | None, dict | None, dict | None, dict | None, str]:
    """Priority 1 — explicit contract in abenix.yaml at zip root."""
    for name in ("abenix.yaml", "abenix.yml", ".abenix.yaml"):
        p = root / name
        if not p.is_file():
            continue
        try:
            import yaml

            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                continue
            return (
                (
                    data.get("input_schema")
                    if isinstance(data.get("input_schema"), dict)
                    else None
                ),
                (
                    data.get("output_schema")
                    if isinstance(data.get("output_schema"), dict)
                    else None
                ),
                (
                    data.get("example_input")
                    if isinstance(data.get("example_input"), dict)
                    else None
                ),
                (
                    data.get("example_output")
                    if isinstance(data.get("example_output"), dict)
                    else None
                ),
                "abenix.yaml",
            )
        except Exception as e:
            logger.debug("abenix.yaml parse failed: %s", e)
    return None, None, None, None, ""


def _probe_examples_dir(
    root: Path,
) -> tuple[dict | None, dict | None, dict | None, dict | None, str]:
    """Priority 2 — examples/input.json + examples/output.json."""
    ex_in = root / "examples" / "input.json"
    ex_out = root / "examples" / "output.json"
    if not ex_in.is_file() and not ex_out.is_file():
        return None, None, None, None, ""

    in_obj = out_obj = None
    in_schema = out_schema = None
    try:
        if ex_in.is_file():
            in_obj = json.loads(ex_in.read_text(encoding="utf-8"))
            if isinstance(in_obj, dict):
                in_schema = _infer_schema_from_example(in_obj)
    except Exception as e:
        logger.debug("examples/input.json parse failed: %s", e)
    try:
        if ex_out.is_file():
            out_obj = json.loads(ex_out.read_text(encoding="utf-8"))
            if isinstance(out_obj, dict):
                out_schema = _infer_schema_from_example(out_obj)
    except Exception as e:
        logger.debug("examples/output.json parse failed: %s", e)

    if not in_schema and not out_schema:
        return None, None, None, None, ""
    return in_schema, out_schema, in_obj, out_obj, "examples"


def _probe_readme_fenced_blocks(
    root: Path,
) -> tuple[dict | None, dict | None, dict | None, dict | None, str]:
    """Priority 3 — README.md fenced code blocks tagged json and"""
    for name in ("README.md", "README.MD", "readme.md", "Readme.md"):
        p = root / name
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            break
    else:
        return None, None, None, None, ""

    fence_pat = re.compile(
        r"(?:```+)\s*(json)(?:\s+(input|output))?\s*\n(.*?)(?:```+)",
        re.DOTALL | re.IGNORECASE,
    )
    heading_pat = re.compile(
        r"^\s*#+\s+(input|output)\s*$", re.MULTILINE | re.IGNORECASE
    )

    in_obj = out_obj = None

    # Scan for tagged fences first
    for m in fence_pat.finditer(text):
        tag = (m.group(2) or "").lower()
        body = m.group(3).strip()
        try:
            obj = json.loads(body)
        except Exception:
            continue
        if tag == "input" and in_obj is None:
            in_obj = obj if isinstance(obj, dict) else None
        elif tag == "output" and out_obj is None:
            out_obj = obj if isinstance(obj, dict) else None

    # If tagged fences didn't cover both, fall back to heading-driven
    # matching (### Input ... ```json ...``` ... ### Output ...).
    if in_obj is None or out_obj is None:
        headings = [(m.start(), m.group(1).lower()) for m in heading_pat.finditer(text)]
        for start, tag in headings:
            # Find the next ```json block after this heading
            segment = text[start:]
            m = re.search(r"```+\s*json\b[^\n]*\n(.*?)(?:```+)", segment, re.DOTALL)
            if not m:
                continue
            try:
                obj = json.loads(m.group(1).strip())
            except Exception:
                continue
            if tag == "input" and in_obj is None and isinstance(obj, dict):
                in_obj = obj
            elif tag == "output" and out_obj is None and isinstance(obj, dict):
                out_obj = obj

    if not in_obj and not out_obj:
        return None, None, None, None, ""
    return (
        _infer_schema_from_example(in_obj) if in_obj else None,
        _infer_schema_from_example(out_obj) if out_obj else None,
        in_obj,
        out_obj,
        "readme",
    )


def probe_schemas(root: Path, analysis: RepoAnalysis) -> None:
    """Populate analysis.input_schema / output_schema / example_input /"""
    sources: list[str] = []
    for probe in (_probe_abenix_yaml, _probe_examples_dir, _probe_readme_fenced_blocks):
        in_s, out_s, in_ex, out_ex, src = probe(root)
        if not any((in_s, out_s, in_ex, out_ex)):
            continue
        if in_s and not analysis.input_schema:
            analysis.input_schema = in_s
        if out_s and not analysis.output_schema:
            analysis.output_schema = out_s
        if in_ex and not analysis.example_input:
            analysis.example_input = in_ex
        if out_ex and not analysis.example_output:
            analysis.example_output = out_ex
        if src:
            sources.append(src)
    if sources:
        analysis.schema_source = "+".join(sources)
        analysis.notes.append(
            AnalysisNote(
                "info",
                f"Input / output contract discovered from {analysis.schema_source}.",
                "The Builder will pre-fill pipeline-node arguments from this schema. "
                "Authors can override in the asset settings if inference is wrong.",
            )
        )


def generate_json_wrapper(
    *,
    language: str,
    entrypoint: str,
    run_command: str,
) -> str:
    """Generate a shell wrapper that:"""
    # Store input in /tmp/input.json (available in the sandbox's writable tmpfs).
    # User code reads it from /tmp/input.json OR from stdin — our wrapper
    # pipes stdin through too, so both patterns work.
    return "set -e; " "cat > /tmp/input.json; " f"cat /tmp/input.json | {run_command}"
