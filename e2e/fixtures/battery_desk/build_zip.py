"""Rebuild battery_dispatch.zip from the battery_dispatch folder."""

import pathlib
import zipfile

here = pathlib.Path(__file__).parent
with zipfile.ZipFile(here / "battery_dispatch.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted((here / "battery_dispatch").rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts:
            z.write(f, f.relative_to(here).as_posix())
