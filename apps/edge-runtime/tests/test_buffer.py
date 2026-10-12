"""Store-and-forward: order, exact retries, limits and restarts."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from abenix_edge.buffer import Buffer, Reading, now_ms  # noqa: E402


def _r(subject: str, i: int, ts: int | None = None) -> Reading:
    return Reading(subject, "Seq", i, ts if ts is not None else now_ms() + i)


def test_oldest_first_per_subject_and_ack(tmp_path: Path) -> None:
    b = Buffer(tmp_path / "b.db", gateway_id="gw1")
    for i in range(5):
        b.add(_r("site/a/x", i))
        b.add(_r("site/b/y", i))
        b.flush()
    assert b.stats()["depth"] == 10
    first = b.next_batch()
    assert first is not None and first.subject == "site/a/x"
    assert [v["value"] for v in first.values] == [0, 1, 2, 3, 4]
    b.ack(first)
    second = b.next_batch()
    assert second.subject == "site/b/y"
    b.ack(second)
    assert b.next_batch() is None
    st = b.stats()
    assert st["depth"] == 0 and st["sent"] == 10 and st["written"] == 10


def test_retry_resends_the_same_batch_under_the_same_key(tmp_path: Path) -> None:
    b = Buffer(tmp_path / "b.db", gateway_id="gw1")
    b.add_many([_r("s/n/d", i) for i in range(3)])
    b.flush()
    one = b.next_batch()
    # more readings arrive while the first send is unanswered
    b.add_many([_r("s/n/d", i) for i in range(3, 6)])
    b.flush()
    again = b.next_batch()
    assert again.key == one.key and again.seqs == one.seqs
    assert [v["value"] for v in again.values] == [0, 1, 2]


def test_inflight_survives_a_restart(tmp_path: Path) -> None:
    b = Buffer(tmp_path / "b.db", gateway_id="gw1")
    b.add_many([_r("s/n/d", i) for i in range(4)])
    b.flush()
    one = b.next_batch()
    b.close()
    b2 = Buffer(tmp_path / "b.db", gateway_id="gw1")
    assert b2.epoch == b.epoch
    again = b2.next_batch()
    assert again.key == one.key
    assert len(again.values) == 4


def test_a_new_file_gets_a_new_epoch(tmp_path: Path) -> None:
    a = Buffer(tmp_path / "a.db", gateway_id="gw1")
    c = Buffer(tmp_path / "c.db", gateway_id="gw1")
    a.add(_r("s/n/d", 1))
    c.add(_r("s/n/d", 1))
    a.flush()
    c.flush()
    assert a.next_batch().key != c.next_batch().key


def test_age_limit_drops_old_readings(tmp_path: Path) -> None:
    b = Buffer(tmp_path / "b.db", gateway_id="gw1", max_age_s=60)
    old = now_ms() - 3600_000
    b.add_many([_r("s/n/d", i, old + i) for i in range(10)])
    b.flush()
    b.add(_r("s/n/d", 99))
    b.flush()
    st = b.stats()
    assert st["dropped_age"] == 10
    assert st["depth"] == 1


def test_size_limit_drops_the_oldest(tmp_path: Path) -> None:
    b = Buffer(tmp_path / "b.db", gateway_id="gw1", max_bytes=4000)
    import random

    for k in range(30):
        b.add_many(
            [
                Reading("s/n/d", f"x{i}", random.random(), now_ms() + i)
                for i in range(50)
            ]
        )
        b.flush()
    st = b.stats()
    assert st["bytes"] <= 4000
    assert st["dropped_size"] > 0
    # what is left is the newest
    batch = b.next_batch(max_values=100000, max_bytes=10_000_000)
    assert batch.seqs[-1] == 30


def test_batches_respect_value_and_byte_caps(tmp_path: Path) -> None:
    b = Buffer(tmp_path / "b.db", gateway_id="gw1")
    for k in range(10):
        b.add_many([_r("s/n/d", k * 100 + i) for i in range(100)])
        b.flush()
    batch = b.next_batch(max_values=350)
    assert len(batch.values) == 300
    assert len(batch.body()) < 900_000


def test_split_a_too_large_batch(tmp_path: Path) -> None:
    b = Buffer(tmp_path / "b.db", gateway_id="gw1")
    for k in range(3):
        b.add_many([_r("s/n/d", k * 10 + i) for i in range(10)])
        b.flush()
    batch = b.next_batch()
    assert len(batch.seqs) == 3
    assert b.split(batch)
    one = b.next_batch()
    assert one.seqs == batch.seqs[:1]
    assert b.split(one)
    half = b.next_batch()
    assert len(half.values) == 5 and [v["value"] for v in half.values] == [
        0,
        1,
        2,
        3,
        4,
    ]
    b.ack(half)
    nxt = b.next_batch()
    assert [v["value"] for v in nxt.values][:5] == [5, 6, 7, 8, 9]


def test_reject_counts_and_drops(tmp_path: Path) -> None:
    b = Buffer(tmp_path / "b.db", gateway_id="gw1")
    b.add(_r("s/n/d", 1))
    b.flush()
    b.reject(b.next_batch())
    assert b.stats()["rejected"] == 1
    assert b.next_batch() is None


def test_compression_keeps_the_file_small(tmp_path: Path) -> None:
    b = Buffer(tmp_path / "b.db", gateway_id="gw1")
    t = now_ms()
    b.add_many(
        [
            Reading("s/n/d", "Engine/Speed_rpm", 1500.0, t + i * 1000, "rpm")
            for i in range(2000)
        ]
    )
    b.flush()
    raw = 2000 * len(
        '{"name":"Engine/Speed_rpm","value":1500.0,"ts":1791720000000,"quality":"good","unit":"rpm"},'
    )
    assert b.stats()["bytes"] < raw / 10
    time.sleep(0)
