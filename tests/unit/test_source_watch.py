"""Source Watch: normalisation per kind, diffs, change detection, fetch safety, kill switches and pausing."""

from __future__ import annotations

import asyncio
import io
import json
import uuid
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy.dialects import postgresql

from app.services import source_watch as SW
from engine import governance
from engine.sources import diff as D
from engine.sources import normalize as N
from models.source_watch import SourceChange, SourceSnapshot, WatchSource

TENANT = uuid.uuid4()


# Normalisation

PAGE = b"""<!doctype html><html><head><title>Carrier  tariff</title>
<style>.a{color:red}</style><script>var nonce = "abc123";</script></head>
<body><nav><a href="/">Home</a><a href="/news">News</a></nav>
<header role="banner"><div>Site banner</div></header>
<main id="content"><h1>Reporting</h1>
<p>The carrier <b>shall</b> publish a tariff
   every quarter.</p>
<ul><li>Shetland</li><li>Highlands &amp; Islands</li></ul>
<table><tr><th>Zone</th><th>Rate</th></tr><tr><td>Shetland</td><td>12</td></tr></table>
<div class="related" aria-hidden="true">Related links</div>
</main><aside>Popular pages</aside><footer>Copyright</footer></body></html>"""


def test_html_drops_noise_and_keeps_structure():
    n = N.normalize("html", PAGE, "text/html; charset=utf-8")
    assert n.title == "Carrier tariff"
    for noise in (
        "nonce",
        "Home",
        "Site banner",
        "Related links",
        "Popular",
        "Copyright",
        "color",
    ):
        assert noise not in n.text
    assert "# Reporting" in n.text
    assert "The carrier shall publish a tariff every quarter." in n.text
    assert "- Shetland\n- Highlands & Islands" in n.text
    assert "Zone | Rate\nShetland | 12" in n.text


def test_html_noise_change_gives_the_same_text():
    other = PAGE.replace(b"abc123", b"zzz999").replace(b"Popular pages", b"Trending")
    assert N.normalize("html", PAGE).text == N.normalize("html", other).text


def test_html_selector_narrows_and_reports_misses():
    n = N.normalize("html", PAGE, selector="main#content ul")
    assert n.text == "- Shetland\n- Highlands & Islands"
    miss = N.normalize("html", PAGE, selector=".nope")
    assert miss.text == "" and "matched nothing" in miss.notes[0]
    with pytest.raises(N.NormalizeError):
        N.parse_css("div:nth-child(2)")


def _pdf(text: str) -> bytes:
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length "
        + str(len(content)).encode()
        + b" >>\nstream\n"
        + content
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for o in offsets:
        out.write(f"{o:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return out.getvalue()


def test_pdf_text_has_page_markers():
    n = N.normalize("pdf", _pdf("Default values apply from 2026"))
    assert n.text.startswith("[page 1]")
    assert "Default values apply from 2026" in n.text


def test_pdf_garbage_is_a_clear_error():
    with pytest.raises(N.NormalizeError):
        N.normalize("pdf", b"not a pdf")


def _xlsx(rows: list[list[object]]) -> bytes:
    shared: list[str] = []
    cells = []
    for r, row in enumerate(rows, 1):
        cs = []
        for c, v in enumerate(row):
            ref = f"{chr(65 + c)}{r}"
            if isinstance(v, str):
                shared.append(v)
                cs.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
            else:
                cs.append(f'<c r="{ref}"><v>{v}</v></c>')
        cells.append(f'<row r="{r}">{"".join(cs)}</row>')
    m = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{m}" xmlns:r="{rel}"><sheets><sheet name="Rates" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>',
        )
        z.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="{m}">'
            + "".join(f"<si><t>{s}</t></si>" for s in shared)
            + "</sst>",
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{m}"><sheetData>{"".join(cells)}</sheetData></worksheet>',
        )
    return buf.getvalue()


