"""Builds the supplier risk zips from the folder next to it. Deterministic.

supplier_risk.zip         the scorer, v1
supplier_risk_v2.zip      the same scorer reporting V2
supplier_risk_broken.zip  a README and nothing to run
supplier_risk_raises.zip  a script that always fails
"""

import zipfile
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "supplier_risk"


def write(out: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(f"supplier_risk/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, files[name])
    print(out)


v1 = {f.name: f.read_bytes() for f in sorted(SRC.iterdir())}
write(HERE / "supplier_risk.zip", v1)

v2 = dict(v1)
v2["main.py"] = v1["main.py"].replace(b"SUPPLIER_RISK_ENGINE_V1", b"SUPPLIER_RISK_ENGINE_V2")
write(HERE / "supplier_risk_v2.zip", v2)

write(HERE / "supplier_risk_broken.zip", {"NOTES.txt": b"Scoring notes, no code yet.\n"})

raises = dict(v1)
raises["main.py"] = (
    b"import json, sys\n"
    b"data = json.load(sys.stdin)\n"
    b"raise ValueError('supplier list is missing the debt_to_equity column')\n"
)
write(HERE / "supplier_risk_raises.zip", raises)
