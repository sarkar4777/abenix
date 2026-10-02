"""Fold release notes into the changelog section of an existing version.

Used by publish-public.sh for a follow-on publish (BUMP=none), so a fix that
lands after the tag joins that version's section instead of adding another
heading for the same version.

    python scripts/merge-changelog.py CHANGELOG.md v2.5.1 2026-10-02 notes.md

Bullets already in the section are skipped, new ones join their ### group,
and a group the section lacks is added at its end.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def groups(text: str) -> dict[str, list[str]]:
    """Items per ### group. An item is a bullet with its indented or prose continuation."""
    out: dict[str, list[str]] = {"": []}
    current = ""
    item: list[str] | None = None

    def flush() -> None:
        nonlocal item
        if item:
            out[current].append("\n".join(item).rstrip())
        item = None

    for line in text.splitlines():
        if line.startswith("## "):
            continue
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            flush()
            current = m.group(1)
            out.setdefault(current, [])
        elif line.startswith("- "):
            flush()
            item = [line.rstrip()]
        elif line.strip():
            if item is None:
                item = [line.rstrip()]
            else:
                item.append(line.rstrip())
        elif item is not None and not line.startswith(" "):
            # a blank line ends a prose item but not a bullet's indented block
            if not item[0].startswith("- "):
                flush()
    flush()
    return out


def main() -> int:
    path, version, date, notes_path = sys.argv[1:5]
    raw = Path(notes_path).read_text(encoding="utf-8")
    return _merge(path, version, date, raw)


def _merge(path: str, version: str, date: str, raw: str) -> int:
    notes = groups(re.sub(r"<!--.*?-->", "", raw, flags=re.S))
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    heading = re.compile(rf"^## {re.escape(version)}\b")
    starts = [i for i, ln in enumerate(lines) if heading.match(ln)]
    if not starts:
        # no section for this version yet, prepend one
        body = []
        for g, bullets in notes.items():
            if bullets:
                body += ([f"### {g}", ""] if g else []) + [*bullets, ""]
        head = lines[:2] if lines and lines[0].startswith("# ") else ["# Changelog", ""]
        rest = lines[2:] if head is not lines else lines
        Path(path).write_text("\n".join([*head, f"## {version} — {date}", "", *body, *rest]) + "\n", encoding="utf-8")
        return 0
    # sections of the same version beyond the first are earlier duplicates, fold them in
    first = starts[0]
    end = next((i for i in range(first + 1, len(lines)) if lines[i].startswith("## ") and not heading.match(lines[i])), len(lines))
    section = lines[first:end]
    merged: dict[str, list[str]] = {}
    order: list[str] = []
    for g, bullets in groups("\n".join(section)).items():
        order.append(g)
        merged[g] = list(dict.fromkeys(bullets))
    for g, bullets in notes.items():
        if g not in merged:
            order.append(g)
            merged[g] = []
        for b in bullets:
            if b not in merged[g]:
                merged[g].append(b)
    body = [section[0], ""]
    for g in order:
        if not merged[g]:
            continue
        if g:
            body += [f"### {g}", ""]
        body += [*merged[g], ""]
    out = [*lines[:first], *body, *lines[end:]]
    Path(path).write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    return 0


def fold_all(path: str) -> None:
    """Fold every version that appears under more than one heading."""
    text = Path(path).read_text(encoding="utf-8")
    seen: list[str] = []
    for v in re.findall(r"^## (v[\d.]+)", text, re.M):
        if v not in seen:
            seen.append(v)
    for v in seen:
        _merge(path, v, "", "")


if __name__ == "__main__":
    code = main()
    if code == 0:
        fold_all(sys.argv[1])
    sys.exit(code)
