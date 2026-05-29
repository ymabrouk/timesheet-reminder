"""
validator.py
Applies all timesheet validation rules against the extracted ADO data.
Returns per-employee violation reports grouped by squad.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional
import pandas as pd


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class Violation:
    code: str          # V1–V10
    severity: str      # ERROR | WARNING | INFO
    message: str
    detail: Optional[str] = None

    def icon(self) -> str:
        return {"ERROR": "🔴", "WARNING": "🟡", "INFO": "ℹ️"}.get(self.severity, "•")

    def __str__(self):
        detail = f" — {self.detail}" if self.detail else ""
        return f"{self.icon()} [{self.code}] {self.message}{detail}"


@dataclass
class EmployeeReport:
    name: str
    squad_name: str
    squad_lead: str
    contract: str
    total_basic_hrs: float
    total_incentive_hrs: float
    violations: list[Violation] = field(default_factory=list)

    @property
    def total_hrs(self) -> float:
        return self.total_basic_hrs + self.total_incentive_hrs

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "ERROR")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "WARNING")

    @property
    def is_clean(self) -> bool:
        return not self.violations


# ── Helpers ───────────────────────────────────────────────────────────────────

def _working_days(start: date, end: date) -> list[date]:
    """Return all Mon–Fri dates in [start, end] inclusive."""
    days = []
    current = start
    while current <= end:
        if current.weekday() not in (4, 5):   # skip Fri=4, Sat=5
            days.append(current)
        current += timedelta(days=1)
    return days


def _parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Add a work_date column parsed from Closed Date."""
    df = df.copy()
    df["work_date"] = pd.to_datetime(
        df["Closed Date"], errors="coerce", dayfirst=False
    ).dt.date
    return df


