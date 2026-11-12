# TrackFund: fund-operations software (backend, database, dashboard)

The client uploads the quarter's source files for its two schemes. The software classifies and parses them, posts the
double-entry books, reconciles bank, custody, Tally, valuation and covenants, and serves the dashboard with maker-checker NAV
approval, period lock, compliance calendar, KYC, reports and a hash-chained audit log.

- How every number traces back to a file: [docs/DATA_FLOW.md](docs/DATA_FLOW.md)
- Who can see and do what: [docs/ACCESS.md](docs/ACCESS.md)
- API reference (when running): `/api/docs`

## Run it locally

```bash
cd app
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
TRACKFUND_INITIAL_PASSWORD='choose-a-password' .venv/bin/python -m trackfund.cli init
.venv/bin/python -m trackfund.cli load ../dataset/Q2FY27            # or the zip: load ~/Downloads/Q2FY27_build_phase1.zip
PYTHONPATH=. .venv/bin/uvicorn trackfund.api:app --port 8000
```

Open http://localhost:8000 and sign in (users are in `seed/users.json`; the administrator is `admin`, the finance maker `pallav`,
the checker `renuka`; one user per role). Without `TRACKFUND_INITIAL_PASSWORD` a random password is written to `data/initial_credentials.txt`.
Local runs use SQLite in `data/`; set `DATABASE_URL` to use Postgres.

## Deploy for a client (Docker + Postgres)

```bash
cd app
cp .env.example .env          # set POSTGRES_PASSWORD, TRACKFUND_SECRET_KEY, TRACKFUND_INITIAL_PASSWORD
docker compose up -d --build
```

Put it behind HTTPS (your reverse proxy or load balancer) and set `TRACKFUND_COOKIE_SECURE=true`. Back up the two volumes:
`pgdata` (database) and `appdata` (uploaded files, which every journal points back to, and generated regulator reports). Run one app container: ingestion
and the audit chain are serialised inside the process.

Before the first start, review `seed/users.json` (people and roles) and `seed/org_profile.json` (manager details, header label,
provider names that the files do not carry). Both are loaded once into the database.

## Using it

1. **Upload**: Data ingestion → Upload files. A full quarter as one zip (`scheme_A_…/`, `scheme_B_…/`, `shared/`), or single
   files to correct one scheme. The log shows each scheme's journals, NAV and checks. A failed upload changes nothing.
   For a zip, the upload window shows a staged progress bar (zip extracting, classifying sheets, mapping, extracting data
   safely, cross check and validation, importing to dashboard, finished) that runs for `TRACKFUND_UPLOAD_PROGRESS_SECONDS`
   (default 20; the work itself takes a few seconds) and refreshes the dashboard at 100%. A failure stops the bar at its stage.
   Set it to 0 to show results as soon as they are ready.
2. **Review**: Reconciliation tab, exceptions, ledger (CSV exports), Tally bridge, valuation, covenants.
3. **Close**: the finance maker submits the NAV, a different person (finance checker or trustee) approves it. The quarter is
   then locked: back-dated posting and file changes for that scheme are refused.
4. **Report**: Report centre. The regulator report (IFSCA quarterly report / SEBI quarterly activity report) is generated as an
   `.xlsx` file from the locked NAV, read back and tied to the books, then downloaded for filing; next quarter it is uploaded as the
   prior report. The other reports are previews you print or save as PDF. Every action is in the audit log; Verify chain recomputes it.

Roles: ADMIN, PO, CRO, FIN_MAKER, FIN_CHECKER, AML_PO, IR, INV_TEAM, TRUSTEE_RO, AUDITOR_RO. Only the administrator sees every page
and can take every action; each other role sees only its own modules, and the server sends it only the data, files and exports of
those modules ([docs/ACCESS.md](docs/ACCESS.md)). The administrator manages users on **Users and access** (add, change role,
deactivate, reset password) and is the only one who can delete source files (Data ingestion → Delete files).

**Deleting files.** The administrator picks files of the current quarter; the books are recomputed without them and the result
becomes current only if that succeeds (otherwise nothing is deleted and the reason is shown). Required files (the only deal master,
bank statement, …) cannot be deleted: upload a corrected file instead, which replaces them. Nothing can be deleted from a locked
quarter. A NAV draft or submission is replaced by a new draft. Each deletion is in the audit log; earlier ingestion runs keep their
own copies of the files.

**Delete all files** (same window) clears the whole quarter: every file of both schemes and the shared opening balances. The
dashboard is then empty for every user ("No quarter loaded yet") until the quarter is uploaded again, which builds the books from
scratch with a new NAV draft per scheme; uploading the same zip gives the same books. It is refused while any scheme's quarter is
locked. The audit log records it for each scheme, and the ingestion runs list shows it as its own run.

## Tests

```bash
.venv/bin/python -m pytest -q
```

- `test_engine.py`: books rebuilt from the dataset equal `expected_results.json` exactly, no check fails, a tampered bank file is
  caught, the dashboard data equals the original demo's data field by field, and the regulator workbook keeps the filed layout, reads
  back and ties (a changed figure is caught).
- `test_roles.py`: for every role, the pages, data keys, investor fields, files, exports and actions it gets match the access
  table; the administrator gets everything; file deletion (refusals, success, failure that changes nothing); user administration.
- `test_api.py`: sign-in, CSRF header, upload permissions, upload, maker-checker, lock, refusal of changes to a locked quarter,
  regulator workbook (refused before lock and for other roles, generated, downloaded, hash-checked, R15 PASS), file access, path
  traversal, CSV export, user admin.

Both suites pass on SQLite and on PostgreSQL 16.

## Layout

```
trackfund/
  catalog.py            document types: filename pattern, tables fed, page, producer, required
  parsing/extract.py    one parser per document type
  engine/books.py       posting rules, bank matching, TB, NAV, capital accounts, Tally bridge, checks
  engine/view.py        dashboard view model
  engine/regreport.py   regulator report model, workbook writer, read-back check
  pipeline.py           upload folder -> all schemes -> dashboard data
  access.py             roles: pages, actions, and the data / files each role receives
  services/             storage (uploads), ingest (runs, persistence, file deletion), workflow (actions, audit chain), reports (regulator files)
  models.py             database schema
  api.py                HTTP API + front end
  static/index.html     dashboard
seed/                   first-start users and organisation profile
tests/
```

## Known limits

- The regulator workbooks use the layout of the reports as filed in the dataset, which the dataset itself marks as reconstructed
  from the circular and not an official format. Replace the layout when the regulator's current format workbook is obtained.
- The other reports (NAV statement, capital account statements, ILPA pack, tax registers, auditor pack, Form 61B) are on-screen
  previews to print or save as PDF; they are not generated as files.
- The parsers expect the file families in this dataset (names and layouts). A new bank or developer layout needs a parser
  entry in `catalog.py` and `parsing/extract.py`.
- One quarter is processed per upload. The opening-balances workbook for the next quarter must come from the locked books
  of the previous one.
- The open decisions in `../docs/known_limitations.md` (single-investee limit basis, fee base, FC-GPR for an NCD, missing tax
  certificates) still show as WARN, as in the demo.
