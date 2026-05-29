"""
reporter.py
Consolidates EmployeeReport list into a Webex-ready markdown summary
grouped by squad, with overall stats and per-employee violation details.
"""

from __future__ import annotations
from datetime import date
from itertools import groupby
from validator import EmployeeReport


SQUAD_ICONS = {
    "Fighters": "⚔️",
    "Hero":     "🦸",
    "Ninga":    "🥷",
}

CONTRACT_BADGE = {
    "Full-time":  "",
    "Freelancer": " *(Freelancer)*",
    "Intern":     " *(Intern)*",
}


def _squad_icon(name: str) -> str:
    return SQUAD_ICONS.get(name, "👥")


def build_report(reports: list[EmployeeReport], today: date | None = None) -> str:
    """
    Build a full Webex markdown report string.
    Sections: header → overall summary → per-squad details → footer.
    """
    if today is None:
        today = date.today()

    total_emp       = len(reports)
    violated        = [r for r in reports if not r.is_clean]
    clean           = [r for r in reports if r.is_clean]
    error_count     = sum(r.error_count   for r in reports)
    warning_count   = sum(r.warning_count for r in reports)

    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────────
    lines.append(f"## 📋 Daily Timesheet Validation Report")
    lines.append(f"**Date:** {today.strftime('%A, %d %B %Y')}  |  "
                 f"**Month:** {today.strftime('%B %Y')}")
    lines.append("")

    # ── Overall summary ───────────────────────────────────────────────────────
    status_icon = "✅" if not violated else ("🔴" if error_count else "🟡")
    lines.append(f"### {status_icon} Overall Summary")
    lines.append(f"| | Count |")
    lines.append(f"|---|---|")
    lines.append(f"| 👤 Total employees | {total_emp} |")
    lines.append(f"| ✅ Clean | {len(clean)} |")
    lines.append(f"| ⚠️ With violations | {len(violated)} |")
    lines.append(f"| 🔴 Hard errors | {error_count} |")
    lines.append(f"| 🟡 Warnings | {warning_count} |")
    lines.append("")

    if not violated:
        lines.append("**All employees are compliant. No action required today.**")
        lines.append("")
        lines.append("---")
        lines.append(_footer(today))
        return "\n".join(lines)

    # ── Per-squad breakdown ───────────────────────────────────────────────────
    lines.append("### Violations by Squad")
    lines.append("")

    squads = {}
    for r in reports:
        squads.setdefault(r.squad_name, []).append(r)

    for squad_name, squad_reports in sorted(squads.items()):
        icon = _squad_icon(squad_name)
        squad_violations = [r for r in squad_reports if not r.is_clean]
        squad_lead = squad_reports[0].squad_lead

        lead_str    = f"Lead: **{squad_lead}**"
        status_str  = (f"✅ All clean" if not squad_violations
                       else f"⚠️ {len(squad_violations)}/{len(squad_reports)} employee(s) with issues")

        lines.append(f"#### {icon} {squad_name}  —  {lead_str}")
        lines.append(f"*{status_str}*")
        lines.append("")

        for r in squad_reports:
            badge = CONTRACT_BADGE.get(r.contract, "")
            effort_str = (f"Basic: **{r.total_basic_hrs:.1f}h** | "
                          f"Incentive: {r.total_incentive_hrs:.1f}h | "
                          f"Total: {r.total_hrs:.1f}h")

            if r.is_clean:
                lines.append(f"- ✅ **{r.name}**{badge}  —  {effort_str}")
            else:
                lines.append(f"- **{r.name}**{badge}  —  {effort_str}")
                for v in sorted(r.violations, key=lambda x: x.severity):
                    lines.append(f"  - {v}")
        lines.append("")

    # ── Action required ───────────────────────────────────────────────────────
    if error_count:
        lines.append("---")
        lines.append("### 🚨 Action Required")
        lines.append(
            f"**{error_count} hard error(s)** must be resolved before the "
            f"25th of {today.strftime('%B')}:"
        )
        for r in violated:
            errors = [v for v in r.violations if v.severity == "ERROR"]
            if errors:
                lines.append(f"- **{r.name}** ({r.squad_name}): "
                              + " | ".join(v.message for v in errors))
        lines.append("")

    lines.append("---")
    lines.append(_footer(today))
    return "\n".join(lines)


def _footer(today: date) -> str:
    return (f"*Generated automatically by Timesheet Reminder · "
            f"{today.strftime('%Y-%m-%d')} · "
            f"Reply to this message or contact your squad lead to resolve issues.*")


def build_summary_card(reports: list[EmployeeReport], today: date | None = None) -> str:
    """Short one-line summary card for quick daily digest."""
    if today is None:
        today = date.today()

    violated    = [r for r in reports if not r.is_clean]
    error_count = sum(r.error_count for r in reports)
    warn_count  = sum(r.warning_count for r in reports)

    if not violated:
        return (f"✅ **Timesheet Check {today.strftime('%d %b')}** — "
                f"All {len(reports)} employees compliant.")

    names = ", ".join(r.name.split()[0] for r in violated[:4])
    extra = f" +{len(violated) - 4} more" if len(violated) > 4 else ""
    return (f"⚠️ **Timesheet Check {today.strftime('%d %b')}** — "
            f"{len(violated)} employee(s) with issues "
            f"({error_count} errors, {warn_count} warnings): "
            f"{names}{extra}. See full report above.")
