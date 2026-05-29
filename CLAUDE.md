# Azure DevOps Timesheet Reminder

## Purpose
Automates daily timesheet compliance monitoring:
1. Downloads CSV exports from Azure DevOps work item queries
2. Validates all employees against 12 rules
3. Exports a formatted daily Excel validation report
4. Sends Webex notifications to the designated recipient

## Project Structure
```
timesheet-reminder/
├── main.py              # Orchestrator — run this
├── extractor.py         # Playwright: logs in to ADO, downloads CSVs
├── validator.py         # 12 validation rules → EmployeeReport list
├── excel_reporter.py    # Builds formatted Excel daily report
├── reporter.py          # Builds Webex markdown report (summary + full)
├── notifier.py          # Sends Webex messages via REST API
├── config/
│   └── config.json      # Employee roster, validation thresholds, notification target
├── output/              # Daily Excel reports (report_YYYY-MM-DD.xlsx)
├── logs/                # Run logs (reminder_YYYY-MM-DD_HH-MM-SS.log)
├── downloads/           # Downloaded CSVs from ADO queries
├── requirements.txt     # Python dependencies
└── .env                 # Credentials + config (never commit)
```

## Environment Variables (.env)
```
ADO_USERNAME=your.email@company.com
ADO_PASSWORD=yourpassword

# Comma-separated ADO query URLs
QUERY_LINKS=https://azuredevops2022.intercom.com.eg/...

DOWNLOAD_DIR=downloads
OUTPUT_DIR=output

# false = show browser window (required for on-prem NTLM auth)
HEADLESS=false

# Webex Bot token for notifications
WEBEX_TOKEN=your_webex_bot_token
```

## config/config.json
Edit this file to change employees, validation thresholds, or notification target — no code changes needed.

```json
{
  "employees": [
    {
      "name": "Full Name",
      "code": 1234,
      "contract": "Full-time",
      "squad_lead": "Lead Name",
      "squad_name": "Squad"
    }
  ],
  "project_codes": ["4452"],
  "validation": {
    "basic_effort_min_hrs": 8,
    "daily_standard_hrs": 8,
    "daily_max_hrs": 16,
    "late_logging_cutoff_day": 25,
    "max_consecutive_gap_days": 2,
    "freelancer_monthly_cap_hrs": 160,
    "intern_monthly_cap_hrs": 120
  },
  "notification": {
    "recipient_email": "name@company.com",
    "recipient_name": "Full Name"
  }
}
```

## Running
```bash
pip install -r requirements.txt
playwright install chromium
python main.py                   # today
python main.py --yesterday       # run for yesterday
python main.py --date 2026-05-15 # run for a specific date
```

## Pipeline — Step by Step
| Step | Module | Action |
|------|--------|--------|
| 1 | `extractor.py` | Downloads CSVs from all ADO query URLs via Playwright |
| 2 | `main.py` | Loads and concatenates all CSVs into a single DataFrame |
| 3 | `validator.py` | Runs 12 rules per employee → `list[EmployeeReport]` |
| 4 | `excel_reporter.py` | Saves `report_YYYY-MM-DD.xlsx` to `output/` |
| 5 | `reporter.py` | Builds Webex markdown (summary card + full report) |
| 6 | `notifier.py` | Sends both messages to recipient via Webex API |

## Validation Rules (validator.py)
Billing cycle: **25th of month → 24th of next month**.
Working week: **Sunday–Thursday** (Fri + Sat are weekends).

| Code | Severity | Trigger |
|------|----------|---------|
| V1 | ERROR | Missing Completed Work on any working day in the check window |
| V2 | ERROR | Task Closed Date is after the 24th (period end) |
| V3 | ERROR | Task Closed Date is in the future |
| V4 | ERROR | Total effort on a single day exceeds `daily_max_hrs` (default 16h) |
| V5 | WARNING | Basic effort on a single day exceeds 8h without Incentive flag |
| V6 | WARNING | Zero total effort logged this billing period |
| V7 | WARNING | Full-time employee basic effort below `basic_effort_min_hrs` |
| V8 | WARNING | Closed Date falls on Friday or Saturday |
| V9 | WARNING | Gap of more than `max_consecutive_gap_days` working days with no entry |
| V10 | INFO | Freelancer/Intern hours exceed monthly cap |
| V11 | ERROR | No effort logged for yesterday (if yesterday was a working day) |
| V12 | ERROR | Behind expected pace AND yesterday has no entry (combined check) |

