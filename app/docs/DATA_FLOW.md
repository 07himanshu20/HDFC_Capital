# How data flows: from the uploaded files to every number on the dashboard

```
 upload (zip or files)
   │  services/storage.py   safe unzip, lay out scheme_A_…/ scheme_B_…/ shared/, merge with the previous run if asked
   ▼
 classify                  catalog.py         every path matched to one of 52 document types (or reported as unrecognised)
   ▼
 parse                     parsing/extract.py one parser per document type; reads only its own file
   ▼
 post + reconcile          engine/books.py    journals, bank matching, trial balance, NAV, capital accounts, Tally bridge, checks R1–R19, S1–S2, G1
   ▼
 view model                engine/view.py     the exact `DATA` object the dashboard renders
   ▼
 persist                   services/ingest.py source_files, journals, journal_lines, bank_lines, trial_balance_lines,
                                              capital_accounts, rule_results, ingestion_runs.dashboard, nav_versions, audit_events
   ▼
 dashboard                 static/index.html  GET /api/dashboard; every action is POST /api/actions/<name>
```

A run either succeeds completely and becomes the current books, or fails and leaves the current books untouched.
The whole quarter (160 files, two schemes) processes in about 1.5 seconds.

## Which files from the zip are used

All **160 source files** under `dataset/Q2FY27/` are used, because the dashboard shows each of them (the *Data ingestion* page
lists them and every journal points back to one). 106 of them are parsed for values; the other 54 are evidence documents
(KYC packs, filing acknowledgements, term summaries) that are stored, hashed, previewed and linked from the calendar and KYC pages.

Two dataset-level files are **optional** and only used for acceptance testing:
`expected_results.json` (enables rule G1, golden totals) and `manifest.json` (enables the R20 manifest check).

Not used at runtime: `generator/` (made the synthetic files), `validation/` (its logic is ported into `engine/books.py`),
`docs/`, `README_dataset.md`.

## File → what is read → where it goes

Scheme A = GIFT IFSC, USD m. Scheme B = onshore, INR cr. "Both" means one file per scheme.

### Opening position and terms

| Document | Files | Read | Drives |
|---|---|---|---|
| Opening balances (locked) | `shared/Opening_Balances_30Jun26_locked.xlsx` | sheets `<A/B> Meta, TB, Instruments, Capital, Calls`: as-at date, unit, 30-Jun rate, opening TB, positions, capital accounts, prior calls | Quarter dates (as-at + 1 day → quarter end), opening trial balance, opening capital accounts, IRR cash flows; R1, R4, R11, R13, R14, R15 |
| PPM term sheet | `PPM_Term_Sheet_Scheme{A,B}.pdf` | `Key: value` lines: currency, target, commitments, fee rate, hurdle, carry, late-payment rate, single-investee limit, minimum corpus, par, tax name; header: registration no, trustee, manager | Scheme header, FX handling (non-INR currency), late-payment interest (R6), limits (R19), fee check (S2), carry |
| Investor register | `Investor_Register_Scheme{A,B}.xlsx` | `Investors` (commitment, class, WHT/TDS rate), `Classes`, `Closes`; Scheme B also `Side Letters` | Commitment weights for allocations, Class A fee base, tax rate check (R7), investor pages |
| Side-letter summary | `Side_Letter_Summary_SchemeA.xlsx` | clause rows | Investors page |
| KYC register | `KYC_Register_Scheme{A,B}.xlsx` | `KYC Register` (risk, PEP, last screening and refresh dates, status), `Documents` (type, file, received date, verified by), `Screening Log` (run date, lists, hits, disposition, reviewer), `FATCA-CRS` (status, reportable, self-certification file) | KYC page (register, document vault, screening log, reportable accounts, self-certifications, CKYC records), KYC gate (R17), refresh exceptions |
| Unit register | `Unit_Register_Scheme{A,B}.xlsx` | `Unit Ledger`, `Holdings` (units at quarter end) | Units check (R13) |

### Money in and out

