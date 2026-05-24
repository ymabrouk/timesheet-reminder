# Azure DevOps Timesheet Extractor

## Purpose
Automates downloading CSV exports from Azure DevOps work item queries and consolidating them into a fully formatted Excel tracker workbook.

## Project Structure
```
timesheet-extractor/
├── main.py              # Orchestrator — run this
├── extractor.py         # Playwright: logs in to ADO, downloads CSVs
├── consolidator.py      # Merges CSVs into consolidated_efforts sheet, calls builder
├── builder.py           # Builds Employees Effort, Lookup, Project Code sheets
├── config/
│   └── config.json      # Employee roster + project codes (edit here, not in code)
├── output/              # Generated Excel files (consolidated_output_YYYY-MM-DD_HH-MM-SS.xlsx)
├── logs/                # Run logs (run_YYYY-MM-DD_HH-MM-SS.log)
├── downloads/           # Downloaded CSVs from ADO queries
├── template.xlsx        # Excel template (user-provided, must exist before running)
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
TEMPLATE_FILE=template.xlsx

# false = show browser window (required for on-prem NTLM auth / MFA)
HEADLESS=false
```

## config/config.json
Controls the employee roster and project codes. Edit this file to add/remove employees or project codes — no code changes needed.

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
  "project_codes": ["4452"]
}
```

## Running
```bash
pip install -r requirements.txt
playwright install chromium
python main.py
```

## Output Workbook — 4 Sheets
Sheets are created in this tab order:

| # | Sheet | Contents |
|---|-------|----------|
| 1 | `consolidated_efforts` | Raw data exported from all ADO query CSVs |
| 2 | `Employees Effort` | Main tracker with formulas, formatting, totals, autofilter |
| 3 | `Lookup` | Employee reference data (static from config + auto-appended new) |
| 4 | `Project Code` | Project code reference table (named table: ProjectCode) |

## Employees Effort Sheet — Columns & Formulas
| Col | Header | Source |
|-----|--------|--------|
| A | Employee Name | From config.json employees list |
| B | Employee Code | =VLOOKUP from Lookup |
| C | Employment Contract | =VLOOKUP from Lookup |
| D | Basic Effort | =SUMPRODUCT (Planned as Incentive = 0) |
| E | Incentive Effort | =SUMPRODUCT (Planned as Incentive = 1) |
| F | Total Effort | =D+E |
| G | Squad Lead | =VLOOKUP from Lookup |
| H | Squad Name | =VLOOKUP from Lookup |
| I | Project Code | Dropdown from Project Code sheet |

Totals row at bottom: SUM of D, E, F — bold, grey background, medium top border.

## Color Formatting (Conditional)
Priority order (highest → lowest):

| Condition | Color | Notes |
|-----------|-------|-------|
| Basic Effort < 16 hrs (< 10% of 160) | `#FF9999` red | Overrides everything |
| Contract = Intern | `#E8D5F5` purple-ish | Col C font: bold `#7030A0` |
| Contract = Freelancer | `#FCE4D6` orange-ish | Col C font: bold `#C55A11` |
| Squad = Fighters | `#DDEBF7` light blue | |
| Squad = Hero | `#E2EFDA` light green | |
| Squad = Ninga | `#FFF2CC` light yellow | |

Header row: `#2F5496` background, white bold font.
Totals row: `#D6DCE4` grey background, bold font, medium top border.

## Employee Roster Logic
1. All employees in `config.json` are always included in `Employees Effort`.
2. Employees found in `consolidated_efforts` (`Assigned To` column) but **not** in config are auto-appended to `Lookup` with blank details.
3. Employees in config with **no records** in `consolidated_efforts` are still included — they show 0 effort and are flagged red.

`Assigned To` format in ADO: `Full Name <DOMAIN\username>` — the app extracts the display name before ` <`.

## Logging
Every run writes to `logs/run_YYYY-MM-DD_HH-MM-SS.log` (also printed to console).

**Success report includes:**
- Timestamp and output file path
- Number of rows extracted
- Total employees (config count + new from data)
- New employees auto-appended to Lookup
- Employees with no records in consolidated_efforts (0 effort, shown red)
- Project codes loaded

**Failure:** full Python stack trace is written to the log file.

## Authentication
The server `azuredevops2022.intercom.com.eg` uses HTTP-level (NTLM/Basic) authentication.
Credentials are passed via Playwright's `http_credentials` context option.
`HEADLESS=false` keeps the browser visible — required for this on-prem server.

## Notes
- Downloaded CSVs are saved to `DOWNLOAD_DIR` and reused if the network is unavailable.
- Each run produces a new timestamped file in `output/` — previous files are never overwritten.
- To add a new squad color, add it to `SQUAD_COLORS` dict in `builder.py`.
- To add employees or project codes, edit `config/config.json` only.