def test_xlsx_rows_are_read_without_optional_libraries():
    n = N.normalize(
        "xlsx", _xlsx([["Postcode area", "Surcharge"], ["IV27", 0.89], ["ZE2", 2.0]])
    )
    assert n.tables == {
        "Rates": [["Postcode area", "Surcharge"], ["IV27", "0.89"], ["ZE2", "2"]]
    }
    assert "## Rates\nPostcode area | Surcharge" in n.text
    with pytest.raises(N.NormalizeError):
        N.normalize("xlsx", _xlsx([["a"]]), selector="Other sheet")


def test_csv_rows_are_trimmed():
    n = N.normalize("csv", b"id; name ;\n1;  Alice  ;\n\n2;Bob;\n")
    assert n.tables == {"": [["id", "name"], ["1", "Alice"], ["2", "Bob"]]}


def test_json_is_canonical_and_pointer_selects():
    a = N.normalize("json", b'{"b": 1, "a": {"y": 2, "x": [1, 2]}}')
    b = N.normalize("json", b'{"a":{"x":[1,2],"y":2},"b":1}')
    assert a.text == b.text
    assert json.loads(
        N.normalize("json", b'{"a":{"x":[1,2]}}', selector="/a/x").text
    ) == [1, 2]
    with pytest.raises(N.NormalizeError):
        N.normalize("json", b'{"a":1}', selector="/missing")


def test_rss_and_atom_become_item_rows():
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Notices</title>
    <item><title>New rule</title><link>https://x.test/1</link><guid>n1</guid>
    <pubDate>Mon, 05 Oct 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;Body &lt;b&gt;text&lt;/b&gt;&lt;/p&gt;</description></item>
    </channel></rss>"""
    n = N.normalize("rss", rss)
    assert n.title == "Notices"
    assert n.tables["Notices"][1][:2] == ["n1", "New rule"]
    assert n.tables["Notices"][1][4] == "Body text"
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>
    <entry><id>e1</id><title>T</title><link href="https://x.test/e1"/><updated>2026-01-01</updated></entry></feed>"""
    a = N.normalize("rss", atom)
    assert a.tables["A"][1][:4] == ["e1", "T", "2026-01-01", "https://x.test/e1"]
    with pytest.raises(N.NormalizeError):
        N.normalize("rss", b'<!DOCTYPE x [<!ENTITY a "b">]><rss/>')


def test_nul_characters_never_reach_the_database():
    n = N.normalize("csv", b"a,b\x00c\n")
    assert "\x00" not in n.text and n.tables == {"": [["a", "bc"]]}


def test_guess_kind():
    assert N.guess_kind("application/pdf") == "pdf"
    assert N.guess_kind("", "https://x/a.csv?y=1") == "csv"
    assert N.guess_kind("text/plain", "", b' {"a":1}') == "json"
    assert N.guess_kind("application/rss+xml") == "rss"
    assert N.guess_kind("text/html") == "html"


# Diffs


def test_text_diff_hunks_and_summary():
    d = D.compare("html", "a\nb\nc\nd", "a\nB shall apply\nc\nd\ne")
    assert d["stats"]["added"] == 2 and d["stats"]["removed"] == 1
    ops = [(x["op"], x["text"]) for x in d["hunks"][0]["lines"]]
    assert ("-", "b") in ops and ("+", "B shall apply") in ops and (" ", "a") in ops
    assert d["summary"].startswith("2 lines added and 1 removed")
    assert d["materiality_hint"] in ("medium", "high")


def test_identical_content_is_no_change():
    assert D.compare("html", "same", "same") is None
    t = {"": [["id", "v"], ["1", "a"]]}
    assert D.compare("csv", "", "", t, json.loads(json.dumps(t))) is None


def test_table_diff_by_key_column():
    old = {"": [["code", "rate"], ["1", "5"], ["2", "6"], ["3", "7"]]}
    new = {"": [["code", "rate"], ["1", "5"], ["2", "6.5"], ["4", "8"]]}
    d = D.compare("csv", "", "", old, new)
    sh = d["sheets"][0]
    assert sh["key_column"] == "code"
    assert sh["added"] == [["4", "8"]] and sh["removed"] == [["3", "7"]]
    assert sh["changed"][0]["key"] == "2" and sh["changed"][0]["columns"] == ["rate"]
    assert "1 row added" in d["summary"] and "1 row changed" in d["summary"]