Violations are severity-sorted: ERROR → WARNING → INFO.

## EmployeeReport dataclass
Fields: `name`, `squad_name`, `squad_lead`, `contract`, `total_basic_hrs`, `total_incentive_hrs`, `violations`.
Computed properties: `total_hrs`, `error_count`, `warning_count`, `is_clean`.

## Excel Report (excel_reporter.py)
Single sheet: **"Validation Report"**. Output: `output/report_YYYY-MM-DD.xlsx`.

### Structure
| Section | Content |
|---------|---------|
| Row 1 | Merged title: "Daily Timesheet Validation Report — Month Year" |
| Row 2 | Merged subtitle: generated date |
| Summary block | Total employees, Clean, With Violations, Hard Errors, Warnings |
| Column headers | 12 columns (see below) |
| Per-squad groups | Squad header row → employee rows → violation sub-rows |
| Totals row | SUM of Basic / Incentive / Total hours |

### Columns (12)
| Col | Header | Notes |
|-----|--------|-------|
| A | Employee Name | |
| B | Contract | |
| C | Squad | |
| D | Squad Lead | |
| E | Basic Hrs | centered |
| F | Incentive Hrs | centered |
| G | Total Hrs | centered |
| H | Status | CLEAN / N Error(s) / N Warning(s) |
| I | Code | V1–V12, centered |
| J | Severity | ERROR / WARNING / INFO, centered |
| K | Violation Message | |
| L | Detail | |

### Color Palette
| Element | Fill | Font |
|---------|------|------|
| Header / title | `#2F5496` | white bold |
| Subtitle bar | `#1F3864` | white |
| Summary bg | `#D6DCE4` | |
| Totals row | `#D6DCE4` | bold, medium top border |
| Squad: Fighters | `#DDEBF7` row / `#2E75B6` header | |
| Squad: Hero | `#E2EFDA` row / `#375623` header | |
| Squad: Ninga | `#FFF2CC` row / `#7F6000` header | |
| Default squad | `#F2F2F2` row / `#595959` header | |
| Contract: Freelancer | `#FCE4D6` | |
| Contract: Intern | `#E8D5F5` | |
| Violation ERROR | `#FFD7D7` | `#C00000` |
| Violation WARNING | `#FFF3CD` | `#7F4F00` |
| Violation INFO | `#D9EAF7` | `#0070C0` |
| CLEAN status | `#E2EFDA` | `#375623` |

## Webex Notification (reporter.py + notifier.py)
Two messages are sent to `notification.recipient_email`:
1. **Summary card** — one-line digest (e.g. "⚠️ Timesheet Check 29 May — 3 employees with issues…")
2. **Full report** — markdown with overall stats, per-squad breakdown, per-employee violations, action-required section

Squad icons: Fighters ⚔️, Hero 🦸, Ninga 🥷. Contract badges: Freelancer *(Freelancer)*, Intern *(Intern)*.

`notifier.send_message()` posts to `https://webexapis.com/v1/messages` using the bot token.

## Authentication
`azuredevops2022.intercom.com.eg` uses NTLM/Basic HTTP authentication.
Credentials passed via Playwright's `http_credentials` context option.
`HEADLESS=false` keeps the browser visible — required for this on-prem server.

## Logging
Every run writes to `logs/reminder_YYYY-MM-DD_HH-MM-SS.log` (also printed to console).

**Success report includes:**
- Run date, total employees, clean vs violated counts
- Hard error and warning totals
- Per-employee violation details

**Failure:** full Python stack trace written to log.

## Notes
- To add a new squad color, add it to `SQUAD_COLORS` in `excel_reporter.py` and `SQUAD_ICONS` in `reporter.py`.
- To add/remove employees, validation thresholds, or the notification target, edit `config/config.json` only.
- Downloaded CSVs are saved to `DOWNLOAD_DIR`; each run produces one new dated report in `output/` — previous files are never overwritten.
- The `Assigned To` field in ADO has format `Full Name <DOMAIN\username>` — the validator matches on the display name portion (before ` <`).