| Document | Files | Read | Drives |
|---|---|---|---|
| Bank statement | A: `IBU_Statement_…mt940` (primary), `.csv`, `.pdf`; B: `Bank_Statement_…xls` (primary), `.pdf` | every line: date, narration, reference, amount, balance; PDF header and summary | Each journal's cash line is matched to exactly one bank line by narration pattern (`MF Q1FY27`, `INV <no>`, `CALL CG3 LP-A1`, `DISB I-A1 T2`, `LPI …`, `DIST DA1 …`, `CPN I-A1 Q2FY27`, `INT CR`, `CHGS`); R1, R2, R3 (all formats agree line by line) |
| Management-fee invoices | `FME_Fee_Invoice_Q1FY27.pdf`, `…Q2FY27.pdf` (A); `IM_Fee_Invoice_…` (B) | total, fee, GST, status | Q1: paid in July → FEE_PAY; Q2: unpaid → ACCR_FEE; S2 |
| Vendor invoices | `Vendor_Invoices_Q2FY27/*.pdf` | number, vendor, service, period, total, status | Paid → EXP_PAY (matched to bank); unpaid → ACCR_EXP (valuer to GL 5210, others 5200) |
| Capital call | `CapitalCall_CG3_Allocation.xlsx` (A), `CapitalCall_CB3_…` (B) + one notice PDF per investor | call sheet (notice, due, %), allocation rows (investment / fee / expense split) | CALL_ISSUE (GL 1400 / 3100 per investor), CALL_RCPT from bank, units issued, late days → LPI; R5, R6 |
| Distribution | `Distribution_DA1_Schedule.xlsx` (A), `…DB1…` (B) + notices; A also `…PaymentFile.csv` | declaration and payment dates, gross / tax / net per investor | DIST_DECL (3200 gross, 2300 net, 2500 tax), DIST_PAY from bank; R7 |
| Tax challan and certificates | `WHT_Deposit_Challan_DA1.pdf` + `WHT_Certificate_*.pdf` (A); `TDS_194LBB_Challan_DB1.pdf` + `Form16A_*.pdf` (B) | amount, deposit date, challan no | R7 (tax held as a liability at quarter end, cleared in October) |

### Portfolio

| Document | Files | Read | Drives |
|---|---|---|---|
| Deal master | `Deal_Master_Scheme{A,B}.xlsx` | `Instruments` (coupon, PIK, ISIN, SPV, security, RERA, homes), `Tranches` (date, INR, FX rate, units), `Covenants`, `Covenant basis` | DISB journals, coupon schedule (ACT/365 with tranche part-periods) → ACCR_INT, CPN_RCPT, ACCR_PIK, PIK_CAP; accrual history; R4, R8, R18 |
| Daily FX (A only) | `FX_Rates_USDINR_Daily_Jul-Sep26.csv` | reference rate, currency pair and source per day; must include the quarter's last day (the upload is refused otherwise) | Quarter-end translation (FX_TRANSL, GL 1220 / 4700); INR coupon and PIK accruals, PIK capitalised and valuer FV adjustments converted at the quarter-end rate; Tally memo-rate bridge; R9; the rates, pair, source and chart markers on the FX page |
| Custody | `Demat_Holding_Statement_…pdf`, `Demat_Transaction_Statement_…csv` | holdings at quarter end, credits | R4 |
| Valuation | `Valuation_Inputs_…xlsx` (`Summary`, `Inputs`, `Cover`), `Valuation_Report_…pdf` | fair value, FV adjustment, prior-cycle adjustment, yields, valuer notes, dates | VALUATION journals (GL 1210 / 4600), valuation page; R10 |
| Developer MIS | `Developer_MIS_<SPV>_<Mon>.xlsx` (6 per scheme, two layouts) | units sold, cumulative, sales value, collections, escrow, construction %, cost to date, cost to complete. Headers are found by synonym, so `Units sold` and `Nos. booked` map to the same field | Project monitoring, covenant tests; R18 |
| Covenant certificates | `Covenant_Certificate_<SPV>_30Sep26.pdf` | units sold, collections, test table | Breach flags (SPV-B2 breaches both); R18 |
| CP checklist, FC-GPR | `CP_Checklist_<instrument>_T<n>.xlsx`, `FCGPR_Acknowledgement_…pdf` | each condition with its met flag, date and evidence; FC-GPR allotment / due / filed / acknowledgement dates and number | Deals page (conditions in date order, filings table); S1 |
| Term summaries, advices, charge filing, pricing certificate | `DTD_Summary_*.pdf`, `CCD_Subscription_Summary_*.pdf`, `Tranche2_Disbursement_Advice_*.pdf`, `Charge_Filing_*.pdf`, `Pricing_Certificate_*.pdf` | `Instrument` name from the summaries; CHG-9 SRN, modification and filed dates, status (due = modification + 30 days); pricing certificate number and date; advices stored as evidence | Instrument long name; Deals page filings table |

