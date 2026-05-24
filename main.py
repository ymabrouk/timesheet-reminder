"""
main.py
Azure DevOps Timesheet Extractor
----------------------------------
Orchestrates: download CSVs → consolidate → build tracker workbook.
Logs every run to logs/run_YYYY-MM-DD_HH-MM-SS.log with full stack traces
on failure and a structured success report.
"""

import os
import sys
import logging
import traceback
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from extractor import download_all_csvs
from consolidator import merge_csvs_into_template


# ── Logging setup ─────────────────────────────────────────────────────────────
def setup_logging(log_dir: str = "logs") -> logging.Logger:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    timestamp  = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file   = Path(log_dir) / f"run_{timestamp}.log"

    fmt = "%(asctime)s  %(levelname)-8s  %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("timesheet"), log_file


# ── Config ────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    load_dotenv()

    username        = os.getenv("ADO_USERNAME", "").strip()
    password        = os.getenv("ADO_PASSWORD", "").strip()
    query_links_raw = os.getenv("QUERY_LINKS", "").strip()
    download_dir    = os.getenv("DOWNLOAD_DIR", "downloads").strip()
    output_dir      = os.getenv("OUTPUT_DIR",   "output").strip()
    template_file   = os.getenv("TEMPLATE_FILE","template.xlsx").strip()
    headless        = os.getenv("HEADLESS", "true").strip().lower() != "false"

    errors = []
    if not username:        errors.append("ADO_USERNAME is not set in .env")
    if not password:        errors.append("ADO_PASSWORD is not set in .env")
    if not query_links_raw: errors.append("QUERY_LINKS is not set in .env")
    if errors:
        for e in errors:
            print(f"  [config error] {e}")
        print("Copy .env.example to .env and fill in your values.")
        sys.exit(1)

    query_links = [l.strip() for l in query_links_raw.split(",") if l.strip()]
    if not query_links:
        print("No valid query links found in QUERY_LINKS.")
        sys.exit(1)

    return dict(
        username=username, password=password,
        query_links=query_links,
        download_dir=download_dir, output_dir=output_dir,
        template_file=template_file, headless=headless,
    )


# ── Success report ────────────────────────────────────────────────────────────
def _log_success_report(log: logging.Logger, summary: dict):
    log.info("=" * 60)
    log.info("RUN COMPLETED SUCCESSFULLY")
    log.info("=" * 60)
    log.info(f"  Timestamp        : {summary['timestamp']}")
    log.info(f"  Output file      : {summary['output_file']}")
    log.info(f"  CSV files loaded : {', '.join(summary['csv_files'])}")
    log.info(f"  Rows extracted   : {summary['data_rows']}")
    log.info(f"  Employees total  : {summary['total_employees']}  "
             f"(config: {summary['static_employees']}, "
             f"new from data: {len(summary['new_employees'])})")
    if summary["new_employees"]:
        log.info(f"  New employees    : {', '.join(summary['new_employees'])}")
    if summary["missing_from_data"]:
        log.warning(f"  No records found : {', '.join(summary['missing_from_data'])} "
                    f"(included in Employees Effort with 0 effort — shown in red)")
    log.info(f"  Project codes    : {', '.join(summary['project_codes'])}")
    log.info("=" * 60)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log, log_file = setup_logging("logs")
    run_start = datetime.now()

    log.info("=" * 60)
    log.info("Azure DevOps Timesheet Extractor — RUN STARTED")
    log.info(f"Started at: {run_start.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    try:
        config = load_config()

        log.info(f"Query links  : {len(config['query_links'])}")
        log.info(f"Headless     : {config['headless']}")
        log.info(f"Download dir : {config['download_dir']}")
        log.info(f"Output dir   : {config['output_dir']}")
        log.info(f"Template     : {config['template_file']}")

        # ── Step 1: Download CSVs ─────────────────────────────────────────────
        log.info("--- Step 1: Downloading CSV exports from Azure DevOps ---")
        csv_files = download_all_csvs(
            query_links=config["query_links"],
            username=config["username"],
            password=config["password"],
            download_dir=config["download_dir"],
            headless=config["headless"],
        )

        if not csv_files:
            log.error("No CSV files were downloaded. Cannot consolidate.")
            sys.exit(1)

        log.info(f"Downloaded {len(csv_files)}/{len(config['query_links'])} CSV file(s).")

        # ── Step 2: Consolidate + build workbook ──────────────────────────────
        log.info("--- Step 2: Consolidating and building tracker workbook ---")
        output_path, summary = merge_csvs_into_template(
            csv_paths=csv_files,
            template_file=config["template_file"],
            output_dir=config["output_dir"],
        )

        _log_success_report(log, summary)

    except Exception:
        log.error("=" * 60)
        log.error("RUN FAILED")
        log.error("=" * 60)
        log.error(traceback.format_exc())
        log.error(f"Log file: {log_file.resolve()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
