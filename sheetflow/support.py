"""Shared plumbing for the sheet console: config, the sheet itself, the LLM.

This is operator-side tooling, separate from the `openoutreach` package. It uses:
- the finder's tested contract (`python -m openoutreach find N emails --json`) for finding,
- the host's own config export for keys (so local runs read the saved row and cloud runs
  read the environment secret),
- plain SMTP for the one thing the approval gate needs that the sender does not offer:
  mailing *exactly* the text a human approved, rather than fresh copy it writes itself.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request

# One column vocabulary for the whole console. The header row is written from this,
# and every step addresses cells by header name, so reordering is safe.
COLUMNS = [
    "Lead ID", "First Name", "Last Name", "Title", "Company", "Website", "LinkedIn",
    "Email", "Match Reason", "Profile", "Status", "Draft Subject", "Draft Body",
    "Approved", "Sent At", "Error",
]

REQUIRED_HEADERS = set(COLUMNS)

PROFILE_CELL_LIMIT = 900


class Bootstrap:
    """The stored answers, applied to this process's environment.

    Order matters and mirrors the wizard's own rule — the environment set on
    purpose wins over the stored row:

    1. the OPENOUTREACH_ENV secret (cloud runs; parsed as KEY="VALUE" lines,
       quoted values may span lines with \\n escapes),
    2. the saved row via the host's own export (`apply_to_environment`, which
       uses setdefault).

    Locally the row holds the keys; in CI the row is empty and the secret
    carries them.
    """

    def __enter__(self):
        _seed_from_openoutreach_env()
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openoutreach.settings")
        import django

        django.setup()
        from django.db import DatabaseError

        try:
            from openoutreach import wizard
            from openoutreach.config.models import SiteConfig

            wizard.apply_to_environment(SiteConfig.load())
        except DatabaseError:
            pass  # no schema yet; the environment says what it has
        return os.environ

    def __exit__(self, *exc):
        return False


def _parse_env_text(text: str) -> dict[str, str]:
    """KEY=VALUE lines, double-quoted values, newlines escaped as \\n."""
    environment: dict[str, str] = {}
    lines, i = text.splitlines(), 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = re.sub(r"^export\s+", "", key.strip())
        value = value.strip()
        if value.startswith('"'):
            closed = value.endswith('"') and not value.endswith('\\"') and len(value) > 1
            while not closed and i < len(lines):
                following = lines[i]
                i += 1
                value += "\n" + following
                closed = following.rstrip().endswith('"') and not following.rstrip().endswith('\\"')
            inner = value[1:]
            end = inner.rfind('"')
            if end != -1:
                inner = inner[:end]
            value = inner.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
        environment[key] = value
    return environment


def _seed_from_openoutreach_env() -> None:
    text = os.environ.get("OPENOUTREACH_ENV", "")
    if not text.strip():
        return
    for key, value in _parse_env_text(text).items():
        os.environ.setdefault(key, value)


def require_env(*names: str) -> dict[str, str]:
    values = {name: os.environ.get(name, "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        sys.exit(f"sheetflow: missing configuration: {', '.join(missing)}")
    return values


# ── The sheet ──────────────────────────────────────────────────────


def open_sheet():
    """The first tab of the configured Google Sheet, headers ready."""
    import gspread
    from google.oauth2.service_account import Credentials

    config = require_env("GOOGLE_SERVICE_ACCOUNT_JSON", "SHEET_ID")
    creds = Credentials.from_service_account_info(
        json.loads(config["GOOGLE_SERVICE_ACCOUNT_JSON"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    ws = gspread.authorize(creds).open_by_key(config["SHEET_ID"]).sheet1

    header = ws.row_values(1)
    if not any(cell.strip() for cell in header):
        ws.update("A1", [COLUMNS])
        header = COLUMNS
    missing = REQUIRED_HEADERS - {cell.strip() for cell in header}
    if missing:
        sys.exit(f"sheetflow: sheet is missing column(s): {', '.join(sorted(missing))}")
    return ws, {name: i for i, name in enumerate(header)}


def sheet_rows(ws, index):
    """Every data row as (row_number, {column: value}). Blank tails are trimmed."""
    for number, row in enumerate(ws.get_all_values(), start=1):
        if number == 1:
            continue
        values = {
            name: (row[index[name]] if index[name] < len(row) else "")
            for name in index
        }
        if any(str(value).strip() for value in values.values()):
            yield number, values


def write_row(ws, number, updates: dict[str, str], index):
    """Set the named cells of one row in a single ranged update."""
    from gspread.utils import rowcol_to_a1

    columns = sorted(index[name] for name in updates)
    first, last = min(columns), max(columns)
    if last - first + 1 != len(updates):
        sys.exit("sheetflow: non-contiguous cell update requested")
    row = [""] * (last - first + 1)
    for name, value in updates.items():
        row[index[name] - first] = value
    a_first, a_last = rowcol_to_a1(number, first + 1), rowcol_to_a1(number, last + 1)
    ws.update(f"{a_first}:{a_last}", [row])


# ── The LLM ────────────────────────────────────────────────────────


def llm_write(system: str, user: str, *, max_retries: int = 3) -> str:
    """One chat completion through the OpenAI-compatible endpoint already configured."""
    config = require_env("OPENOUTFIND_LLM_API_KEY", "OPENOUTFIND_AI_MODEL")
    base = (os.environ.get("OPENOUTFIND_LLM_API_BASE", "").strip()
            or "https://openrouter.ai/api/v1").rstrip("/")
    model = config["OPENOUTFIND_AI_MODEL"]
    prefix = "openai_compatible:"
    if model.startswith(prefix):
        model = model[len(prefix):]

    payload = json.dumps({
        "model": model,
        "temperature": 0.7,
        "max_tokens": 700,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {config['OPENOUTFIND_LLM_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    last_error = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = json.loads(response.read().decode("utf-8"))
                return body["choices"][0]["message"]["content"]
        except Exception as exc:  # transient network/API errors: retry, then surface
            last_error = exc
            time.sleep(5 * (attempt + 1))
    sys.exit(f"sheetflow: LLM call failed after {max_retries} attempts: {last_error}")


DRAFT_SPLIT = re.compile(r"^SUBJECT:\s*(.*?)\s*BODY:\s*(.*)$", re.S | re.I)


def parse_draft(text: str) -> tuple[str, str]:
    """The model's 'SUBJECT: ... BODY: ...' reply as a (subject, body) pair."""
    match = DRAFT_SPLIT.match(text.strip())
    if not match:
        raise ValueError(f"reply did not follow the SUBJECT/BODY shape: {text[:120]!r}")
    subject, body = match.group(1).strip(), match.group(2).strip()
    if not subject or not body:
        raise ValueError("empty subject or body")
    return subject, body