### Books of record and compliance

| Document | Files | Read | Drives |
|---|---|---|---|
| Tally export | `Tally_Scheme{A,B}_DayBook_Q2FY27.xml`, `…_TrialBalance_30Sep26.xlsx`, `…_LedgerMasters.xlsx` | vouchers and lines, TB by ledger and group, ledger opening balances | Tally bridge: B is the statutory book (each voucher = one journal); A is cash-basis INR at the memo rate, every difference explained as M (memo rate), A (accrual) or F (FX); R11, R12 |
| Compliance calendar | `IFSCA_Compliance_Calendar_SchemeA.xlsx`, `SEBI_Compliance_Calendar_SchemeB.xlsx` | obligations, due dates, status, evidence file | Calendar, exceptions, breach-notice due date; R10, R16, R18 |
| Prior report as filed | `IFSCA_Quarterly_Report_Q1FY27_as_filed.xlsx`, `SEBI_Quarterly_Activity_Report_Q1FY27_as_filed.xlsx` (next quarter: the workbook the Report centre generated, e.g. `IFSCA_Quarterly_Report_Q2FY27.xlsx`) | title, layout note, NAV, drawn, cash, investments, commitments; Investments sheet (sector); Investors sheet (drawn per investor) | R15; the layout, sectors and prior drawn of this quarter's regulator report |
| Evidence | `Evidence/*.pdf`, KYC packs, `FATCA_CRS_SelfCert_*`, `AML_Policy_Extract.pdf`, `FINGate_…`, `CTR_FY26_extract.pdf`, `IFSCA_Q1FY27_Submission_Email.pdf`, `Form64C_Statement_*.pdf` | stored and hashed; read: `FINGate_…pdf` (FIU registration number, date, Principal Officer, Designated Director, status) and `KYC_Pack_…/NetWorth_Certificate.pdf` (investor, amount, date) | Calendar evidence (R16), KYC page (FIU registration card; the Form 61B line comes from the compliance calendar), file previews |

## Regulator report files (Report centre)

The IFSCA quarterly report (Scheme A) and the SEBI quarterly activity report (Scheme B) are generated as `.xlsx` files.

| Part of the workbook | Comes from |
|---|---|
| Sheet names, part headings, row labels, column headings, layout note | the prior quarter's report as filed (same layout, so the file can be uploaded next quarter as the prior report) |
| Part A: scheme name, registration, category, manager, period, currency | PPM term sheet, opening balances, period |
| Part B: target, commitments | PPM term sheet |
| Part B: cumulative drawn, undrawn, distributions | closing trial balance (GL 3100, 3200) |
| Part C: cash, investments at cost, fair-value adjustment, FX translation, liabilities, NAV | closing trial balance (1100, 1200, 1210, 1220, 2xxx); a line for accrued income and receivables (1300, 1400) is added only when it is not zero |
| Part D: prepared on / by, NAV version and approver, ingestion run | the workflow, at generation |
| Investments sheet | deal master and the books (principal, cost per instrument); sector from the prior report |
| Investors sheet | investor register (type, country, class, commitment); drawn = drawn in the prior report + this quarter's call |

Rules:
- The workbook is generated only from a **locked** NAV, by the finance maker, finance checker, Principal Officer or CRO.
- The model is built at ingestion (`engine/regreport.py`, stored as `reg_report` with the dashboard data), so the on-screen preview and the
  file show the same figures. Four ties are checked before the file is written (Part C adds up to the NAV, investor commitments and drawn
  add up, instrument cost adds up).