def _employee_rows(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Return rows whose Assigned To display name matches name (partial, case-insensitive)."""
    mask = df["Assigned To"].fillna("").str.contains(name, case=False, regex=False)
    return df[mask].copy()


def _period_bounds(today: date) -> tuple[date, date]:
    """Return (period_start, period_end) for the billing cycle that contains today.
    Each cycle runs from the 25th of one month to the 24th of the next."""
    if today.day >= 25:
        period_start = today.replace(day=25)
        if today.month == 12:
            period_end = date(today.year + 1, 1, 24)
        else:
            period_end = date(today.year, today.month + 1, 24)
    else:
        if today.month == 1:
            period_start = date(today.year - 1, 12, 25)
        else:
            period_start = date(today.year, today.month - 1, 25)
        period_end = today.replace(day=24)
    return period_start, period_end


# ── Validation rules ──────────────────────────────────────────────────────────

def _v1_missing_daily_entry(emp_df: pd.DataFrame, today: date,
                             period_start: date, period_end: date) -> list[Violation]:
    """V1 ERROR — No Completed Work on a working day in the check window."""
    window_end = min(today - timedelta(days=1), period_end)
    if window_end < period_start:
        return []

    days_with_effort = set(
        emp_df[emp_df["Completed Work"].fillna(0) > 0]["work_date"].dropna()
    )
    missing = [
        d for d in _working_days(period_start, window_end)
        if d not in days_with_effort
    ]
    if not missing:
        return []
    dates_str = ", ".join(d.strftime("%d %b") for d in missing[:5])
    extra = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
    return [Violation("V1", "ERROR",
                       f"Missing entries on {len(missing)} working day(s)",
                       f"{dates_str}{extra}")]


def _v2_late_logging(emp_df: pd.DataFrame, period_end: date) -> list[Violation]:
    """V2 ERROR — Task Closed Date is after the 24th (period end)."""
    late = emp_df[
        emp_df["work_date"].apply(lambda d: pd.notna(d) and d > period_end)
    ]
    if late.empty:
        return []
    dates = sorted(d for d in late["work_date"].unique() if pd.notna(d))
    dates_str = ", ".join(d.strftime("%d %b") for d in dates[:3])
    return [Violation("V2", "ERROR",
                       f"{len(late)} task(s) logged after period end ({period_end.strftime('%d %b')})",
                       dates_str)]


def _v3_future_entries(emp_df: pd.DataFrame, today: date) -> list[Violation]:
    """V3 ERROR — Closed Date is in the future."""
    future = emp_df[emp_df["work_date"].apply(lambda d: pd.notna(d) and d > today)]
    if future.empty:
        return []
    return [Violation("V3", "ERROR",
                       f"{len(future)} task(s) with future Closed Date",
                       f"IDs: {', '.join(str(i) for i in future['ID'].head(3))}")]


def _v4_excessive_daily_effort(emp_df: pd.DataFrame, daily_max: float) -> list[Violation]:
    """V4 ERROR — Total effort on a single day > daily_max hrs (physically impossible)."""
    daily = emp_df.groupby("work_date")["Completed Work"].sum()
    bad = daily[daily > daily_max]
    if bad.empty:
        return []
    details = ", ".join(f"{d.strftime('%d %b')} ({h:.1f}h)" for d, h in bad.head(3).items() if d)
    return [Violation("V4", "ERROR",
                       f"Excessive effort on {len(bad)} day(s) (>{daily_max}h)",
                       details)]


def _v5_overtime_without_incentive(emp_df: pd.DataFrame, daily_std: float) -> list[Violation]:
    """V5 WARNING — Daily basic effort (Planned as Incentive=0) > 8 hrs."""
    basic_df = emp_df[emp_df["Planned as Incentive"].fillna(0) == 0]
    daily_basic = basic_df.groupby("work_date")["Completed Work"].sum()
    bad = daily_basic[daily_basic > daily_std]
    if bad.empty:
        return []
    details = ", ".join(f"{d.strftime('%d %b')} ({h:.1f}h)" for d, h in bad.head(3).items() if d)
    return [Violation("V5", "WARNING",
                       f"Basic effort >8h on {len(bad)} day(s) without incentive flag",
                       details)]


def _v6_zero_monthly_effort(total_basic: float, total_incentive: float) -> list[Violation]:
    """V6 WARNING — Employee has 0 total effort for the month."""
    if total_basic + total_incentive == 0:
        return [Violation("V6", "WARNING", "Zero effort logged this month")]
    return []


def _v7_below_minimum(total_basic: float, contract: str, min_hrs: float) -> list[Violation]:
    """V7 WARNING — Full-time employee with basic effort below minimum threshold."""
    if contract != "Full-time":
        return []
    if total_basic < min_hrs:
        return [Violation("V7", "WARNING",
                           f"Basic effort {total_basic:.1f}h below minimum {min_hrs}h (full-time)")]
    return []


def _v8_weekend_entries(emp_df: pd.DataFrame) -> list[Violation]:
    """V8 WARNING — Closed Date falls on Saturday or Sunday."""
    weekend = emp_df[
        emp_df["work_date"].apply(lambda d: pd.notna(d) and d.weekday() in (4, 5))
    ]
    if weekend.empty:
        return []
    dates = sorted(d for d in weekend["work_date"].unique() if pd.notna(d))
    dates_str = ", ".join(d.strftime("%d %b (%a)") for d in dates[:3])
    return [Violation("V8", "WARNING",
                       f"{len(weekend)} task(s) logged on weekend",
                       dates_str)]


def _v9_consecutive_gap(emp_df: pd.DataFrame, today: date,
                         period_start: date, period_end: date, max_gap: int) -> list[Violation]:
    """V9 WARNING — More than max_gap consecutive working days with no entries."""
    window_end = min(today - timedelta(days=1), period_end)
    if window_end < period_start:
        return []

    days_with_effort = set(
        emp_df[emp_df["Completed Work"].fillna(0) > 0]["work_date"].dropna()
    )
    all_working = _working_days(period_start, window_end)

    max_found, current_gap, gap_start = 0, 0, None
    worst_start = None
    for d in all_working:
        if d not in days_with_effort:
            if current_gap == 0:
                gap_start = d
            current_gap += 1
            if current_gap > max_found:
                max_found = current_gap
                worst_start = gap_start
        else:
            current_gap = 0

    if max_found > max_gap:
        return [Violation("V9", "WARNING",
                           f"Gap of {max_found} consecutive working days with no entries",
                           f"Starting {worst_start.strftime('%d %b') if worst_start else ''}")]
    return []


def _v10_contract_cap(total_hrs: float, contract: str,
                       freelancer_cap: float, intern_cap: float) -> list[Violation]:
    """V10 INFO — Freelancer/Intern hours exceed monthly cap."""
    cap = None
    if contract == "Freelancer":
        cap = freelancer_cap
    elif contract == "Intern":
        cap = intern_cap
    if cap is not None and total_hrs > cap:
        return [Violation("V10", "INFO",
                           f"{contract} hours ({total_hrs:.1f}h) exceed monthly cap ({cap}h)")]
    return []


def _v12_behind_daily_pace(emp_df: pd.DataFrame, today: date,
                            period_start: date, daily_std: float) -> list[Violation]:
    """V12 ERROR — Behind expected period pace AND yesterday has no entry.

    Fires when BOTH are true:
      1. Yesterday is a working day (Sun–Thu) and has no logged effort.
      2. Total basic hours logged this period < (working days elapsed × daily_std).
    """
    yesterday = today - timedelta(days=1)
    if yesterday.weekday() in (4, 5):
        return []
    if yesterday < period_start:
        return []

    days_with_effort = set(
        emp_df[emp_df["Completed Work"].fillna(0) > 0]["work_date"].dropna()
    )

    # Condition 1: yesterday missing
    if yesterday in days_with_effort:
        return []

    # Condition 2: behind pace
    elapsed_working_days = len(_working_days(period_start, yesterday))
    expected_hrs = elapsed_working_days * daily_std
    total_basic = float(
        emp_df[emp_df["Planned as Incentive"].fillna(0) == 0]["Completed Work"].fillna(0).sum()
    )
    if total_basic >= expected_hrs:
        return []

    return [Violation(
        "V12", "ERROR",
        f"Behind daily pace: {total_basic:.1f}h logged vs {expected_hrs:.0f}h expected "
        f"({elapsed_working_days} working days × {daily_std:.0f}h) and yesterday missing",
        f"Yesterday: {yesterday.strftime('%d %b %Y')} — no entry found",
    )]


def _v11_missing_yesterday(emp_df: pd.DataFrame, today: date, period_start: date) -> list[Violation]:
    """V11 ERROR — No effort logged for yesterday (if yesterday was a working day)."""
    yesterday = today - timedelta(days=1)
    # Skip if yesterday is a weekend (Fri=4, Sat=5)
    if yesterday.weekday() in (4, 5):
        return []
    # Skip if yesterday is before the start of this period
    if yesterday < period_start:
        return []
    days_with_effort = set(
        emp_df[emp_df["Completed Work"].fillna(0) > 0]["work_date"].dropna()
    )
    if yesterday not in days_with_effort:
        return [Violation("V11", "ERROR",
                           f"No effort logged for yesterday ({yesterday.strftime('%d %b %Y')})",
                           "Expected at least one completed work entry")]
    return []


# ── Main validate function ────────────────────────────────────────────────────

def validate(df: pd.DataFrame, employees: list[dict],
             validation_cfg: dict, today: date | None = None) -> list[EmployeeReport]:
    """
    Run all validation rules for each employee.
    Returns a list of EmployeeReport sorted by squad then name.
    """
    if today is None:
        today = date.today()

    daily_std    = validation_cfg.get("daily_standard_hrs", 8)
    daily_max    = validation_cfg.get("daily_max_hrs", 16)
    min_basic    = validation_cfg.get("basic_effort_min_hrs", 8)
    max_gap      = validation_cfg.get("max_consecutive_gap_days", 2)
    free_cap     = validation_cfg.get("freelancer_monthly_cap_hrs", 160)
    intern_cap   = validation_cfg.get("intern_monthly_cap_hrs", 120)

    period_start, period_end = _period_bounds(today)

    # Filter to current billing period only
    df = _parse_dates(df)
    period_df = df[df["work_date"].apply(
        lambda d: pd.notna(d) and d >= period_start
    )].copy()

    reports = []
    for emp in employees:
        name     = emp["name"]
        contract = emp["contract"]
        emp_df   = _employee_rows(period_df, name)

        total_basic     = float(emp_df[emp_df["Planned as Incentive"].fillna(0) == 0]["Completed Work"].fillna(0).sum())
        total_incentive = float(emp_df[emp_df["Planned as Incentive"].fillna(0) == 1]["Completed Work"].fillna(0).sum())

        violations: list[Violation] = []
        violations += _v1_missing_daily_entry(emp_df, today, period_start, period_end)
        violations += _v2_late_logging(emp_df, period_end)
        violations += _v3_future_entries(emp_df, today)
        violations += _v4_excessive_daily_effort(emp_df, daily_max)
        violations += _v5_overtime_without_incentive(emp_df, daily_std)
        violations += _v6_zero_monthly_effort(total_basic, total_incentive)
        violations += _v7_below_minimum(total_basic, contract, min_basic)
        violations += _v8_weekend_entries(emp_df)
        violations += _v9_consecutive_gap(emp_df, today, period_start, period_end, max_gap)
        violations += _v10_contract_cap(total_basic + total_incentive, contract, free_cap, intern_cap)
        v12 = _v12_behind_daily_pace(emp_df, today, period_start, daily_std)
        violations += v12 if v12 else _v11_missing_yesterday(emp_df, today, period_start)

        reports.append(EmployeeReport(
            name=name,
            squad_name=emp["squad_name"],
            squad_lead=emp["squad_lead"],
            contract=contract,
            total_basic_hrs=total_basic,
            total_incentive_hrs=total_incentive,
            violations=violations,
        ))

    return sorted(reports, key=lambda r: (r.squad_name, r.name))
