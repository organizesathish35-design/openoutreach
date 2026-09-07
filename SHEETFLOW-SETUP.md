# Sheet Console — setup (one time, ~10 minutes)

The pipeline now works through a **Google Sheet**:

```
1. Find + draft  (you click, GitHub Actions runs)   -> leads + AI drafts appear in the sheet
2. YOU review the sheet, edit drafts if you like, set Approved = YES
3. Send approved (you click)                        -> exactly those emails go out
```

Nothing is ever sent automatically. The weekly cron is gone.

## One-time setup

### 1. Create the Google Sheet
- Go to sheets.new, name it e.g. `AIM Leads`.
- Copy its ID from the URL: `https://docs.google.com/spreadsheets/d/<THIS_PART>/edit`

### 2. Create a service account (gives the automation access)
1. Open https://console.cloud.google.com/ , sign in, and create a project (any name, e.g. `aim-outreach`).
2. APIs & Services -> Library -> enable **Google Sheets API** (the Drive API is not needed).
3. APIs & Services -> Credentials -> **Create credentials -> Service account** -> name it `sheetflow` -> Done.
4. Open the service account -> Keys tab -> **Add key -> Create new key -> JSON** -> a `.json` file downloads.
5. Open the downloaded file, copy the `client_email` value (ends in `@...iam.gserviceaccount.com`).
6. In your Google Sheet: **Share** -> paste that email -> give it **Editor**. Uncheck "Notify people" -> Share.

### 3. Add two secrets to the GitHub repo
https://github.com/organizesathish35-design/openoutreach/settings/secrets/actions

| Secret name | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | paste the WHOLE service-account JSON file content |
| `SHEET_ID` | the sheet ID from step 1 |

(`OPENOUTREACH_ENV` already exists from before.)

## Daily use — everything online

- **Find + draft**: https://github.com/organizesathish35-design/openoutreach/actions/workflows/find-draft.yml
  -> Run workflow -> goal 5 (spends 5 credits for the addresses).
- Open your Google Sheet: new rows appear, then AI drafts fill in (a few minutes).
  Columns: name / title / company / email / **Match Reason** (why the AI picked them) / draft.
- Edit any draft cell directly if you want different wording (do it BEFORE approving).
- On rows you want mailed: set **Approved** = `YES`.
- **Send approved**: https://github.com/organizesathish35-design/openoutreach/actions/workflows/send-approved.yml
  -> Run workflow. Emails go out ~1 minute apart, exactly as written in the sheet.
  Status becomes `Sent` with a timestamp. Failures show in the Error column.

## Row status meanings

| Status | Meaning |
|---|---|
| `Found` | lead stored, address bought, draft pending |
| `Found - no email` | free find — no address yet (re-run find with credits to fill) |
| `Drafted` | AI draft ready for your review |
| `Sent` | mailed (Sent At shows when) |
| `Send Failed` | Gmail refused; see Error; send again by re-running the workflow |
| `Skipped` | you set this — the sender will never touch the row |

## Local (optional)

```powershell
.venv\Scripts\pip install gspread google-auth
$env:GOOGLE_SERVICE_ACCOUNT_JSON = "<paste json or set to file content>"
$env:SHEET_ID = "<sheet id>"
.venv\Scripts\python -m sheetflow find 3 --free   # no credits: rows without addresses
.venv\Scripts\python -m sheetflow draft
.venv\Scripts\python -m sheetflow send
```

## Good to know

- **Credits:** find buys 1 BetterContact credit per address. `--free` / local tests spend nothing.
- **Suppression:** the sheet is the ledger (`Sent` rows are never re-sent). If somebody says
  "no thanks", set their row to `Skipped` and never approve it again.
- **Drafts come from product.md + target.md** on the repo's main branch — edit those to change
  how the AI writes.
- **Sending is plain Gmail SMTP** with your app password, ~1 email/minute, max 10 per run
  (change the `limit` input). At this tiny volume that is the honest, simple path; the full
  warm-up machinery (`openoutreach run`) stays available for when you outgrow it.