def test_table_diff_without_key_counts_duplicates():
    old = {"s": [["a", "b"], ["x", "1"], ["x", "1"]]}
    new = {"s": [["a", "b"], ["x", "1"], ["x", "1"], ["x", "1"]]}
    d = D.compare("xlsx", "", "", old, new)
    assert d["sheets"][0]["added"] == [["x", "1"]] and d["sheets"][0]["removed"] == []


def test_small_wording_change_is_a_low_hint():
    assert D.compare("html", "Hello there", "Hello world")["materiality_hint"] == "low"


# Fetch safety


def test_private_and_odd_targets_are_refused(monkeypatch):
    monkeypatch.delenv("SOURCE_WATCH_ALLOW_PRIVATE_TARGETS", raising=False)
    run = asyncio.run
    assert "private" in run(SW.blocked_reason("http://127.0.0.1/x"))
    assert "private" in run(SW.blocked_reason("http://10.1.2.3/x"))
    assert "private" in run(
        SW.blocked_reason("http://169.254.169.254/latest/meta-data")
    )
    assert "private" in run(SW.blocked_reason("http://[::ffff:127.0.0.1]/"))
    assert "http" in run(SW.blocked_reason("file:///etc/passwd"))
    assert "credential" in run(SW.blocked_reason("https://u:p@93.184.216.34/"))
    assert run(SW.blocked_reason("https://93.184.216.34/")) is None
    monkeypatch.setenv("SOURCE_WATCH_ALLOW_PRIVATE_TARGETS", "1")
    assert run(SW.blocked_reason("http://127.0.0.1/x")) is None


def test_allowlist_covers_subdomains_only():
    assert SW.host_allowed("eur-lex.europa.eu", ["europa.eu"])
    assert SW.host_allowed("europa.eu", ["europa.eu"])
    assert not SW.host_allowed("evil-europa.eu", ["europa.eu"])
    assert SW.host_allowed("anything.test", [])
    assert "allowlist" in asyncio.run(
        SW.blocked_reason("https://93.184.216.34/", ["europa.eu"])
    )
    assert SW.clean_settings({"host_allowlist": ["*.Europa.EU.", "europa.eu"]})[
        "host_allowlist"
    ] == ["europa.eu"]


@pytest.fixture
def no_gap(monkeypatch):
    monkeypatch.setenv("SOURCE_WATCH_HOST_INTERVAL_SECONDS", "0")
    monkeypatch.delenv("SOURCE_WATCH_ALLOW_PRIVATE_TARGETS", raising=False)


def test_redirect_to_private_address_is_blocked(no_gap):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8080/admin"})

    res = asyncio.run(
        SW.fetch("https://93.184.216.34/start", transport=httpx.MockTransport(handler))
    )
    assert not res.ok and res.blocked and "private" in res.error


def test_conditional_request_and_not_modified(no_gap):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(req.headers)
        return httpx.Response(304, headers={"etag": '"v1"'})

    res = asyncio.run(
        SW.fetch(
            "https://93.184.216.34/doc",
            etag='"v1"',
            last_modified="Mon, 05 Oct 2026 10:00:00 GMT",
            transport=httpx.MockTransport(handler),
        )
    )
    assert res.ok and res.not_modified
    assert seen["if-none-match"] == '"v1"'
    assert seen["if-modified-since"].startswith("Mon, 05 Oct")
    assert seen["user-agent"].startswith("Abenix-SourceWatch")


def test_size_cap_and_http_errors(no_gap, monkeypatch):
    monkeypatch.setenv("SOURCE_WATCH_MAX_BYTES", "2048")
    big = httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 5000))
    res = asyncio.run(SW.fetch("https://93.184.216.34/big", transport=big))
    assert not res.ok and "limit" in res.error
    gone = httpx.MockTransport(lambda r: httpx.Response(404))
    res = asyncio.run(SW.fetch("https://93.184.216.34/gone", transport=gone))
    assert not res.ok and res.status == 404 and "404" in res.error


