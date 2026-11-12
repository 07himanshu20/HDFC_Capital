"""Document catalog: the single list of every source file type the system accepts.

Each entry says how a file is recognised (pattern on its path inside the scheme folder), which
database tables it feeds, which dashboard page shows it, who normally produces it, and whether a
quarter cannot be processed without it.  This is the same mapping as dataset/Q2FY27/README_dataset.md;
the dashboard's file list is built from it.
"""
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DocType:
    key: str
    pattern: str
    feeds: tuple
    page: str
    who: str
    required: bool = False
    parsed: bool = True          # False = stored and hashed as evidence only
    label: str = ''

    def match(self, rel):
        return re.search(self.pattern, rel)


KYC = 'KYC / AML / FATCA'
DEALS = 'Deals, CPs & filings'
CAL = 'Calendar'

CATALOG = [
    # ---- prior period / masters ----
    DocType('opening_balances', r'(^|/)Opening_Balances_[^/]*\.xlsx$', ('period', 'journal', 'journal_line', 'capital_account'), 'Ledger & TB',
            'Fund administrator (audited prior period)', True, label='Locked opening balances (prior quarter)'),
    DocType('ppm_term_sheet', r'^PPM_Term_Sheet_[^/]*\.pdf$', ('scheme', 'scheme_term'), 'Investors & commitments', 'FME / fund counsel', True, label='PPM term sheet'),
    DocType('investor_register', r'^Investor_Register_[^/]*\.xlsx$', ('investor', 'commitment', 'unit_class'), 'Investors & commitments', 'Fund administrator / RTA', True,
            label='Investor register'),
    DocType('side_letters', r'^Side_Letter_Summary_[^/]*\.xlsx$', ('side_letter_term',), 'Investors & commitments', 'Fund counsel / IR', label='Side-letter summary'),
    DocType('kyc_register', r'^KYC_Register_[^/]*\.xlsx$', ('kyc_file', 'kyc_document', 'screening_log', 'fatca_crs'), KYC, 'FME compliance (AML PO)', True, label='KYC register'),
    DocType('deal_master', r'^Deal_Master_[^/]*\.xlsx$', ('project_spv', 'instrument', 'tranche', 'covenant_test'), 'Instruments & accruals / Deals, CPs & filings',
            'Investment team', True, label='Deal master'),
    DocType('unit_register', r'^Unit_Register_[^/]*\.xlsx$', ('unit_ledger',), 'Capital accounts', 'Fund administrator / RTA', True, label='Unit register'),
    # ---- bank and custody ----
    DocType('bank_mt940', r'^(IBU|Bank)_Statement_[^/]*\.mt940$', ('bank_account', 'bank_line'), 'Ingestion / Bank reconciliation', '{bank} - SWIFT MT940', label='Bank statement (MT940)'),
    DocType('bank_csv', r'^(IBU|Bank)_Statement_[^/]*\.csv$', ('bank_account', 'bank_line'), 'Ingestion / Bank reconciliation', '{bank} - CSV download', label='Bank statement (CSV)'),
    DocType('bank_xls', r'^(IBU|Bank)_Statement_[^/]*\.xls$', ('bank_account', 'bank_line'), 'Ingestion / Bank reconciliation', '{bank} - XLS download', label='Bank statement (XLS)'),
    DocType('bank_pdf', r'^(IBU|Bank)_Statement_[^/]*\.pdf$', ('bank_account', 'bank_line'), 'Bank & custody reconciliation', '{bank}', True, label='Bank statement (PDF)'),
    DocType('fx_rates', r'^FX_Rates_[^/]*\.csv$', ('fx_rate',), 'FX & translation', 'Rate feed (FBIL-style)', label='Daily FX rates'),
    DocType('demat_holding', r'^Demat_Holding_Statement_[^/]*\.pdf$', ('custody_account', 'custody_holding'), 'Bank & custody reconciliation', 'Custodian / DP', True,
            label='Demat holding statement'),
    DocType('demat_txn', r'^Demat_Transaction_Statement_[^/]*\.csv$', ('custody_txn',), 'Bank & custody reconciliation', 'Custodian / DP', True, label='Demat transaction statement'),
    # ---- fees and expenses ----
    DocType('fee_invoice', r'^(FME|IM)_Fee_Invoice_(?P<q>Q\dFY\d\d)\.pdf$', ('journal',), 'Quarter close & NAV', 'FME / investment manager', True, label='Management-fee invoice'),
    DocType('vendor_invoice', r'^Vendor_Invoices_[^/]+/[^/]*\.pdf$', ('journal',), 'Quarter close & NAV', '{vendor_who}', label='Vendor invoice / accrual note'),
    # ---- capital calls and distributions ----
    DocType('call_allocation', r'^CapitalCall_(?P<code>[A-Za-z0-9]+)_Allocation\.xlsx$', ('capital_call', 'call_allocation'), 'Capital calls', 'FME finance (maker) / checker', True,
            label='Capital-call allocation'),
    DocType('call_notice', r'^CapitalCall_(?P<code>[A-Za-z0-9]+)_Notice_[^/]*\.pdf$', ('capital_call', 'call_allocation'), 'Capital calls', 'FME / fund administrator',
            label='Capital-call notice'),
    DocType('dist_schedule', r'^Distribution_(?P<code>[A-Za-z0-9]+)_Schedule\.xlsx$', ('distribution', 'distribution_line', 'wht_entry'), 'Distributions',
            'FME finance (maker) / checker', True, label='Distribution schedule'),
    DocType('dist_notice', r'^Distribution_(?P<code>[A-Za-z0-9]+)_Notice_[^/]*\.pdf$', ('distribution', 'distribution_line'), 'Distributions', 'FME / fund administrator',
            label='Distribution notice'),
    DocType('dist_payment_file', r'^Distribution_(?P<code>[A-Za-z0-9]+)_PaymentFile\.csv$', ('distribution_line',), 'Distributions', 'FME finance - IBU bulk-payment upload',
            label='Bulk payment file'),
    DocType('tax_challan', r'^(WHT_Deposit_Challan|TDS_194LBB_Challan)_[^/]*\.pdf$', ('wht_entry', 'evidence'), 'Distributions', 'Authorised bank / tax portal', True,
            label='Tax deposit challan'),
    DocType('tax_certificate', r'^(WHT_Certificate|Form16A)_[^/]*\.pdf$', ('wht_entry',), 'Distributions', 'FME / deductor', label='Tax certificate'),
    DocType('form64c', r'^Form64C_Statement_[^/]*\.pdf$', ('distribution_line', 'report_run'), 'Report centre', 'FME tax team (draft)', parsed=False, label='Form 64C statement'),
    # ---- portfolio ----
    DocType('valuation_inputs', r'^Valuation_Inputs_[^/]*\.xlsx$', ('valuation_item',), 'Valuation', 'Independent registered valuer', True, label='Valuation inputs'),
    DocType('valuation_report', r'^Valuation_Report_[^/]*\.pdf$', ('valuation_cycle', 'valuation_item'), 'Valuation', 'Independent registered valuer', True, label='Valuation report'),
    DocType('developer_mis', r'^Developer_MIS_(?P<spv>SPV-[A-Za-z0-9]+)_(?P<mon>[A-Za-z]{3}\d\d)\.xlsx$', ('mis_month',), 'Project monitoring', 'Developer ({developer})', True,
            label='Developer monthly MIS'),
    DocType('covenant_cert', r'^Covenant_Certificate_(?P<spv>SPV-[A-Za-z0-9]+)_[^/]*\.pdf$', ('covenant_test',), 'Project monitoring', 'Developer CFO ({developer})', True,
            label='Covenant certificate'),
    DocType('instrument_summary', r'^(DTD_Summary|CCD_Subscription_Summary)_[^/]*\.pdf$', ('instrument',), DEALS, 'Fund counsel', label='Instrument term summary'),
    DocType('cp_checklist', r'^CP_Checklist_[^/]*\.xlsx$', ('cp_item',), DEALS, 'Investment team / legal', label='CP checklist'),
    DocType('tranche_advice', r'^Tranche\d+_Disbursement_Advice_[^/]*\.pdf$', ('tranche',), DEALS, 'FME finance', parsed=False, label='Disbursement advice'),
    DocType('charge_filing', r'^Charge_Filing_[^/]*\.pdf$', ('charge_filing', 'evidence'), DEALS, 'ROC / company secretary of the SPV', label='Charge filing'),
    DocType('fcgpr', r'^FCGPR_Acknowledgement_[^/]*\.pdf$', ('fema_filing', 'evidence'), DEALS, 'AD bank / RBI reporting portal', label='FC-GPR acknowledgement'),
    DocType('pricing_certificate', r'^Pricing_Certificate_[^/]*\.pdf$', ('evidence',), DEALS, 'Chartered accountant', label='Pricing certificate'),
    # ---- Tally ----
    DocType('tally_daybook', r'^Tally_[^/]*_DayBook_[^/]*\.xml$', ('tally_voucher',), 'Tally bridge', 'Client finance team (Tally export)', True, label='Tally day book (XML)'),
    DocType('tally_ledgers', r'^Tally_[^/]*_LedgerMasters\.xlsx$', ('tally_ledger_balance', 'gl_account'), 'Tally bridge', 'Client finance team (Tally export)', True,
            label='Tally ledger masters'),
    DocType('tally_tb', r'^Tally_[^/]*_TrialBalance_[^/]*\.xlsx$', ('tally_ledger_balance',), 'Tally bridge', 'Client finance team (Tally export)', True, label='Tally trial balance'),
    # ---- compliance ----
    DocType('calendar', r'^[A-Z]+_Compliance_Calendar_[^/]*\.xlsx$', ('obligation', 'evidence'), 'Calendar / Exceptions', 'FME compliance', True, label='Compliance calendar'),
    DocType('prior_report', r'^([A-Za-z_]+_Q\dFY\d\d_as_filed|[A-Za-z_]*Report_Q\dFY\d\d)\.xlsx$', ('report_run',), 'Report centre', 'FME compliance (prior filing)', True, label='Prior regulatory report (as filed)'),
    DocType('evidence_filing', r'^Evidence/[^/]*\.pdf$', ('evidence',), CAL, 'Regulator portal / mailbox', parsed=False, label='Filing acknowledgement'),
    DocType('submission_email', r'^[A-Z]+_Q\dFY\d\d_Submission_Email\.pdf$', ('evidence',), CAL, 'FME compliance mailbox', parsed=False, label='Submission e-mail'),
    DocType('ctr_extract', r'^CTR_[^/]*\.pdf$', ('evidence',), CAL, 'FME compliance', parsed=False, label='CTR extract'),
    DocType('aml_policy', r'^AML_Policy_[^/]*\.pdf$', ('evidence',), KYC, 'FME compliance', parsed=False, label='AML policy extract'),
    DocType('fingate', r'^FINGate_[^/]*\.pdf$', ('evidence',), KYC, 'FIU-IND portal', label='FIU-IND registration'),
    DocType('kyc_selfcert', r'^FATCA_CRS_SelfCert_[^/]*\.pdf$', ('kyc_document', 'evidence', 'fatca_crs'), KYC, 'Investor', parsed=False, label='FATCA/CRS self-certification'),
    DocType('kyc_bo', r'^KYC_Pack_[^/]+/BO_declaration\.pdf$', ('kyc_document', 'evidence'), KYC, 'Investor', parsed=False, label='KYC: BO declaration'),
    DocType('kyc_crs', r'^KYC_Pack_[^/]+/CRS_self_certification\.pdf$', ('kyc_document', 'evidence', 'fatca_crs'), KYC, 'Investor', parsed=False, label='KYC: CRS self-certification'),
    DocType('kyc_fatca', r'^KYC_Pack_[^/]+/FATCA_[^/]*\.pdf$', ('kyc_document', 'evidence', 'fatca_crs'), KYC, 'FME compliance', parsed=False, label='KYC: FATCA summary'),
    DocType('kyc_checklist', r'^KYC_Pack_[^/]+/checklist\.pdf$', ('kyc_document', 'evidence'), KYC, 'FME compliance', parsed=False, label='KYC: checklist'),
    DocType('kyc_screening', r'^KYC_Pack_[^/]+/screening_report\.pdf$', ('kyc_document', 'evidence', 'screening_log'), KYC, 'Screening vendor', parsed=False, label='KYC: screening report'),
    DocType('kyc_ckyc', r'^KYC_Pack_[^/]+/CKYC_record\.pdf$', ('kyc_document', 'evidence'), KYC, 'CKYC registry', parsed=False, label='KYC: CKYC record'),
    DocType('kyc_networth', r'^KYC_Pack_[^/]+/NetWorth_Certificate\.pdf$', ('kyc_document', 'evidence'), KYC, 'Chartered accountant', label='KYC: net-worth certificate'),
]

BY_KEY = {d.key: d for d in CATALOG}
BANK_TYPES = ('bank_mt940', 'bank_xls', 'bank_csv', 'bank_pdf')


def classify(rel):
    """rel: path inside the scheme folder (forward slashes). Returns (DocType, match) or (None, None)."""
    for d in CATALOG:
        m = d.match(rel)
        if m:
            return d, m
    return None, None


def required_types():
    return [d for d in CATALOG if d.required]
