"""Every Cypher statement in the platform filters by knowledge base from its first pattern."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ["apps/agent-runtime/engine", "apps/api/app", "apps/worker/worker"]
NODE = re.compile(r"\((\w*)((?::\w+)?)\s*(\{[^{}]*\})?\s*\)")
PATTERN_CLAUSE = re.compile(
    r"\b(?:OPTIONAL\s+)?(?:MATCH|MERGE)\b(.*?)"
    r"(?=\b(?:WHERE|WITH|RETURN|SET|DELETE|DETACH|MERGE|MATCH|OPTIONAL|ON\s+CREATE|UNWIND|CALL|ORDER)\b|\Z)",
    re.S | re.I,
)
CYPHER = re.compile(r"\b(MATCH|MERGE)\s*\(", re.I)


def _strings_in(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    out: list[tuple[int, str]] = []
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                v.value if isinstance(v, ast.Constant) else _expr_text(v.value)
                for v in node.values
            )
            out.append((node.lineno, text))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if not isinstance(parents.get(id(node)), ast.JoinedStr):
                out.append((node.lineno, node.value))
    return out


def _expr_text(expr: ast.AST) -> str:
    """entity_scope("e") and _VISIBLE.format(v="e") stand for their predicate on that variable."""
    src = ast.unparse(expr)
    m = re.match(r"""entity_scope\(['"](\w+)['"]\)""", src)
    if m:
        return f"{m.group(1)}.kb_id = $kb_id"
    return ""


def _statements() -> list[tuple[str, int, str]]:
    found = []
    for base in SOURCES:
        for path in (ROOT / base).rglob("*.py"):
            for line, text in _strings_in(path):
                if CYPHER.search(text) and (
                    ":Entity" in text or "[r" in text or "-[" in text
                ):
                    found.append((str(path.relative_to(ROOT)), line, text))
    return found


def unscoped_patterns(statement: str) -> list[str]:
    """Node patterns in MATCH and MERGE that could reach another knowledge base."""
    bad: list[str] = []
    text = re.sub(r"\s+", " ", statement)
    bound: set[str] = set(re.findall(r"YIELD node AS (\w+)", text))
    # a CALL subquery imports what its WITH names, those are bound outside
    scoped: set[str] = set(re.findall(r"(\w+)\.kb_id\b", text))
    scoped |= set(re.findall(r"(\w+)\.kb_id\s+IN\b", text))
    for clause in PATTERN_CLAUSE.findall(text):
        for var, label, props in NODE.findall(clause):
            has_kb = bool(props and "kb_id" in props)
            if has_kb or var in scoped or var in bound:
                if var:
                    bound.add(var)
                continue
            if var and var in bound:
                continue
            if (
                not label
                and var
                and re.search(rf"\({var}\s*\)", clause)
                and var in bound
            ):
                continue
            bad.append(f"({var}{label}{props})")
    return bad


def test_the_scanner_catches_what_it_should():
    assert unscoped_patterns(
        "MATCH (e:Entity {kb_id: $kb_id})-[r]-() SET r.weight = 1"
    ) == ["()"]
    assert unscoped_patterns("MATCH (e:Entity) RETURN e") == ["(e:Entity)"]
    assert unscoped_patterns(
        "MATCH (a:Entity {kb_id: $k})-[r]->(b:Entity) RETURN r"
    ) == ["(b:Entity)"]
    assert not unscoped_patterns(
        "MATCH (a:Entity {kb_id: $k})-[r]->(b:Entity {kb_id: $k}) RETURN r"
    )
    assert not unscoped_patterns("MATCH (e:Entity) WHERE e.kb_id IN $kb_ids RETURN e")


def test_every_statement_filters_by_knowledge_base():
    statements = _statements()
    assert len(statements) > 20
    problems = []
    for path, line, text in statements:
        # the GDPR purge walks out from a KB scoped node and removes by document id
        if "$doc_ids" in text and "$kb_ids" in text:
            continue
        bad = unscoped_patterns(text)
        if bad:
            problems.append(f"{path}:{line} {bad}")
    assert not problems, "\n".join(problems)


def test_reads_that_face_a_caller_carry_the_tenant_predicate_too():
    from engine.knowledge import hybrid_search as hs
    from engine.knowledge import neo4j_client as nc

    assert "$tenant_id" in nc.entity_scope(
        "x"
    ) and "x.kb_id = $kb_id" in nc.entity_scope("x")
    for build in (
        hs._match_names_cypher,
        hs._match_aliases_cypher,
        hs._hop_cypher,
        hs._direct_relationships_cypher,
    ):
        assert "$tenant_id" in build() and "$kb_id" in build()


def test_retrieval_has_no_or_over_aliases_and_caps_before_it_sorts():
    from engine.knowledge import hybrid_search as hs

    assert "any(a IN e.aliases" not in hs._match_names_cypher()
    assert "any(a IN" not in hs._match_aliases_cypher()
    assert "*1.." not in hs._hop_cypher(), "no variable length expansion"
    hop = hs._hop_cypher()
    assert hop.index("LIMIT $scan") < hop.index("ORDER BY") < hop.index("LIMIT $fanout")
    direct = hs._direct_relationships_cypher()
    assert " OR " not in direct.split("RETURN")[0].split("$tenant_id")[0]
    assert direct.index("LIMIT $scan") < direct.index("ORDER BY")


def test_lucene_query_carries_the_kb_and_escapes_input():
    from engine.knowledge.neo4j_client import fulltext_query, kb_token

    q = fulltext_query("11111111-2222-3333-4444-555555555555", 'Acme "Corp" (x) OR y:z')
    assert q.startswith(
        f"+kb_token:{kb_token('11111111-2222-3333-4444-555555555555')} +("
    )
    assert '\\"Corp\\"' in q and "\\(x\\)" in q and "y\\:z" in q
