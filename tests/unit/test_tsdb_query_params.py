"""tsdb_query must bind real datetimes, not ISO strings.

asyncpg binds parameters before the `::timestamptz` cast in the SQL runs, so a
plain string is rejected outright and every call failed with "expected a
datetime.date or datetime.datetime instance, got 'str'". Two earlier faults
(a wrong env var name, then a missing hypertable) masked this one.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "apps" / "agent-runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from engine.tools.tsdb_query import TsdbQueryTool, _parse_ts  # noqa: E402


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-01-01T00:00:00Z", datetime(2026, 1, 1, tzinfo=timezone.utc)),
        ("2026-01-01 00:00:00", datetime(2026, 1, 1, tzinfo=timezone.utc)),
        ("2026-01-01", datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ],
)
def test_parse_ts_returns_aware_datetime(raw: str, expected: datetime) -> None:
    got = _parse_ts(raw)
    assert isinstance(got, datetime), f"{raw} did not parse to a datetime"
    assert got.tzinfo is not None, "asyncpg needs an aware datetime for timestamptz"
    assert got == expected


def test_parse_ts_keeps_explicit_offset() -> None:
    got = _parse_ts("2026-01-01T00:00:00+02:00")
    assert got is not None
    assert got.utcoffset() is not None
    assert got.utcoffset().total_seconds() == 7200


@pytest.mark.parametrize("raw", ["", "   ", "garbage", "2026-13-45"])
def test_parse_ts_rejects_junk(raw: str) -> None:
    assert _parse_ts(raw) is None


@pytest.mark.asyncio
async def test_execute_rejects_unparseable_since(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad timestamp must be a clear tool error, not an asyncpg type crash."""
    monkeypatch.setenv("TSDB_URL", "postgresql://unused:unused@127.0.0.1:1/none")
    tool = TsdbQueryTool()
    result = await tool.execute({"metric": "vibration_rms", "since": "not-a-date"})
    assert result.is_error
    assert "ISO-8601" in result.content


@pytest.mark.asyncio
async def test_execute_requires_metric() -> None:
    tool = TsdbQueryTool()
    result = await tool.execute({"since": "2026-01-01T00:00:00Z"})
    assert result.is_error
    assert "metric is required" in result.content
