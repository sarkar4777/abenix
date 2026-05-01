#!/usr/bin/env python3
"""Generate the binary UAT fixtures (test PDF + Python project zip).

Run from repo root::

    python e2e/fixtures/build.py

Re-run is idempotent — it overwrites the outputs and never adds noise.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

# ─── PDF ──────────────────────────────────────────────────────────────
# Hand-rolled single-page PDF using only stdlib. Contains the marker
# phrase "QUANTUM_GIGAFACTORY_UAT_MARKER" so the retrieval-search test
# can assert the document was actually cognified + indexed.
PDF_TEXT = (
    "Abenix UAT test document.\\n"
    "QUANTUM_GIGAFACTORY_UAT_MARKER appears in this document.\\n"
    "It is used for end-to-end Knowledge Base retrieval verification.\\n"
)


def _pdf_object(num: int, body: bytes) -> bytes:
    return f"{num} 0 obj\n".encode() + body + b"\nendobj\n"


def build_pdf() -> bytes:
    # 4-object PDF: catalog, pages, page, content stream + font.
    stream = (
        f"BT /F1 12 Tf 50 750 Td ({PDF_TEXT}) Tj ET".encode("latin-1")
    )
    content = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            b" /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        content,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(_pdf_object(i, body))
    xref_offset = out.tell()
    out.write(b"xref\n0 " + str(len(objects) + 1).encode() + b"\n")
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode()
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode()
        + b"\n%%EOF"
    )
    return out.getvalue()


# ─── Python project zip ───────────────────────────────────────────────
PYTHON_MAIN = """\
\"\"\"Abenix Code Runner UAT fixture.

Reads a JSON object {\"a\": int, \"b\": int} from stdin, returns
{\"sum\": a + b}.  Has no external deps — runs on the default Python
sandbox image without a requirements step.
\"\"\"
import json
import sys


def add(a: int, b: int) -> int:
    return a + b


def main() -> None:
    raw = sys.stdin.read().strip() or '{\"a\": 0, \"b\": 0}'
    payload = json.loads(raw)
    result = {\"sum\": add(int(payload.get(\"a\", 0)), int(payload.get(\"b\", 0)))}
    sys.stdout.write(json.dumps(result))


if __name__ == \"__main__\":
    main()
"""

PYTHON_README = """\
# UAT add-server

Tiny Python project used by the Abenix Code Runner UAT.

* `python main.py` reads `{ \"a\": <int>, \"b\": <int> }` on stdin.
* Emits `{ \"sum\": <int> }` on stdout.
"""


def build_zip() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("uat_add/main.py", PYTHON_MAIN)
        zf.writestr("uat_add/README.md", PYTHON_README)
    return out.getvalue()


# ─── ML model stub ────────────────────────────────────────────────────
# Tiny pickled identity-function model — not a real model artifact, but
# a valid binary the upload endpoint will accept. We are testing the UI
# pipeline (register → list → page renders), not inference correctness.
def build_model() -> bytes:
    """Use a stdlib-friendly pickled object — a dict is enough for the
    UAT to verify the upload flow end-to-end."""
    import pickle
    return pickle.dumps({"name": "uat-identity-model", "version": "0.1", "weights": [1.0, 2.0, 3.0]})


# ─── Main ─────────────────────────────────────────────────────────────
def main() -> int:
    pdf_path = OUT_DIR / "uat_kb_doc.pdf"
    zip_path = OUT_DIR / "uat_python_app.zip"
    pkl_path = OUT_DIR / "uat_ml_model.pkl"

    pdf_path.write_bytes(build_pdf())
    zip_path.write_bytes(build_zip())
    pkl_path.write_bytes(build_model())

    print(f"  wrote {pdf_path.relative_to(OUT_DIR.parent.parent)} ({pdf_path.stat().st_size}B)")
    print(f"  wrote {zip_path.relative_to(OUT_DIR.parent.parent)} ({zip_path.stat().st_size}B)")
    print(f"  wrote {pkl_path.relative_to(OUT_DIR.parent.parent)} ({pkl_path.stat().st_size}B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