def test_sign_in_header_stays_on_the_source_host(no_gap):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.url.host, req.headers.get("authorization")))
        if req.url.host == "93.184.216.34":
            return httpx.Response(302, headers={"location": "https://93.184.216.35/x"})
        return httpx.Response(
            200, content=b"ok", headers={"content-type": "text/plain"}
        )

    res = asyncio.run(
        SW.fetch(
            "https://93.184.216.34/a",
            secret_headers={"Authorization": "Bearer s3cret"},
            transport=httpx.MockTransport(handler),
        )
    )
    assert res.ok and res.body == b"ok"
    assert calls == [("93.184.216.34", "Bearer s3cret"), ("93.184.216.35", None)]


def test_credential_keys_are_restricted():
    with pytest.raises(SW.SourceError):
        asyncio.run(SW.credential_headers(TENANT, "DATABASE_URL"))
    assert asyncio.run(SW.credential_headers(TENANT, None)) == {}


def test_due_claim_skips_locked_rows():
    sql = str(
        SW.due_claim_stmt(datetime.now(timezone.utc)).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "watch_sources.active IS true" in sql


# Recording outcomes against a stand-in session


class FakeDB:
    def __init__(self) -> None:
        self.snapshots: dict[uuid.UUID, SourceSnapshot] = {}
        self.changes: list[SourceChange] = []

    async def get(self, model, key):
        return self.snapshots.get(key) if model is SourceSnapshot else None

    async def execute(self, stmt):
        params = stmt.compile().params
        sha = next(
            (v for k, v in params.items() if k.startswith("content_sha256")), None
        )
        sid = next((v for k, v in params.items() if k.startswith("source_id")), None)
        hit = next(
            (
                p
                for p in self.snapshots.values()
                if p.content_sha256 == sha and p.source_id == sid
            ),
            None,
        )
        return SimpleNamespace(scalar_one_or_none=lambda: hit)

    def add(self, obj):
        if isinstance(obj, SourceSnapshot):
            self.snapshots[obj.id] = obj
        elif isinstance(obj, SourceChange):
            self.changes.append(obj)

    async def flush(self):
        return None


def _source(kind="html"):
    return WatchSource(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        name="Carrier tariff page",
        url="https://example.test/tariff",
        kind=kind,
        cadence_minutes=60,
        active=True,
        headers={},
        tags=["tariff"],
        risk_tier="high",
        consecutive_failures=0,
        check_count=0,
    )


def _prep(body: bytes, kind="html", ctype="text/html") -> SW.Prepared:
    norm = N.normalize(kind, body, ctype)
    res = SW.FetchResult(
        ok=True,
        status=200,
        body=body,
        content_type=ctype,
        final_url="https://example.test/tariff",
        headers={"etag": '"e"'},
    )
    return SW.Prepared(
        fetch=res, sha=D.sha256(body), text_sha=D.sha256(norm.text), normalized=norm
    )


def _record(db, src, prep, emit, pause=5):
    return asyncio.run(
        SW.record(db, src, prep, {"pause_after_failures": pause}, emit=emit)
    )


def test_change_detection_is_idempotent_and_emits_once():
    db, src, emit = FakeDB(), _source(), AsyncMock()
    v1 = PAGE
    v2 = PAGE.replace(b"every quarter", b"every month")

    out = _record(db, src, _prep(v1), emit)
    assert out["status"] == "baseline" and len(db.snapshots) == 1
    emit.assert_not_awaited()
    assert src.etag == '"e"'

    assert _record(db, src, _prep(v1), emit)["status"] == "unchanged"
    noisy = v1.replace(b"abc123", b"other-nonce")
    noise = _record(db, src, _prep(noisy), emit)
    assert noise["status"] == "unchanged" and "readable content" in noise["note"]
    assert len(db.snapshots) == 1 and not db.changes
    emit.assert_not_awaited()

    out = _record(db, src, _prep(v2), emit)
    assert out["status"] == "changed" and len(db.changes) == 1
    assert (
        src.last_changed_at is not None
        and src.current_snapshot_id == db.changes[0].to_snapshot_id
    )
    emit.assert_awaited_once()
    _db, tenant, event, payload = emit.await_args.args
    assert event == "source.changed" and tenant == TENANT
    assert (
        payload["change_id"] == out["change_id"]
        and payload["name"] == "Carrier tariff page"
    )
    assert "every month" in json.dumps(db.changes[0].diff)

    assert _record(db, src, _prep(v2), emit)["status"] == "unchanged"
    assert emit.await_count == 1

    back = _record(db, src, _prep(v1), emit)
    assert back["status"] == "changed" and not back.get("snapshot_created")
    assert len(db.snapshots) == 2 and len(db.changes) == 2


def test_table_sources_record_row_deltas():
    db, src, emit = FakeDB(), _source("csv"), AsyncMock()
    _record(db, src, _prep(b"code,rate\n1,5\n2,6\n", "csv", "text/csv"), emit)
    out = _record(db, src, _prep(b"code,rate\n1,5\n2,7\n", "csv", "text/csv"), emit)
    assert out["status"] == "changed"
    assert db.changes[0].diff["kind"] == "table"
    assert db.changes[0].diff["sheets"][0]["changed"][0]["key"] == "2"


def test_failures_pause_the_source_after_the_limit():
    db, src, emit = FakeDB(), _source(), AsyncMock()
    for i in range(1, 3):
        out = _record(
            db, src, SW.Prepared(error="The site answered HTTP 500."), emit, pause=3
        )
        assert out["consecutive_failures"] == i and src.active
    out = _record(
        db, src, SW.Prepared(error="The site answered HTTP 500."), emit, pause=3
    )
    assert out["paused"] and not src.active
    assert "3 failed checks" in src.paused_reason and src.last_status == "error"


def test_platform_faults_do_not_count_toward_pausing():
    db, src, emit = FakeDB(), _source(), AsyncMock()
    for _ in range(4):
        _record(
            db,
            src,
            SW.Prepared(error="storage down", platform_error=True),
            emit,
            pause=2,
        )
    assert src.active and src.consecutive_failures == 0


def test_success_resets_failures():
    db, src, emit = FakeDB(), _source(), AsyncMock()
    _record(db, src, SW.Prepared(error="boom"), emit)
    assert src.consecutive_failures == 1
    _record(db, src, _prep(PAGE), emit)
    assert src.consecutive_failures == 0 and src.last_error is None


class _Factory:
    def __init__(self, src):
        self.src = src
        self.commits = 0

    def __call__(self):
        outer = self

        class _S:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, model, key):
                return outer.src if model is WatchSource else None

            async def commit(self):
                outer.commits += 1

        return _S()


