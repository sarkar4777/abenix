"""Date arithmetic, business day calculations, contract term computations."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from engine.tools.base import BaseTool, ToolResult

US_HOLIDAYS_FIXED = [
    (1, 1),  # New Year's Day
    (6, 19),  # Juneteenth
    (7, 4),  # Independence Day
    (11, 11),  # Veterans Day
    (12, 25),  # Christmas
]


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    d = first + timedelta(days=offset + (n - 1) * 7)
    return d


def _us_holidays(year: int) -> set[date]:
    holidays: set[date] = set()

    for m, d in US_HOLIDAYS_FIXED:
        holidays.add(date(year, m, d))

    holidays.add(_nth_weekday(year, 1, 0, 3))  # MLK Day
    holidays.add(_nth_weekday(year, 2, 0, 3))  # Presidents Day
    holidays.add(_nth_weekday(year, 9, 0, 1))  # Labor Day
    holidays.add(_nth_weekday(year, 10, 0, 2))  # Columbus Day
    holidays.add(_nth_weekday(year, 11, 3, 4))  # Thanksgiving

    may_31 = date(year, 5, 31)
    offset = (may_31.weekday() - 0) % 7
    holidays.add(may_31 - timedelta(days=offset))  # Memorial Day

    return holidays


def _is_business_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    holidays = _us_holidays(d.year)
    return d not in holidays


def _add_business_days(start: date, days: int) -> date:
    current = start
    added = 0
    direction = 1 if days >= 0 else -1
    target = abs(days)
    while added < target:
        current += timedelta(days=direction)
        if _is_business_day(current):
            added += 1
    return current


class DateCalculatorTool(BaseTool):
    name = "date_calculator"
    description = (
        "Perform date calculations: add/subtract days/months/years, compute business "
        "days between dates (excluding weekends and US holidays), calculate contract "
        "terms and milestones, find days until deadlines, compute age/duration, "
        "and work with time zones."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "add",
                    "subtract",
                    "difference",
                    "business_days",
                    "business_days_between",
                    "contract_milestones",
                    "days_until",
                    "format",
                ],
                "description": "Date operation to perform",
            },
            "date": {
                "type": "string",
                "description": "Date in YYYY-MM-DD format",
            },
            "second_date": {
                "type": "string",
                "description": "Second date for difference/between operations",
            },
            "days": {
                "type": "integer",
                "description": "Number of days to add/subtract",
            },
            "months": {
                "type": "integer",
                "description": "Number of months to add/subtract",
            },
            "years": {
                "type": "integer",
                "description": "Number of years to add/subtract",
            },
            "business_days": {
                "type": "integer",
                "description": "Number of business days to add",
            },
            "contract_start": {
                "type": "string",
                "description": "Contract start date for milestone calculation",
            },
            "contract_years": {
                "type": "integer",
                "description": "Contract duration in years",
            },
            "timezone": {
                "type": "string",
                "description": "Timezone for formatting (e.g. 'America/New_York')",
            },
        },
        "required": ["operation"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        operation = arguments.get("operation", "")

        ops = {
            "add": self._add,
            "subtract": self._subtract,
            "difference": self._difference,
            "business_days": self._add_business_days,
            "business_days_between": self._business_days_between,
            "contract_milestones": self._contract_milestones,
            "days_until": self._days_until,
            "format": self._format_date,
        }

        fn = ops.get(operation)
        if not fn:
            return ToolResult(content=f"Unknown operation: {operation}", is_error=True)

        try:
            result = fn(arguments)
            output = json.dumps(result, indent=2, default=str)
            return ToolResult(content=output, metadata={"operation": operation})
        except Exception as e:
            return ToolResult(content=f"Date calculation error: {e}", is_error=True)

    def _parse_date(self, date_str: str) -> date:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%B %d, %Y", "%d %B %Y"):
            try:
                return datetime.strptime(date_str.strip(), fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Cannot parse date: {date_str}")

    def _add(self, args: dict[str, Any]) -> dict[str, Any]:
        d = self._parse_date(args.get("date", ""))
        days = args.get("days", 0)
        months = args.get("months", 0)
        years = args.get("years", 0)

        result = self._add_to_date(d, days, months, years)
        return {
            "original_date": d.isoformat(),
            "result_date": result.isoformat(),
            "day_of_week": result.strftime("%A"),
            "added": {"days": days, "months": months, "years": years},
            "is_business_day": _is_business_day(result),
        }

    def _subtract(self, args: dict[str, Any]) -> dict[str, Any]:
        d = self._parse_date(args.get("date", ""))
        days = args.get("days", 0)
        months = args.get("months", 0)
        years = args.get("years", 0)

        result = self._add_to_date(d, -days, -months, -years)
        return {
            "original_date": d.isoformat(),
            "result_date": result.isoformat(),
            "day_of_week": result.strftime("%A"),
            "subtracted": {"days": days, "months": months, "years": years},
            "is_business_day": _is_business_day(result),
        }

    def _add_to_date(self, d: date, days: int, months: int, years: int) -> date:
        new_year = d.year + years + (d.month + months - 1) // 12
        new_month = (d.month + months - 1) % 12 + 1

        import calendar

        max_day = calendar.monthrange(new_year, new_month)[1]
        new_day = min(d.day, max_day)

        result = date(new_year, new_month, new_day)
        result += timedelta(days=days)
        return result

    def _difference(self, args: dict[str, Any]) -> dict[str, Any]:
        d1 = self._parse_date(args.get("date", ""))
        d2 = self._parse_date(args.get("second_date", ""))

        delta = d2 - d1
        total_days = delta.days
        years = abs(total_days) // 365
        remaining = abs(total_days) % 365
        months = remaining // 30
        days = remaining % 30

        return {
            "date_1": d1.isoformat(),
            "date_2": d2.isoformat(),
            "total_days": total_days,
            "calendar_breakdown": {
                "years": years,
                "months": months,
                "days": days,
            },
            "weeks": total_days // 7,
            "total_weeks_decimal": round(total_days / 7, 1),
        }

    def _add_business_days(self, args: dict[str, Any]) -> dict[str, Any]:
        d = self._parse_date(args.get("date", ""))
        bdays = args.get("business_days", 0)

        result = _add_business_days(d, bdays)

        calendar_days = (result - d).days
        return {
            "start_date": d.isoformat(),
            "business_days_added": bdays,
            "result_date": result.isoformat(),
            "day_of_week": result.strftime("%A"),
            "calendar_days_elapsed": calendar_days,
        }

    def _business_days_between(self, args: dict[str, Any]) -> dict[str, Any]:
        d1 = self._parse_date(args.get("date", ""))
        d2 = self._parse_date(args.get("second_date", ""))

        if d1 > d2:
            d1, d2 = d2, d1

        total_calendar = (d2 - d1).days
        bdays = 0
        holidays_hit = 0
        weekends = 0
        current = d1

        while current < d2:
            current += timedelta(days=1)
            if current.weekday() >= 5:
                weekends += 1
            elif current in _us_holidays(current.year):
                holidays_hit += 1
            else:
                bdays += 1

        return {
            "date_1": d1.isoformat(),
            "date_2": d2.isoformat(),
            "business_days": bdays,
            "calendar_days": total_calendar,
            "weekends": weekends,
            "holidays": holidays_hit,
        }

    def _contract_milestones(self, args: dict[str, Any]) -> dict[str, Any]:
        start = self._parse_date(args.get("contract_start", args.get("date", "")))
        years = args.get("contract_years", 10)

        milestones = []
        end = self._add_to_date(start, 0, 0, years)
        midpoint = self._add_to_date(start, 0, 0, years // 2)

        milestones.append(
            {"event": "Contract Start (Execution)", "date": start.isoformat()}
        )

        for q in range(1, 5):
            qdate = self._add_to_date(start, 0, 3 * q, 0)
            milestones.append({"event": f"Q{q} Review", "date": qdate.isoformat()})

        annual_dates = []
        for y in range(1, years + 1):
            anniversary = self._add_to_date(start, 0, 0, y)
            annual_dates.append(anniversary)
            if y <= 5 or y == years or y % 5 == 0:
                milestones.append(
                    {"event": f"Year {y} Anniversary", "date": anniversary.isoformat()}
                )

        milestones.append({"event": "Contract Midpoint", "date": midpoint.isoformat()})

        renewal_notice = self._add_to_date(end, 0, -6, 0)
        milestones.append(
            {
                "event": "Renewal Notice Deadline (6 months before)",
                "date": renewal_notice.isoformat(),
            }
        )
        milestones.append({"event": "Contract End", "date": end.isoformat()})

        today = date.today()
        elapsed = (today - start).days
        total = (end - start).days
        remaining = (end - today).days

        return {
            "contract_start": start.isoformat(),
            "contract_end": end.isoformat(),
            "duration_years": years,
            "total_days": total,
            "elapsed_days": max(0, elapsed),
            "remaining_days": max(0, remaining),
            "pct_complete": (
                round(max(0, min(100, elapsed / total * 100)), 1) if total > 0 else 0
            ),
            "milestones": sorted(milestones, key=lambda m: m["date"]),
        }

    def _days_until(self, args: dict[str, Any]) -> dict[str, Any]:
        target = self._parse_date(args.get("date", ""))
        today = date.today()
        diff = (target - today).days

        return {
            "today": today.isoformat(),
            "target_date": target.isoformat(),
            "days_remaining": diff,
            "weeks_remaining": round(diff / 7, 1),
            "is_past": diff < 0,
            "is_business_day": _is_business_day(target),
            "business_days_remaining": (
                self._count_bdays(today, target) if diff > 0 else 0
            ),
        }

    def _count_bdays(self, start: date, end: date) -> int:
        count = 0
        current = start
        while current < end:
            current += timedelta(days=1)
            if _is_business_day(current):
                count += 1
        return count

    def _format_date(self, args: dict[str, Any]) -> dict[str, Any]:
        d = self._parse_date(args.get("date", ""))
        tz_name = args.get("timezone", "UTC")

        try:
            tz = ZoneInfo(tz_name)
        except (KeyError, ValueError):
            tz = ZoneInfo("UTC")

        datetime(d.year, d.month, d.day, tzinfo=tz)

        return {
            "iso": d.isoformat(),
            "us_format": d.strftime("%m/%d/%Y"),
            "european_format": d.strftime("%d/%m/%Y"),
            "long_format": d.strftime("%B %d, %Y"),
            "day_of_week": d.strftime("%A"),
            "day_of_year": d.timetuple().tm_yday,
            "week_number": d.isocalendar()[1],
            "quarter": (d.month - 1) // 3 + 1,
            "is_leap_year": d.year % 4 == 0
            and (d.year % 100 != 0 or d.year % 400 == 0),
            "is_business_day": _is_business_day(d),
            "timezone": tz_name,
        }
