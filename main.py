"""
main.py — Timesheet Reminder
------------------------------
Runs daily:
  1. Downloads CSV from Azure DevOps
  2. Validates all employees against 10 rules
  3. Consolidates violations by squad
  4. Sends Webex notification to Yasser Mabrouk
  5. Logs full run report with stack trace on failure
"""

import argparse
import os
import sys
import json
import logging
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

from extractor import download_all_csvs
from validator import validate
from excel_reporter import save_report as save_excel_report
from reporter import build_report, build_summary_card
from notifier import notify
import pandas as pd


# ── Logging ───────────────────────────────────────────────────────────────────
def setup_logging(log_dir: str = "logs") -> tuple[logging.Logger, Path]:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = Path(log_dir) / f"reminder_{ts}.log"
    fmt      = "%(asctime)s  %(levelname)-8s  %(message)s"

    # Reconfigure stdout to UTF-8 on Windows to support emoji in console output
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    logging.basicConfig(
        level=logging.INFO, format=fmt,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("timesheet"), log_file


# ── Config ────────────────────────────────────────────────────────────────────
_CONFIG_PATH = Path(__file__).parent / "config" / "config.json"

def load_app_config() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)

def load_env_config() -> dict:
    load_dotenv()
    username        = os.getenv("ADO_USERNAME", "").strip()
    password        = os.getenv("ADO_PASSWORD", "").strip()
    query_links_raw = os.getenv("QUERY_LINKS", "").strip()
    download_dir    = os.getenv("DOWNLOAD_DIR", "downloads").strip()
    output_dir      = os.getenv("OUTPUT_DIR", "output").strip()
    headless        = os.getenv("HEADLESS", "true").strip().lower() != "false"
    webex_token     = os.getenv("WEBEX_TOKEN", "").strip()

    errors = []
    if not username:        errors.append("ADO_USERNAME not set")
    if not password:        errors.append("ADO_PASSWORD not set")
    if not query_links_raw: errors.append("QUERY_LINKS not set")
    if errors:
        for e in errors:
            print(f"  [config error] {e}")
        sys.exit(1)

    return dict(
        username=username, password=password,
        query_links=[l.strip() for l in query_links_raw.split(",") if l.strip()],
        download_dir=download_dir,
        output_dir=output_dir,
        headless=headless,
        webex_token=webex_token,
    )


# ── Run report ────────────────────────────────────────────────────────────────
def _log_run_report(log: logging.Logger, reports, today: date):
    violated    = [r for r in reports if not r.is_clean]
    clean       = [r for r in reports if r.is_clean]
    error_count = sum(r.error_count   for r in reports)
    warn_count  = sum(r.warning_count for r in reports)

    log.info("=" * 60)
    log.info("VALIDATION REPORT")
    log.info("=" * 60)
    log.info(f"  Date              : {today.strftime('%Y-%m-%d')}")
    log.info(f"  Total employees   : {len(reports)}")
    log.info(f"  Clean             : {len(clean)}")
    log.info(f"  With violations   : {len(violated)}")
    log.info(f"  Hard errors       : {error_count}")
    log.info(f"  Warnings          : {warn_count}")

    if violated:
        log.info("")
        log.info("  Violations:")
        for r in violated:
            log.info(f"    [{r.squad_name}] {r.name} ({r.contract}): "
                     f"{r.error_count} error(s), {r.warning_count} warning(s)")
            for v in r.violations:
                log.info(f"      {v}")
    log.info("=" * 60)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Timesheet Reminder")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--yesterday", action="store_true",
                       help="Run report for yesterday instead of today")
    group.add_argument("--date", metavar="YYYY-MM-DD",
                       help="Run report for a specific date")
    args = parser.parse_args()

    if args.yesterday:
        today = date.today() - timedelta(days=1)
    elif args.date:
        try:
            today = date.fromisoformat(args.date)
        except ValueError:
            print(f"[error] Invalid date format: {args.date!r}. Use YYYY-MM-DD.")
            sys.exit(1)
    else:
        today = date.today()

    log, log_file = setup_logging("logs")

    log.info("=" * 60)
    log.info("Timesheet Reminder — RUN STARTED")
    log.info(f"Date: {today.strftime('%Y-%m-%d')}")
    log.info("=" * 60)

    try:
        env_cfg = load_env_config()
        app_cfg = load_app_config()

        employees      = app_cfg["employees"]
        validation_cfg = app_cfg.get("validation", {})

        # ── Step 1: Download CSVs ─────────────────────────────────────────────
        log.info("--- Step 1: Downloading CSV from Azure DevOps ---")
        csv_files = download_all_csvs(
            query_links=env_cfg["query_links"],
            username=env_cfg["username"],
            password=env_cfg["password"],
            download_dir=env_cfg["download_dir"],
            headless=env_cfg["headless"],
        )
        if not csv_files:
            log.error("No CSV files downloaded. Aborting.")
            sys.exit(1)
        log.info(f"Downloaded {len(csv_files)} file(s).")

        # ── Step 2: Load & combine CSVs ───────────────────────────────────────
        log.info("--- Step 2: Loading data ---")
        frames   = [pd.read_csv(f, encoding="utf-8-sig") for f in csv_files]
        combined = pd.concat(frames, ignore_index=True)
        combined = combined.where(pd.notnull(combined), None)
        log.info(f"Total rows loaded: {len(combined)}")

        # ── Step 3: Validate ──────────────────────────────────────────────────
        log.info("--- Step 3: Validating ---")
        reports = validate(combined, employees, validation_cfg, today)
        _log_run_report(log, reports, today)

        # ── Step 4: Export daily report file ──────────────────────────────────
        log.info("--- Step 4: Exporting daily report ---")
        report_file = save_excel_report(reports, today, env_cfg["output_dir"])
        log.info(f"Report saved to: {report_file.resolve()}")

        # ── Step 5: Send Webex notification ───────────────────────────────────
        log.info("--- Step 5: Sending Webex notification ---")
        notif_cfg = app_cfg.get("notification", {})
        recipient_email = notif_cfg.get("recipient_email", "")
        recipient_name  = notif_cfg.get("recipient_name", "")
        webex_token     = env_cfg["webex_token"]

        if not webex_token:
            log.warning("WEBEX_TOKEN not set — skipping notification.")
        elif not recipient_email:
            log.warning("notification.recipient_email not set in config.json — skipping notification.")
        else:
            summary_card = build_summary_card(reports, today)
            full_report  = build_report(reports, today)
            ok = notify(webex_token, recipient_email, recipient_name, full_report, summary_card)
            if not ok:
                log.warning("Webex notification failed — check token and recipient. Run continues.")

        log.info("=" * 60)
        log.info("RUN COMPLETED SUCCESSFULLY")
        log.info("=" * 60)

    except Exception:
        log.error("=" * 60)
        log.error("RUN FAILED")
        log.error("=" * 60)
        log.error(traceback.format_exc())
        log.error(f"Log file: {log_file.resolve()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