def test_kill_switch_skips_the_source():
    src = _source()
    governance.load_for_test(
        switches=[(str(TENANT), "source", str(src.id), "vendor asked us to stop")]
    )
    try:
        with patch.object(SW, "prepare", AsyncMock()) as prep:
            out = asyncio.run(SW.check_source(src.id, session_factory=_Factory(src)))
        assert out["status"] == "stopped" and "vendor asked" in out["error"]
        prep.assert_not_awaited()
        assert src.last_status == "stopped"
    finally:
        governance.load_for_test()


def test_paused_source_is_skipped_unless_manual():
    src = _source()
    src.active = False
    governance.load_for_test()
    with patch.object(SW, "prepare", AsyncMock()) as prep:
        out = asyncio.run(SW.check_source(src.id, session_factory=_Factory(src)))
    assert out["status"] == "paused"
    prep.assert_not_awaited()


def test_kb_text_carries_the_citation():
    src = _source()
    snap = SourceSnapshot(
        id=uuid.uuid4(),
        url="https://example.test/tariff",
        content_sha256="ab" * 32,
        fetched_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        title="T",
        normalized_text="Body",
    )
    t = SW.kb_text(src, snap)
    assert (
        "URL: https://example.test/tariff" in t
        and str(snap.id) in t
        and t.endswith("Body")
    )


def test_migration_makes_snapshots_immutable():
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2]
        / "packages/db/alembic/versions/25f2dd065d53_source_watch.py"
    ).read_text(encoding="utf-8")
    assert "BEFORE UPDATE ON source_snapshots" in src
    assert "uq_source_snapshot_sha" in src
