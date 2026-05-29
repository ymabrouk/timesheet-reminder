"""
notifier.py
Sends Webex messages via the Webex Messaging REST API.
Supports sending to a person by email (direct message).
"""

from __future__ import annotations
import logging
import requests

WEBEX_API = "https://webexapis.com/v1/messages"

log = logging.getLogger("timesheet")


def send_message(token: str, recipient_email: str, markdown: str) -> bool:
    """
    Send a Webex direct message (markdown) to recipient_email.
    Returns True on success, False on failure.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    payload = {
        "toPersonEmail": recipient_email,
        "markdown":      markdown,
    }
    try:
        resp = requests.post(WEBEX_API, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        log.info(f"  Webex message sent to {recipient_email}")
        return True
    except requests.HTTPError as e:
        log.error(f"  Webex HTTP error {resp.status_code}: {resp.text}")
        return False
    except requests.RequestException as e:
        log.error(f"  Webex request failed: {e}")
        return False


def notify(token: str, recipient_email: str, recipient_name: str,
           full_report: str, summary_card: str) -> bool:
    """
    Send two messages to recipient:
      1. Summary card (short)
      2. Full detailed report
    """
    log.info(f"  Sending Webex notification to {recipient_name} <{recipient_email}>")
    ok1 = send_message(token, recipient_email, summary_card)
    ok2 = send_message(token, recipient_email, full_report)
    return ok1 and ok2
