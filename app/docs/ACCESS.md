# Roles and access

Every person signs in with their own account. The role decides which pages they see, which data the server sends to their
browser, which source files, exports and report files they can open, and which actions they can take. **Only the administrator
sees and does everything.** The single source of this table is `trackfund/access.py`; this file is generated from it.

How it is enforced (server side, not just hidden menus):

- `/api/dashboard` sends each role only the parts of the scheme data that its pages read (recorded by rendering every page), and
  only the investor fields those pages show. KYC-only fields (beneficial ownership, FATCA, GIIN, PEP) go only to roles with the KYC page.
- Source files open only for roles that can see a page the file is used on; KYC packs, for example, only for KYC roles.
- Exports, ingestion runs, report files and the audit log are refused to roles without the page they belong to.
- Actions are refused unless the role is listed below. Calendar obligations can be marked filed only by their owner role, the
  Principal Officer or the administrator.
- API responses are never cached by the browser, so the next person on a shared computer cannot see them.
- The administrator acts on everything, but maker-checker still holds: nobody approves a NAV they submitted. Nobody can change
  or delete the files of a locked quarter.

## Pages each role can open

| Page | Administrator | Finance maker | Finance checker | Principal Officer | Chief Risk Officer | AML officer | Investor relations | Investment team | Trustee | Auditor |
|---|---|---|---|---|---|---|---|---|---|---|
| **Overview** | | | | | | | | | | |
| Command centre | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Data** | | | | | | | | | | |
| Data ingestion | ✓ | ✓ | ✓ |  |  |  |  |  |  | ✓ |
| **Fund accounting** | | | | | | | | | | |
| Quarter close & NAV | ✓ | ✓ | ✓ | ✓ |  |  |  |  | ✓ | ✓ |
| Ledger & trial balance | ✓ | ✓ | ✓ |  |  |  |  |  |  | ✓ |
| Instruments & accruals | ✓ | ✓ | ✓ |  | ✓ |  |  | ✓ |  | ✓ |
| FX & translation | ✓ | ✓ | ✓ |  |  |  |  |  |  | ✓ |
| Valuation | ✓ | ✓ | ✓ |  | ✓ |  |  | ✓ | ✓ | ✓ |
| Capital accounts | ✓ | ✓ | ✓ |  |  |  | ✓ |  | ✓ | ✓ |
| Waterfall | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ | ✓ |
| Tally bridge | ✓ | ✓ | ✓ |  |  |  |  |  |  | ✓ |
| **Fund administration** | | | | | | | | | | |
| Investors | ✓ | ✓ | ✓ | ✓ |  | ✓ | ✓ |  | ✓ |  |
| KYC / AML / FATCA | ✓ |  |  | ✓ |  | ✓ |  |  |  |  |
| Capital calls | ✓ | ✓ | ✓ |  |  | ✓ | ✓ |  |  | ✓ |
| Distributions | ✓ | ✓ | ✓ |  |  | ✓ | ✓ |  |  | ✓ |
| Bank & custody | ✓ | ✓ | ✓ |  |  |  |  |  |  | ✓ |
| Deals, CPs & filings | ✓ |  |  | ✓ | ✓ |  |  | ✓ |  | ✓ |
| Approvals & controls | ✓ | ✓ | ✓ | ✓ |  |  |  |  | ✓ | ✓ |
| **Reporting** | | | | | | | | | | |
| Report centre | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  | ✓ | ✓ |
| Project monitoring | ✓ |  |  | ✓ | ✓ |  | ✓ | ✓ | ✓ |  |
| **Compliance** | | | | | | | | | | |
| Calendar | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Exceptions | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Audit log | ✓ |  | ✓ | ✓ |  |  |  |  | ✓ | ✓ |
| **Administration** | | | | | | | | | | |
| Users and access | ✓ |  |  |  |  |  |  |  |  |  |

## Actions each role can take

| Action | Administrator | Finance maker | Finance checker | Principal Officer | Chief Risk Officer | AML officer | Investor relations | Investment team | Trustee | Auditor |
|---|---|---|---|---|---|---|---|---|---|---|
| Submit the NAV for approval | ✓ | ✓ |  |  |  |  |  |  |  |  |
| Approve and lock the NAV | ✓ |  | ✓ |  |  |  |  |  | ✓ |  |
| Approve the valuation | ✓ |  | ✓ |  | ✓ |  |  |  |  |  |
| Test the period lock | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| Approve bank-detail changes | ✓ |  | ✓ |  |  |  |  |  |  |  |
| Mark obligations they own as filed | ✓ | ✓ | ✓ | ✓ |  | ✓ | ✓ | ✓ |  |  |
| Raise suspicious transaction reports | ✓ |  |  | ✓ |  | ✓ |  |  |  |  |
| Move STRs through review | ✓ |  |  | ✓ |  | ✓ |  |  |  |  |
| Accept column mappings | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| Issue covenant breach notices | ✓ |  |  | ✓ | ✓ |  | ✓ | ✓ |  |  |
| Generate reports | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |
| Generate the regulator workbook | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |
| Acknowledge and assign exceptions | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |
| Verify the audit chain | ✓ |  | ✓ | ✓ |  |  |  |  | ✓ | ✓ |
| Upload source files | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| Delete source files | ✓ |  |  |  |  |  |  |  |  |  |
| Manage users and roles | ✓ |  |  |  |  |  |  |  |  |  |

## Why each role sees what it sees

- **Finance maker**: prepares the books: ingestion, all of fund accounting, investor money flows (calls, distributions, bank), approvals queue, reports, calendar.
- **Finance checker**: same pages as the maker plus the audit log; approves the NAV, valuation and bank-detail changes.
- **Principal Officer**: the scheme's compliance: investors and KYC (and STRs), deals and filings, approvals, reports, covenant monitoring, calendar and audit log; sees the NAV status but not the ledger.
- **Chief Risk Officer**: portfolio risk: instruments, valuation (approves it), deals, covenant monitoring, calendar and exceptions.
- **AML officer**: KYC, screening and STRs, the investor register, and money moving in and out of investor accounts (calls, distributions).
- **Investor relations**: investors, their capital accounts, calls and distributions, investor reports and covenant breach notices.
- **Investment team**: instruments, valuation (read), deals and developer / covenant monitoring.
- **Trustee (read + approve)**: oversight: NAV (approves it), valuation, capital accounts, waterfall, investors, approvals, reports, covenants, calendar and audit log; otherwise read only.
- **Auditor (read only)**: the books and their evidence, read only: ingestion runs and source files, all of fund accounting, calls, distributions, bank, deals, approvals, reports, calendar, audit log. No investor KYC.

To change what a role can open or do, edit `ROLE_PAGES` / `ACTIONS` in `trackfund/access.py`; `tests/test_roles.py` checks the
table stays consistent and that no role receives data, files or actions outside it.
