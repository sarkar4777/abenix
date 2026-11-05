"""Duplicate candidates without comparing every pair.

Names go to a temporary SQLite file. Each one then gets blocking keys, its sorted
token key and its rarest character trigrams across the corpus. Blocks are read in
sorted order with a fixed comparison window, so memory stays flat and the work grows
with n times the window.
"""

from __future__ import annotations

import os
import re
import sqlite3
import tempfile
import unicodedata
import zlib
from array import array
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from difflib import SequenceMatcher

WINDOW = 24
SKETCH_SIZE = 4
DEFAULT_THRESHOLD = 0.85
MIN_JACCARD = 0.55
MAX_GROUP_SIZE = 25

_DIGITS = re.compile(r"\d+")
_NON_WORD = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE = re.compile(r"\s+")


def name_key(name: str | None) -> str:
    """Casefolded, accents and punctuation removed, spaces collapsed."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    text = _NON_WORD.sub(" ", text.replace("_", " "))
    return _SPACE.sub(" ", text).strip()


def char_ngrams(key: str, n: int = 3) -> set[str]:
    padded = f" {key} "
    if len(padded) <= n:
        return {padded}
    return {padded[i : i + n] for i in range(len(padded) - n + 1)}


def _hash(value: str) -> int:
    return zlib.crc32(value.encode("utf-8", "ignore"))


class GramCounts:
    """How common each trigram is, in a fixed size table whatever the corpus."""

    def __init__(self, bits: int = 20) -> None:
        self.mask = (1 << bits) - 1
        self.table = array("I", [0]) * (1 << bits)

    def add(self, key: str) -> None:
        for gram in char_ngrams(key):
            self.table[_hash(gram) & self.mask] += 1

    def rarest(self, key: str, k: int = SKETCH_SIZE) -> list[int]:
        # a trigram only this name has cannot bring it together with another name
        hashed = [
            h for h in map(_hash, char_ngrams(key)) if self.table[h & self.mask] > 1
        ]
        hashed.sort(key=lambda h: (self.table[h & self.mask], h))
        return hashed[:k]


def blocking_keys(entity_type: str, key: str, counts: GramCounts) -> list[int]:
    """Integer block ids. Two names only meet if they share one of these."""
    salt = _hash(f"{entity_type}|")
    tokens = " ".join(sorted(key.split(" ")))
    keys = {(_hash(f"t{tokens}") * 2654435761 ^ salt) & 0x7FFFFFFFFFFFFFFF}
    keys.update(
        ((h * 40503 + 1) ^ salt) & 0x7FFFFFFFFFFFFFFF for h in counts.rarest(key)
    )
    return list(keys)


@dataclass(slots=True)
class _Seen:
    name_id: int
    key: str
    grams: frozenset[str]
    digits: tuple[str, ...]
    tokens: tuple[str, ...]


def _seen(name_id: int, key: str) -> _Seen:
    return _Seen(
        name_id,
        key,
        frozenset(char_ngrams(key)),
        tuple(_DIGITS.findall(key)),
        tuple(sorted(key.split(" "))),
    )


def _close(a: _Seen, b: _Seen, threshold: float) -> bool:
    if a.key == b.key or a.tokens == b.tokens:
        return True
    # Project 12 and Project 13 read alike but are different things
    if a.digits != b.digits:
        return False
    shared = len(a.grams & b.grams)
    if shared / max(len(a.grams) + len(b.grams) - shared, 1) < MIN_JACCARD * threshold:
        return False
    return SequenceMatcher(None, a.key, b.key, autojunk=False).ratio() >= threshold


def similar(a: str, b: str, threshold: float = DEFAULT_THRESHOLD) -> bool:
    return _close(_seen(0, a), _seen(0, b), threshold)


@dataclass
class BlockingStats:
    names: int = 0
    block_rows: int = 0
    comparisons: int = 0
    matched_pairs: int = 0
    groups: int = 0
    disk_bytes: int = 0
    truncated: bool = False


@dataclass
class CandidateGroup:
    entity_type: str
    names: list[str] = field(default_factory=list)
    exact: bool = False


class _Union:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        parent = self.parent
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


class NameBlocker:
    """Feed pages of (name, type), then read candidate groups. Close removes the file."""

    def __init__(
        self,
        threshold: float = DEFAULT_THRESHOLD,
        window: int = WINDOW,
        max_groups: int = 50000,
        directory: str | None = None,
    ) -> None:
        self.threshold = threshold
        self.window = window
        self.max_groups = max_groups
        self.stats = BlockingStats()
        fd, self.path = tempfile.mkstemp(suffix=".blocks", dir=directory)
        os.close(fd)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        for pragma in (
            "PRAGMA journal_mode=OFF",
            "PRAGMA synchronous=OFF",
            "PRAGMA temp_store=FILE",
            "PRAGMA cache_size=-32000",
        ):
            self.db.execute(pragma)
        self.db.execute(
            "CREATE TABLE names (id INTEGER PRIMARY KEY, name TEXT, type TEXT, key TEXT)"
        )
        self.db.execute("CREATE TABLE blocks (block INTEGER, name_id INTEGER)")
        self.counts = GramCounts()

    def add(self, page: Iterable[tuple[str, str]]) -> None:
        names = []
        next_id = self.stats.names
        for name, entity_type in page:
            key = name_key(name)
            if not key:
                continue
            next_id += 1
            names.append((next_id, name, entity_type, key))
            self.counts.add(key)
        self.db.executemany("INSERT INTO names VALUES (?, ?, ?, ?)", names)
        self.db.commit()
        self.stats.names = next_id

    def _build_blocks(self) -> None:
        """A second pass, rarity is only known once every name has been seen."""
        reader = self.db.cursor()
        writer = self.db.cursor()
        reader.execute("SELECT id, type, key FROM names")
        while rows := reader.fetchmany(5000):
            blocks = [
                (b, name_id)
                for name_id, entity_type, key in rows
                for b in blocking_keys(entity_type, key, self.counts)
            ]
            writer.executemany("INSERT INTO blocks VALUES (?, ?)", blocks)
            self.stats.block_rows += len(blocks)
        self.db.commit()

    def _rows(self) -> Iterator[tuple[int, int, str, str]]:
        return self.db.execute(
            "SELECT b.block, b.name_id, n.key, n.type FROM blocks b "
            "JOIN names n ON n.id = b.name_id ORDER BY b.block, n.key"
        )

    def groups(self) -> list[CandidateGroup]:
        self._build_blocks()
        union = _Union()
        exact = _Union()
        recent: deque[_Seen] = deque(maxlen=self.window)
        block = None
        stats = self.stats
        for row_block, name_id, key, _type in self._rows():
            if row_block != block:
                block = row_block
                recent.clear()
            current = _seen(name_id, key)
            for other in recent:
                if other.name_id == name_id:
                    continue
                stats.comparisons += 1
                if current.tokens == other.tokens:
                    if exact.find(other.name_id) != exact.find(name_id):
                        stats.matched_pairs += 1
                        exact.union(other.name_id, name_id)
                elif _close(current, other, self.threshold):
                    if union.find(other.name_id) != union.find(name_id):
                        stats.matched_pairs += 1
                        union.union(other.name_id, name_id)
            recent.append(current)
            if stats.matched_pairs >= self.max_groups * 8:
                stats.truncated = True
                break
        out: list[CandidateGroup] = []
        for merged in (exact, union):
            by_root: dict[int, list[int]] = {}
            for member in list(merged.parent):
                by_root.setdefault(merged.find(member), []).append(member)
            self._materialise(by_root, merged is exact, out)
        self.stats.groups = len(out)
        self.stats.disk_bytes = os.path.getsize(self.path)
        return out

    def _materialise(
        self,
        by_root: dict[int, list[int]],
        is_exact: bool,
        out: list[CandidateGroup],
    ) -> None:
        for members in by_root.values():
            if len(members) < 2:
                continue
            members = sorted(members)[:MAX_GROUP_SIZE]
            marks = ",".join("?" * len(members))
            rows = self.db.execute(
                f"SELECT name, type, key FROM names WHERE id IN ({marks})", members
            ).fetchall()
            out.append(
                CandidateGroup(
                    entity_type=rows[0][1],
                    names=[r[0] for r in rows],
                    exact=is_exact,
                )
            )
            if len(out) >= self.max_groups:
                self.stats.truncated = True
                return

    def close(self) -> None:
        try:
            self.db.close()
        finally:
            for suffix in ("", "-journal", "-wal", "-shm"):
                try:
                    os.unlink(self.path + suffix)
                except OSError:
                    pass


def candidate_groups(
    rows: Iterable[tuple[str, str]],
    threshold: float = DEFAULT_THRESHOLD,
    window: int = WINDOW,
) -> list[CandidateGroup]:
    blocker = NameBlocker(threshold=threshold, window=window)
    try:
        blocker.add(rows)
        return blocker.groups()
    finally:
        blocker.close()
