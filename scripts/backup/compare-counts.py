#!/usr/bin/env python3
"""Compare two row count listings, a table is reported when the counts differ."""

from __future__ import annotations

import sys


def load(path: str) -> dict[str, int]:
    out: dict[str, int] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            name, _, value = line.strip().partition("|")
            if name and value.isdigit():
                out[name] = int(value)
    return out


def main() -> int:
    source, restored = load(sys.argv[1]), load(sys.argv[2])
    drift = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    bad = 0
    for name in sorted(set(source) | set(restored)):
        a, b = source.get(name), restored.get(name)
        if a == b:
            continue
        allowed = (
            a is not None and b is not None and abs(a - b) <= max(a, b) * drift / 100
        )
        print(f"{'drift' if allowed else 'MISMATCH'} {name} source={a} restored={b}")
        bad += 0 if allowed else 1
    print(
        f"compared {len(source)} tables, {sum(source.values())} rows, {bad} mismatches"
    )
    if not source:
        print("MISMATCH the source listing is empty")
        return 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