- The file is stored under `<STORAGE_DIR>/reports/<scheme>/<period>/` with its SHA-256, then **read back with the prior-report parser** and
  compared with the closing trial balance: NAV, drawn, cash, investments, commitments, the Part C total, and the totals of the
  Investors and Investments sheets (9 figures). Rule R15 turns from PARTIAL to PASS when all tie.
- Downloading checks the hash again; a file changed on disk is not served. Generation and every download are in the audit log.

## What is not in the files (organisation master data)

These live in the `settings` table (seeded from `seed/org_profile.json`, editable through `PUT /api/admin/profile`, applied from the next ingestion):

- Manager details shown in headers: SEBI and IFSCA registration of the manager, principal officer, compliance officer, AML officers, IR, CRO, addresses.
- Three provider display names that differ from what the files say: Scheme A bank label "First Gulf-India Bank, IBU GIFT City", Scheme B custodian "Deccan Custodial Services Ltd" (the demat statement names the DP, Deccan Securities DP Ltd).
- Investors' paying banks (the files carry SWIFT codes only).
- Journal numbering start per scheme (A-JV-0025, B-JV-0033: the sequence continues from earlier quarters).
- Scheme A coupon accruals of earlier quarters as booked in USD (Q4 FY26 at 88.50, Q1 FY27 booked at 0.7843). The INR amounts are recomputed from the deal master; only the USD booking is history.
- The name-screen term for check N1, and the header label (currently "HDFC Capital · GIFT IFSC").

The chart of accounts (24 GL codes) is part of the product (`engine/coa.py`), because the posting rules decide which accounts are used.
Users and roles are in the `users` table (seeded from `seed/users.json`). What each role may see and do is in `trackfund/access.py`
([ACCESS.md](ACCESS.md)); the server cuts the dashboard data down to each role's pages before sending it.

## Checks

The engine re-runs the validation suite's rules on every upload: R1–R19, S1, S2, and G1 when `expected_results.json` is supplied.
On the Q2 FY27 dataset: Scheme A 27 pass, Scheme B 24 pass, 0 fail, plus the open decisions shown as WARN (R19 single-investee limit,
S2 fee base) and R15 PARTIAL until the regulator workbook is generated from the locked NAV (then PASS). Three rules differ from the original demo on purpose:

| Original | In the product | Why |
|---|---|---|
| G2: brief Section 6.1 golden totals | removed | constants from the build brief, not a production control |
| R20: generator re-run gives identical hashes | R20: every stored file still matches the SHA-256 recorded at upload | there is no generator in production |
| R15: prior report ties to the opening books (PARTIAL) | also reads back this quarter's generated workbook and ties it to the closing books (PASS) | the regulator workbook is now generated |

`tests/test_engine.py` proves the rest: the dashboard data built from the raw files equals the original dashboard's embedded data
field by field (journals, bank lines, trial balances, NAV, capital accounts, instruments, accrual schedules, MIS, covenants, Tally
vouchers and bridge, obligations, investors, file register).

## Upload rules

- **Replace** (default for a zip with scheme folders): the upload is the complete quarter.
- **Merge** (default for loose files): the previous run's files are copied and the uploaded files laid over them. A document type
  that occurs once per quarter (bank statement, deal master, …) replaces the old file even if the name changed.
- A scheme whose NAV is approved (locked) cannot have its files changed; the upload is refused for that scheme.
- **Delete** (administrator only): the chosen files are removed from the current quarter and the books recomputed without them; the
  new run becomes current only if it succeeds. Required files and files of a locked quarter cannot be deleted. Each deletion is audited.
- The prior report is recognised as `<Name>_Q<n>FY<yy>_as_filed.xlsx` or as a generated `<Name>Report_Q<n>FY<yy>.xlsx`.
- When a scheme's files change, its NAV draft or submitted version is superseded by a new draft (v2, v3, …).

## Dates on the pages

No date or quarter label is typed into the dashboard page. Period captions (opening and closing dates, quarter start, the next quarter's label, the waterfall's hurdle date, the tranche of the quarter) come from `meta.period`, which the opening-balances workbook and the files set; every other date is read from the file that states it. `tests/test_pages.py` fails if a fixed date or quarter label is added to `index.html`.
