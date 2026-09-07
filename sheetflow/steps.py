"""The three console steps: find -> draft -> send. Run through `python -m sheetflow`."""
from __future__ import annotations

import json
import os
import random
import smtplib
import subprocess
import sys
import time
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from .support import (
    COLUMNS,
    Bootstrap,
    PROFILE_CELL_LIMIT,
    llm_write,
    open_sheet,
    parse_draft,
    require_env,
    sheet_rows,
    write_row,
)

# ── Step 1: find ───────────────────────────────────────────────────


def cmd_find(goal: int, free: bool = False) -> int:
    """Find leads through the finder's own CLI and put them in the sheet.

    Without `--free` the goal is in the `emails` unit: the finder buys one verified
    address per lead (1 BetterContact credit each) before the row reaches the sheet.
    """
    with Bootstrap():
        args = [sys.executable, "-m", "openoutreach", "find", str(goal)]
        if not free:
            args.append("emails")
        args.append("--json")
        print(f"[sheetflow] finding {goal} lead(s) via the finder...", file=sys.stderr)
        proc = subprocess.run(args, stdout=subprocess.PIPE, text=True, encoding="utf-8")

    records = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            print(f"[sheetflow] skipped a non-JSON stdout line (paid lead lost): {line[:80]!r}",
                  file=sys.stderr)
            continue
        records.append(record)

    if not records and proc.returncode != 0:
        sys.exit(f"[sheetflow] the finder failed and returned nothing:\n{proc.stderr[-1500:]}")
    if proc.returncode != 0:
        print(f"[sheetflow] note: the finder stopped short; keeping what arrived.",
              file=sys.stderr)

    ws, index = open_sheet()
    known = {}
    for number, values in sheet_rows(ws, index):
        lead_id = values["Lead ID"].strip()
        if lead_id:
            known[lead_id] = number

    appended, updated = 0, 0
    for record in records:
        lead_id = str(record.get("lead_id") or "").strip()
        if not lead_id:
            continue
        email = (record.get("email") or "").strip()
        profile = (record.get("profile_text") or "").strip()
        reason = (record.get("reason") or "").strip()
        if lead_id in known:
            # A re-find: fill the address in on the row that already exists.
            number = known[lead_id]
            existing = ws.row_values(number)
            current_email = existing[index["Email"]] if index["Email"] < len(existing) else ""
            if email and not current_email.strip():
                updates = {"Email": email, "Status": "Found"}
                if reason:
                    updates["Match Reason"] = reason
                write_row(ws, number, updates, index)
                updated += 1
            continue
        status = "Found" if email else ("Found - no email" if free else "Found - no email")
        row = [
            lead_id,
            (record.get("first_name") or "").strip(),
            (record.get("last_name") or "").strip(),
            (record.get("title") or "").strip(),
            (record.get("company") or "").strip(),
            (record.get("website") or "").strip(),
            (record.get("linkedin_url") or "").strip(),
            email,
            reason,
            profile[:PROFILE_CELL_LIMIT],
            status,
            "", "", "", "", "",
        ]
        ws.append_row(row, value_input_option="RAW")
        appended += 1
        known[lead_id] = None

    print(f"[sheetflow] sheet updated: {appended} new row(s), {updated} filled with an address")
    return 0


# ── Step 2: draft ──────────────────────────────────────────────────


