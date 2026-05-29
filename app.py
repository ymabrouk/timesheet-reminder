"""
app.py — Flask web GUI for the Timesheet Reminder tool.
Run with: python app.py
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from flask import (
    Flask, jsonify, redirect, render_template,
    request, send_file, url_for,
)

app = Flask(__name__)

BASE_DIR     = Path(__file__).parent
CONFIG_PATH  = BASE_DIR / "config" / "config.json"
LOGS_DIR     = BASE_DIR / "logs"
OUTPUT_DIR   = BASE_DIR / "output"


# ── Config helpers ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ── File listing helpers ───────────────────────────────────────────────────────

def _log_files() -> list[dict]:
    """Return log file metadata sorted newest first."""
    LOGS_DIR.mkdir(exist_ok=True)
    files = []
    for p in sorted(LOGS_DIR.glob("*.log"), reverse=True):
        stat = p.stat()
        files.append({
            "filename": p.name,
            "size":     _fmt_size(stat.st_size),
            "date":     _parse_file_date(p.name),
            "path":     str(p),
        })
    return files


def _report_files() -> list[dict]:
    """Return Excel report file metadata sorted newest first."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    files = []
    for p in sorted(OUTPUT_DIR.glob("*.xlsx"), reverse=True):
        stat = p.stat()
        files.append({
            "filename": p.name,
            "size":     _fmt_size(stat.st_size),
            "date":     _parse_file_date(p.name),
            "path":     str(p),
        })
    return files


def _fmt_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / 1024 ** 2:.1f} MB"


def _parse_file_date(filename: str) -> str:
    """Extract a human-readable date from filenames like reminder_2026-05-25_02-33-36.log
    or report_2026-05-24.xlsx."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            pass
    return "—"


def _last_run_label() -> str:
    logs = _log_files()
    if not logs:
        return "Never"
    return logs[0]["date"]


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    cfg      = load_config()
    logs     = _log_files()
    reports  = _report_files()
    return render_template(
        "dashboard.html",
        employee_count=len(cfg.get("employees", [])),
        last_run=_last_run_label(),
        report_count=len(reports),
        log_count=len(logs),
        recent_reports=reports[:5],
        recent_logs=logs[:5],
        today=datetime.today().strftime("%Y-%m-%d"),
    )


# ── Employees ──────────────────────────────────────────────────────────────────

@app.route("/employees", methods=["GET"])
def employees():
    cfg = load_config()
    squad_names = sorted({e["squad_name"] for e in cfg.get("employees", [])})
    return render_template(
        "employees.html",
        employees=cfg.get("employees", []),
        squad_names=squad_names,
    )


@app.route("/employees/add", methods=["POST"])
def employees_add():
    cfg = load_config()
    new_emp = {
        "name":       request.form.get("name", "").strip(),
        "code":       int(request.form.get("code") or 0),
        "contract":   request.form.get("contract", "Full-time"),
        "squad_lead": request.form.get("squad_lead", "").strip(),
        "squad_name": request.form.get("squad_name", "").strip(),
    }
    cfg.setdefault("employees", []).append(new_emp)
    save_config(cfg)
    return redirect(url_for("employees"))


@app.route("/employees/edit/<int:idx>", methods=["POST"])
def employees_edit(idx: int):
    cfg       = load_config()
    employees = cfg.get("employees", [])
    if 0 <= idx < len(employees):
        employees[idx] = {
            "name":       request.form.get("name", "").strip(),
            "code":       int(request.form.get("code") or 0),
            "contract":   request.form.get("contract", "Full-time"),
            "squad_lead": request.form.get("squad_lead", "").strip(),
            "squad_name": request.form.get("squad_name", "").strip(),
        }
        save_config(cfg)
    return redirect(url_for("employees"))


@app.route("/employees/delete/<int:idx>", methods=["POST"])
def employees_delete(idx: int):
    cfg       = load_config()
    employees = cfg.get("employees", [])
    if 0 <= idx < len(employees):
        employees.pop(idx)
        save_config(cfg)
    return redirect(url_for("employees"))


# ── Settings ───────────────────────────────────────────────────────────────────

@app.route("/settings", methods=["GET", "POST"])
def settings():
    cfg = load_config()

    if request.method == "POST":
        cfg["validation"] = {
            "basic_effort_min_hrs":      _safe_float(request.form.get("basic_effort_min_hrs"), 8),
            "daily_standard_hrs":        _safe_float(request.form.get("daily_standard_hrs"), 8),
            "daily_max_hrs":             _safe_float(request.form.get("daily_max_hrs"), 16),
            "late_logging_cutoff_day":   _safe_int(request.form.get("late_logging_cutoff_day"), 25),
            "max_consecutive_gap_days":  _safe_int(request.form.get("max_consecutive_gap_days"), 2),
            "freelancer_monthly_cap_hrs": _safe_float(request.form.get("freelancer_monthly_cap_hrs"), 160),
            "intern_monthly_cap_hrs":    _safe_float(request.form.get("intern_monthly_cap_hrs"), 120),
        }
        cfg["notification"] = {
            "recipient_email": request.form.get("recipient_email", "").strip(),
            "recipient_name":  request.form.get("recipient_name", "").strip(),
        }
        save_config(cfg)
        return redirect(url_for("settings", saved=1))

    return render_template(
        "settings.html",
        validation=cfg.get("validation", {}),
        notification=cfg.get("notification", {}),
        saved=request.args.get("saved"),
    )


def _safe_float(val, default):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


# ── Run main.py ────────────────────────────────────────────────────────────────

@app.route("/run", methods=["POST"])
def run():
    date_val   = request.form.get("date", "").strip()
    yesterday  = request.form.get("yesterday") == "on"

    cmd = [sys.executable, str(BASE_DIR / "main.py")]
    if yesterday:
        cmd.append("--yesterday")
    elif date_val:
        cmd.extend(["--date", date_val])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(BASE_DIR),
            timeout=300,
        )
        combined = (result.stdout or "") + (result.stderr or "")
        success  = result.returncode == 0
        return jsonify({"success": success, "output": combined})
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "output": "Process timed out after 5 minutes."})
    except Exception as exc:
        return jsonify({"success": False, "output": str(exc)})


# ── Logs ───────────────────────────────────────────────────────────────────────

@app.route("/logs")
def logs():
    return render_template("logs.html", logs=_log_files())


@app.route("/logs/<filename>")
def log_content(filename: str):
    # Restrict to simple filenames (no path traversal)
    safe = Path(filename).name
    log_path = LOGS_DIR / safe
    if not log_path.exists():
        return jsonify({"content": "File not found."}), 404
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        content = str(exc)
    return jsonify({"content": content})


# ── Reports ────────────────────────────────────────────────────────────────────

@app.route("/reports")
def reports():
    return render_template("reports.html", reports=_report_files())


@app.route("/reports/download/<filename>")
def report_download(filename: str):
    safe        = Path(filename).name
    report_path = OUTPUT_DIR / safe
    if not report_path.exists():
        return "File not found.", 404
    return send_file(
        str(report_path),
        as_attachment=True,
        download_name=safe,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=5000)
