"""Rebuild spark_desk.zip from the spark_desk folder."""

import pathlib
import zipfile

here = pathlib.Path(__file__).parent
with zipfile.ZipFile(here / "spark_desk.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted((here / "spark_desk").rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts:
            z.write(f, f.relative_to(here).as_posix())