def cmd_draft(limit: int | None = None) -> int:
    """Write a personalized draft into the sheet for every row that has an address."""
    with Bootstrap():
        def from_repo(filename: str, env_var: str) -> str:
            path = Path(filename)
            if path.exists():
                return path.read_text(encoding="utf-8")
            return os.environ.get(env_var, "")

        product_docs = from_repo("product.md", "OPENOUTFIND_PRODUCT_DOCS")
        campaign_target = from_repo("target.md", "OPENOUTFIND_CAMPAIGN_TARGET")
        operator_name = os.environ.get("OUTSEND_OPERATOR_NAME", "").strip()
        signature = os.environ.get("OUTSEND_SIGNATURE", "").strip()

    ws, index = open_sheet()
    drafted = 0
    for number, values in sheet_rows(ws, index):
        if limit is not None and drafted >= limit:
            break
        if values["Status"].strip() not in ("", "Found", "Drafted"):
            continue
        if not values["Email"].strip() or values["Draft Body"].strip():
            continue
        if values["Status"].strip() == "Drafted":
            continue  # a draft already exists; only blank bodies are (re)written

        lead_block = "\n".join(
            f"{label}: {values[name].strip()}"
            for label, name in (
                ("Name", "First Name"), ("Role", "Title"), ("Company", "Company"),
                ("Website", "Website"),
            )
            if values[name].strip()
        )
        system = (
            "You write one short cold email for a human to review before it is sent.\n\n"
            f"WHAT IS BEING OFFERED:\n{product_docs}\n\n"
            f"WHO COUNTS AS A GOOD LEAD (already decided - do not re-qualify):\n{campaign_target}\n\n"
            "RULES:\n"
            "- Under 110 words in the body. Plain text. No markdown, no bullet lists.\n"
            "- Open with one specific, honest observation about THIS person's business drawn "
            "from the facts given. Never invent facts, numbers or customers.\n"
            "- The offer to make is the free funnel-leak diagnosis (a soft confirmation step "
            "before any project). One clear question as the call to action.\n"
            f"- Sign with the first name only: {operator_name or 'the sender'}.\n"
            + (f"- End with exactly this signature block:\n{signature}\n" if signature else "")
            + "- The subject: under 8 words, specific, no clickbait, no ALL CAPS.\n\n"
            "Return exactly this shape and nothing else:\n"
            "SUBJECT: <subject>\nBODY: <body>"
        )
        user = (
            f"{lead_block}\n\nWHY THEY MATCHED: {values['Match Reason'].strip()}\n\n"
            f"PROFILE FACTS: {values['Profile'].strip()[:1500]}"
        )
        try:
            subject, body = parse_draft(llm_write(system, user))
        except ValueError as exc:
            write_row(ws, number, {"Error": f"draft rejected: {exc}"}, index)
            print(f"[sheetflow] row {number}: {exc}", file=sys.stderr)
            continue
        write_row(ws, number, {"Draft Subject": subject, "Draft Body": body,
                               "Status": "Drafted", "Error": ""}, index)
        drafted += 1
        print(f"[sheetflow] row {number}: drafted for {values['First Name'].strip() or 'lead'}"
              f" at {values['Company'].strip() or '?'}", file=sys.stderr)
        time.sleep(2)

    print(f"[sheetflow] drafted {drafted} email(s) — review them in the sheet, "
          f"set Approved = YES on the ones to send")
    return 0


# ── Step 3: send approved ─────────────────────────────────────────


def cmd_send(limit: int = 10) -> int:
    """Send exactly the approved sheet text. Nothing is rewritten, nothing auto-sends."""
    with Bootstrap():
        config = require_env("OUTSEND_MAILBOX_ADDRESS", "OUTSEND_MAILBOX_PASSWORD")
    mailbox = config["OUTSEND_MAILBOX_ADDRESS"]
    password = config["OUTSEND_MAILBOX_PASSWORD"]
    from_name = os.environ.get("OUTSEND_OPERATOR_NAME", "").strip() or mailbox
    host = os.environ.get("OUTSEND_SMTP_HOST", "").strip() or "smtp.gmail.com"
    port = int(os.environ.get("OUTSEND_SMTP_PORT", "").strip() or "587")

    ws, index = open_sheet()
    pending = []
    for number, values in sheet_rows(ws, index):
        if values["Approved"].strip().upper() not in ("YES", "Y", "TRUE", "1"):
            continue
        if values["Status"].strip() in ("Sent", "Skipped"):
            continue
        if not values["Email"].strip() or not values["Draft Body"].strip():
            write_row(ws, number, {"Error": "approved but Email/Draft Body is empty"}, index)
            continue
        pending.append((number, values))

    if not pending:
        print("[sheetflow] nothing to send: no rows have Approved = YES "
              "(set YES on drafted rows you want mailed)")
        return 0
    pending = pending[:limit]
    print(f"[sheetflow] sending {len(pending)} approved email(s) from {mailbox}, "
          f"~1 minute apart", file=sys.stderr)

    failures = 0
    sent = 0
    for position, (number, values) in enumerate(pending):
        message = EmailMessage()
        message["From"] = formataddr((from_name, mailbox))
        message["To"] = values["Email"].strip()
        message["Reply-To"] = mailbox
        message["Subject"] = values["Draft Subject"].strip() or "(no subject)"
        message.set_content(values["Draft Body"].strip())

        try:
            with smtplib.SMTP(host, port, timeout=60) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(mailbox, password)
                server.send_message(message)
        except smtplib.SMTPException as exc:
            failures += 1
            write_row(ws, number, {"Status": "Send Failed", "Error": str(exc)[:400]}, index)
            print(f"[sheetflow] row {number}: send failed: {exc}", file=sys.stderr)
            if failures >= 3:
                print("[sheetflow] three failures in a row — stopping early", file=sys.stderr)
                break
        else:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + " UTC"
            write_row(ws, number, {"Status": "Sent", "Sent At": stamp, "Error": ""}, index)
            sent += 1
            print(f"[sheetflow] row {number}: sent to {values['Email'].strip()}", file=sys.stderr)

        if position < len(pending) - 1:
            time.sleep(random.randint(50, 80))

    print(f"[sheetflow] done: {sent} sent, {failures} failed")
    return 0 if failures < 3 else 1
