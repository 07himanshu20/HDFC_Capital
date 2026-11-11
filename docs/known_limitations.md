# Q2 FY27 build — status, decisions and known limitations

Status at 10 Nov 2026: **phase 1 of the build brief is done** (generator, native-format dataset, validation suite). Backend, parsers-as-services, UI, report exports, unit tests and the demo script are not started.

## What exists

| Item | State |
|---|---|
| `generator/` (`python -m generator --seed 20260930 --out dataset/Q2FY27`) | Done. 160 source files, two schemes, byte-identical on re-run (PDF dates and workbook timestamps normalised). |
| `dataset/Q2FY27/` with `manifest.json`, `expected_results.json`, `README_dataset.md` | Done. |
| `validation/run.py` → `validation_report.html` / `.json` | Done. Reads only the source files. 49 pass, 4 warn, 2 partial, 0 fail. |
| `schema.sql`, FastAPI backend, parser modules, UI pages, xlsx/PDF report exports, `tests/`, demo script | Not started. |

The validation suite was also run on a tampered copy (one coupon rate changed in the deal master, one amount changed in the bank CSV): eight rules failed, including NAV. The checks are not vacuous.

## Decisions needed from the finance team

Each of these comes from the brief's own figures. The dataset follows the brief's golden totals; the consequence is stated.

1. **Single-investee limit is exceeded on a commitments basis (R19 = WARN).** I-A1 costs USD 33.9185m = 28.3% of USD 120m commitments; I-B1 is INR 150 cr = 30.0% of INR 500 cr. Both are within 25% only if "investable funds" is read as target corpus (22.6% and exactly 25.0%). Either the limit basis, the tranche sizes or the commitments need to change, or the demo shows a limit breach.
2. **Management fee base (S2 = WARN).** The brief says 1.75% / 2.0% on commitments, Class A only, but its golden fee (USD 0.525m, INR 2.50 cr) is computed on total commitments including Class B. On Class A commitments only the fee would be USD 0.49875m and INR 2.375 cr. The dataset uses the golden figures and charges the whole fee to Class A.
3. **FC-GPR and pricing certificate for an NCD.** The brief asks for an FC-GPR acknowledgement and a CA pricing certificate for I-A1 tranche 2, which is a secured NCD. FC-GPR is the reporting form for equity instruments (it would fit the CCD, I-A2). The files are generated as the brief specifies; the correct FEMA route for the NCD needs confirming before this is shown to a client.
4. **Three open obligations are overdue on the default demo clock (05-Nov-2026):** quarterly portfolio disclosure (due 31-Oct), half-yearly AML/CFT sheet (due 31-Oct) and the SPV-B2 breach notice (due 14-Oct). The brief gives no completion date for them, so they are Open. They will show as overdue exceptions unless the clock or the statuses change.
5. **LP-A4 (FME class)** has 10% tax withheld on DA-1 but receives no certificate, as the brief specifies. Same for the sponsor's Form 16A in Scheme B.

## Arithmetic differences from the brief (all within the 0.0005 tolerance)

| Item | Brief | Dataset | Why |
|---|---|---|---|
| Scheme A opening accumulated loss | 1.0013 | 1.0011 | The brief's opening trial balance does not balance (out by 0.0002). |
| Scheme A opening NAV | 46.9987 | 46.9989 | Follows from the line above. |
| Scheme A quarter result | 1.0090 | 1.0088 | The brief's own components sum to 1.0088. |
| Scheme A closing TB, NAV 64.8077, bank 24,282,600.00, units 660,000 | — | identical | — |
| Q1 FY27 coupon in USD | 0.7843 | 0.7843 (kept) | INR 6.9808 cr at 89.00 rounds to 0.7844; the brief's figure is kept so opening cash is 18,123,200.00. |
| I-B2 PIK for Q2 | 1.2375 | 1.2374 | 81.8241 × 6% × 92/365 = 1.23745; closing principal is 83.0615 (brief 83.0616). |
| I-A1 coupon lines | 7.0575 + 2.1479 | total 9.2055 | The total is rounded once from the unrounded tranche amounts. |

## Conventions adopted

- **Rounding.** Every cash amount is the brief's four-decimal figure, so Scheme A cash moves in multiples of USD 100 and Scheme B in multiples of INR 1,000. Tranche 2 is remitted as USD 11,217,000.00, not 11,217,049.92.
- **Scheme A Tally** is kept on a cash basis at the single memo rate 89.40: no fee, expense, interest or call-receivable accruals and no FX translation. The bridge uses three codes: M (memo-rate restatement against the daily rate), A (accrual or receivable not in Tally), F (FX translation). Valuation and distribution journals are booked in Tally.
- **Tally trial balances** cover 1 Jul – 30 Sep with income and expense ledgers opening at zero and prior results in "Profit & Loss A/c". A real Tally company would carry the year from 1 April.
- **Scheme B history** was not given in full. Assumed: CB-1 on 15-Sep-2025 and CB-2 on 10-Nov-2025 (so the 20-Nov-2025 disbursement is funded), fees charged from 1 Oct 2025, vendor batch split trustee 0.12 / RTA 0.10 / legal 0.20, Q2 accrual split trustee 0.12 / RTA 0.10 / audit 0.16. Opening cash is INR 54.9531 cr and closing NAV INR 298.9544 cr.
- **Collection cover** is collections in the quarter divided by a covenant debt-service amount stated in the deal master (INR 36, 18, 30 and 20 cr). The brief gives only the ratios.
- **Breach-notice date** counts weekends only (14-Oct-2026). 2 October is a public holiday; with it the date is 15-Oct-2026.
- **KYC:** LP-B3's refresh is set to 15-Dec-2026 so Scheme B also has one refresh falling due.

## Files added beyond the brief's list

- `shared/Opening_Balances_30Jun26_locked.xlsx` — the locked 30-Jun trial balance, instrument positions, capital accounts and prior call dates. The validation suite needs a source for the opening position; Scheme A's Tally cannot supply it.
- `Evidence/*.pdf` in each scheme folder — one-page acknowledgements so every Filed/Done calendar row has evidence (R16).

## Authenticity limits

- PDF layouts are plausible issuer-style documents, not replicas. No redacted real statement, challan, FC-GPR or Tally export was available; narration style, MT940 field usage and Tally tags should be checked against real samples.
- Regulatory layouts (IFSCA quarterly report, SEBI activity report) and most regulatory due dates are reconstructed and carry a `verify` flag. They are not official formats.
- Not modelled: TDS on bank interest and on vendor/fee payments, GST input treatment, the purpose code in the bulk-payment file (`P9999` is a placeholder), GST treatment of IFSC invoices.
- Two Scheme B dates fall on a Sunday (fee payment 05-Jul-2026, declaration 20-Sep-2026), as in the brief.
- All names are invented, but they have not been checked against real people or registered entities.

## Validation scope notes

- **R15 is PARTIAL.** The Q2 regulatory reports are backend outputs and do not exist yet. The rule currently proves the Q1 "as filed" report ties to the locked opening books.
- **R12 for Scheme A** matches vouchers to journals on date, amount and cash leg, not on a shared reference.
- **The firm-name check** covers file names and all PDF, xlsx, csv, xml and MT940 text; the `.xls` bank download was not scanned.
- The ledger-to-GL mapping for Tally is a table inside `validation/run.py`. In the product it becomes the mapping a user accepts at ingestion.
