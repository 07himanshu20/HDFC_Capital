#!/usr/bin/env python3
"""Reconciliation and validation suite (brief Section 7).
Reads ONLY the generated source files, rebuilds the books with its own posting rules, checks R1-R20
and compares the result with expected_results.json.  Usage: python validation/run.py [dataset_dir] [--skip-determinism]"""
import sys, os, re, csv, json, glob, hashlib, subprocess, tempfile, html
from decimal import Decimal as D, ROUND_HALF_UP
from datetime import datetime, date, timedelta
import openpyxl, pdfplumber, mt940, xlrd
import xml.etree.ElementTree as ET

ROOT = next((a for a in sys.argv[1:] if not a.startswith('--')), 'dataset/Q2FY27')
Q_START, Q_END, OPEN_DT = date(2026, 7, 1), date(2026, 9, 30), date(2026, 6, 30)
TOL = D('0.0005'); MEMO = D('89.40')
CFG = {'A': dict(folder='scheme_A_gift', short='SchemeA', scale=D(1000000), ccy='USD', call='CG3', dist='DA1', bank='IBU_Statement_SchemeA_USD_Jul-Sep26',
                 cal='IFSCA_Compliance_Calendar_SchemeA.xlsx', q1='IFSCA_Quarterly_Report_Q1FY27_as_filed.xlsx', challan='WHT_Deposit_Challan_DA1.pdf', cert='WHT_Certificate_*.pdf', fee='FME'),
       'B': dict(folder='scheme_B_onshore', short='SchemeB', scale=D(10000000), ccy='INR', call='CB3', dist='DB1', bank='Bank_Statement_SchemeB_INR_Jul-Sep26',
                 cal='SEBI_Compliance_Calendar_SchemeB.xlsx', q1='SEBI_Quarterly_Activity_Report_Q1FY27_as_filed.xlsx', challan='TDS_194LBB_Challan_DB1.pdf', cert='Form16A_*.pdf', fee='IM')}
TYPE = {1100: 'a', 1200: 'a', 1210: 'a', 1220: 'a', 1300: 'a', 1400: 'a', 2100: 'l', 2200: 'l', 2300: 'l', 2500: 'l', 3100: 'e', 3200: 'e', 3900: 'e'}
CAT = {4100: 'income', 4110: 'income', 4200: 'income', 4500: 'income', 4600: 'fv', 4700: 'fx', 5100: 'fee', 5200: 'expense', 5210: 'expense', 5300: 'expense'}


def q(x, p=4): return D(x).quantize(D(1).scaleb(-p), ROUND_HALF_UP)
def num(s):
    if s is None or s == '': return D(0)
    if isinstance(s, (int, float)): return D(str(round(s, 6)))
    return D(str(s).replace(',', '').replace('%', '').strip() or '0')
def dt(s):
    if isinstance(s, datetime): return s.date()
    if isinstance(s, date): return s
    s = str(s).strip()
    for f in ('%d-%b-%Y', '%d/%m/%Y', '%d-%m-%Y'):
        try: return datetime.strptime(s, f).date()
        except ValueError: pass
    raise ValueError(s)
def nows(s): return re.sub(r'\s+', '', s or '')
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def pdf_text(p):
    with pdfplumber.open(p) as f: return '\n'.join(pg.extract_text() or '' for pg in f.pages)
def pdf_kv(p):
    out = {}
    for ln in pdf_text(p).split('\n'):
        if ': ' in ln:
            k, v = ln.split(': ', 1); out.setdefault(k.strip(), v.strip())
    return out
def pdf_tables(p):
    with pdfplumber.open(p) as f: return [t for pg in f.pages for t in pg.extract_tables()]
def xl_kv(p, sheet):
    ws = openpyxl.load_workbook(p, data_only=True)[sheet]
    return {str(r[0]).strip(): r[1] for r in ws.iter_rows(values_only=True) if r[0] is not None and len(r) > 1 and r[1] is not None}
def xl_table(p, sheet, must):
    """locate the header row by content (not position) and return rows as dicts with their sheet row number"""
    ws = openpyxl.load_workbook(p, data_only=True)[sheet]; rows = list(ws.iter_rows(values_only=True))
    for hi, r in enumerate(rows):
        cells = [str(c).strip() if c is not None else '' for c in r]
        if sum(1 for c in cells if c) >= 2 and all(any(m.lower() in c.lower() for c in cells) for m in must):
            out = []
            for k, rr in enumerate(rows[hi + 1:], hi + 2):
                if rr[0] is None: break
                d = dict(zip(cells, rr)); d['_row'] = k; out.append(d)
            return out
    raise KeyError(f'{p}:{sheet}: header {must} not found')
def col(row, *keys):
    for k in row:
        if all(x.lower() in k.lower() for x in keys): return row[k]
    raise KeyError(keys)


class Res:
    def __init__(s): s.rows = []
    def add(s, rule, scheme, title, ok, left, right, detail='', src='', status=None):
        s.rows.append(dict(rule=rule, scheme=scheme, title=title, status=status or ('PASS' if ok else 'FAIL'), left=str(left), right=str(right), detail=detail, src=src))
R = Res()
def eq(a, b, tol=TOL): return abs(D(a) - D(b)) <= tol


def prorate(total, w, p=6):
    tw = sum(w.values()); out = {k: q(total * v / tw, p) for k, v in w.items()}
    k = max(w, key=lambda z: (w[z], z)); out[k] += q(total, p) - sum(out.values()); return out
def xirr(flows):
    t0 = min(d for d, _ in flows); f = lambda r: sum(float(a) / (1 + r) ** ((d - t0).days / 365.0) for d, a in flows); lo, hi = -0.99, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0: hi = mid
        else: lo = mid
    return round((lo + hi) / 2, 6)
def carry_on_liquidation(nav, calls, dists, hurdle, carry):
    g = lambda d, a: float(a) * (1 + float(hurdle)) ** ((Q_END - d).days / 365.0)
    paid = sum(a for _, a in calls); dist = sum(a for _, a in dists)
    hurdle_amt = max(D(str(round(sum(g(d, a) for d, a in calls) - sum(g(d, a) for d, a in dists), 6))) - (paid - dist), D(0))
    rem = max(D(nav) - (paid - dist), D(0)); t2 = min(rem, hurdle_amt); rem -= t2
    cu = min(rem, q(hurdle_amt * carry / (1 - carry), 6)); rem -= cu
    return q(cu + rem * carry, 6)
def led2gl(n):
    for k, g in (('Interest on Bank', 4200), ('Bank Charges', 5300), ('Investment in', 1200), ('Fair Value Adjustment', 1210), ('Interest Accrued', 1300), ('Call Money', 1400),
                 ('Management Fee Payable', 2100), ('Expenses Payable', 2200), ('Distribution Payable', 2300), ('WHT Payable', 2500), ('TDS Payable', 2500), ('Unit Capital', 3100),
                 ('Distribution to Unitholders', 3200), ('Profit & Loss', 3900), ('PIK Interest', 4110), ('Interest on NCD', 4100), ('Late Payment Interest', 4500), ('Unrealised Gain', 4600),
                 ('Management Fees', 5100), ('Valuation Fees', 5210), ('Trusteeship', 5200), ('Administration', 5200), ('RTA Fees', 5200), ('Legal', 5200), ('Audit', 5200), ('Organisation', 5200)):
        if k in n: return g
    if 'Bank' in n and 'A/c' in n: return 1100
    raise KeyError(n)


def run(sid, manifest, expected):
    C = CFG[sid]; A = sid == 'A'; F = os.path.join(ROOT, C['folder']); P = lambda n: os.path.join(F, n); sc = C['scale']
    u = lambda base: D(base) / sc                                   # base currency -> scheme unit (m / cr)
    add = lambda rule, title, ok, l, r, detail='', src='', status=None: R.add(rule, sid, title, ok, l, r, detail, src, status)
    # ---------------- load masters ----------------
    OB = os.path.join(ROOT, 'shared/Opening_Balances_30Jun26_locked.xlsx')
    open_tb = {int(r['GL code']): num(r['Balance']) for r in xl_table(OB, f'{sid} TB', ['GL code', 'Balance'])}
    open_ins = {r['Instrument ID']: r for r in xl_table(OB, f'{sid} Instruments', ['Instrument ID', 'Principal'])}
    open_cap = {r['Investor ID']: r for r in xl_table(OB, f'{sid} Capital', ['Investor ID', 'Units'])}
    hist_calls = [(dt(r['Due date']), num(col(r, 'Amount'))) for r in xl_table(OB, f'{sid} Calls', ['Call', 'Due date'])]
    inv = {r['Investor ID']: dict(cls=r['Unit class'], commit=u(num(col(r, 'Commitment'))), wht=num(col(r, 'rate')), name=r['Legal name'])
           for r in xl_table(P(f"Investor_Register_{C['short']}.xlsx"), 'Investors', ['Investor ID', 'Commitment'])}
    terms = pdf_kv(P(f"PPM_Term_Sheet_{C['short']}.pdf")); par = num(terms[f"Unit par value ({C['ccy']})"])
    committed = sum(i['commit'] for i in inv.values()); w = {k: v['commit'] for k, v in inv.items()}
    DM = P(f"Deal_Master_{C['short']}.xlsx")
    ins = {r['Instrument ID']: dict(isin=r['ISIN'], kind=r['Kind'], cash=num(col(r, 'Cash coupon')) / 100, pik=num(col(r, 'PIK coupon')) / 100, spv=r['Project SPV']) for r in xl_table(DM, 'Instruments', ['Instrument ID', 'ISIN'])}
    tranches = [dict(ins=r['Instrument ID'], no=int(r['Tranche no']), date=dt(r['Disbursement date']), inr=num(col(r, 'Amount (INR cr)')), rate=num(col(r, 'FX rate')) if A else D(1),
                     units=int(r['Units allotted']), demat=dt(r['Demat credit date']), row=r['_row']) for r in xl_table(DM, 'Tranches', ['Instrument ID', 'Tranche no'])]
    cov_terms = xl_table(DM, 'Covenants', ['Instrument ID', 'Test', 'Minimum']); cov_ds = {r['Instrument ID']: num(col(r, 'debt service')) for r in xl_table(DM, 'Covenant basis', ['Instrument ID', 'debt service'])}
    fx = {}
    if A:
        with open(P('FX_Rates_USDINR_Daily_Jul-Sep26.csv')) as f:
            for r in csv.DictReader(f): fx[dt(r['Date'])] = D(r['Reference Rate'])
    fxon = lambda d: fx[max(k for k in fx if k <= d)]
    fn = lambda inr, rate: q(inr * 10 / rate) if A else D(inr)
    # ---------------- bank: three (A) / two (B) native formats ----------------
    def from_pdf():
        out = []
        for t in pdf_tables(P(C['bank'] + '.pdf')):
            for r in t[1:]:
                r = [(c or '').replace('\n', ' ') for c in r]
                if 'TOTAL' in r[0] or 'OPENING' in ' '.join(r): continue
                n = len(r); dr, cr, bal = num(r[n - 3]), num(r[n - 2]), num(r[n - 1])
                out.append(dict(date=dt(r[0].replace(' ', '')), narr=r[2 if A else 1], ref=r[3 if A else 2], amt=cr - dr, bal=bal))
        return out
    bank_pdf = from_pdf(); kvb = pdf_kv(P(C['bank'] + '.pdf')); open_bank = num(kvb['Opening balance as on 30-Jun-2026'])
    if A:
        raw = open(P(C['bank'] + '.mt940')).read().replace('\r\n', '\n'); tr = mt940.parse(raw)
        cl = {datetime.strptime(m[0], '%y%m%d').date(): D(m[1].replace(',', '.')) for m in re.findall(r':62F:C(\d{6})USD([\d,]+)', raw)}
        op60 = D(re.search(r':60F:C260630USD([\d,]+)', raw).group(1).replace(',', '.'))
        bank = []; bal = op60
        for k, t in enumerate(tr):
            a = t.data['amount'].amount; bal += a
            bank.append(dict(date=t.data['date'], narr=t.data['transaction_details'].replace('\n', ''), ref=t.data['customer_reference'], amt=a, bal=bal, loc=f":61: #{k + 1}"))
        day_ok = all(next(b['bal'] for b in reversed(bank) if b['date'] == d) == v for d, v in cl.items())
        rows = list(csv.reader(open(P(C['bank'] + '.csv')))); hi = next(i for i, r in enumerate(rows) if r and r[0] == 'Txn Date')
        bank_csv = [dict(date=dt(r[0]), narr=r[2], ref=r[3], amt=num(r[5]) - num(r[4]), bal=num(r[6])) for r in rows[hi + 1:] if r]
        others = {'PDF': bank_pdf, 'CSV': bank_csv}; prim = 'MT940'
        add('R3', 'MT940 opening :60F: = PDF opening; daily :62F: = running balance', op60 == open_bank and day_ok, op60, open_bank, f"{len(cl)} daily :62F: balances checked", C['bank'] + '.mt940 / .pdf')
    else:
        ws = xlrd.open_workbook(P(C['bank'] + '.xls')).sheet_by_index(0); hi = next(i for i in range(ws.nrows) if ws.cell_value(i, 0) == 'Date')
        bank = []
        for i in range(hi + 2, ws.nrows):
            v = ws.row_values(i); bank.append(dict(date=dt(v[0]), narr=v[1], ref=v[2], amt=num(v[4]) - num(v[3]), bal=num(v[5]), loc=f"Statement!row {i + 1}"))
        add('R3', 'XLS opening balance = PDF opening balance', num(ws.cell_value(hi + 1, 5)) == open_bank, num(ws.cell_value(hi + 1, 5)), open_bank, '', C['bank'] + '.xls / .pdf')
        others = {'PDF': bank_pdf}; prim = 'XLS'
    for nm, o in others.items():
        same = len(o) == len(bank) and all(a['date'] == b['date'] and a['amt'] == b['amt'] and a['bal'] == b['bal'] and nows(a['narr']) == nows(b['narr']) and a['ref'] == b['ref'] for a, b in zip(o, bank))
        add('R3', f'{prim} = {nm}: line count, dates, refs, narrations, amounts, balances', same, f"{len(bank)} lines, net {sum(b['amt'] for b in bank):,.2f}", f"{len(o)} lines, net {sum(b['amt'] for b in o):,.2f}", '', f"{C['bank']}.{nm.lower()}")
    add('R3', 'PDF summary: closing balance and transaction count', num(kvb['Closing balance as on 30-Sep-2026']) == bank[-1]['bal'] and int(kvb['Number of transactions']) == len(bank), kvb['Closing balance as on 30-Sep-2026'], f"{bank[-1]['bal']:,.2f}", '', C['bank'] + '.pdf')
    # ---------------- posting engine (independent of the generator) ----------------
    J = []; used = set()
    def post(d, kind, ref, lines, src):
        assert sum(a for _, a, _ in lines) == 0, (kind, ref, lines)
        J.append(dict(date=d, kind=kind, ref=ref, lines=[dict(gl=g, amt=D(a), **m) for g, a, m in lines], src=src, bank=None))
        return J[-1]
    def find(pattern):
        hits = [(k, b, re.search(pattern, b['narr'])) for k, b in enumerate(bank) if k not in used and re.search(pattern, b['narr'])]
        return hits
    def cash(j, k): used.add(k); j['bank'] = k
    issues = []
    # fees and vendor invoices
    fee_inv = {}
    for ql in ('Q1FY27', 'Q2FY27'):
        k = pdf_kv(P(f"{C['fee']}_Fee_Invoice_{ql}.pdf")); k['_file'] = f"{C['fee']}_Fee_Invoice_{ql}.pdf"; fee_inv[ql] = k
    vend = []
    for p in sorted(glob.glob(P('Vendor_Invoices_Q2FY27/*.pdf'))):
        k = pdf_kv(p); k['_file'] = os.path.relpath(p, F); vend.append(k)
    tot_key = f"Invoice total ({C['ccy']})"
    for ql, k in fee_inv.items():
        amt = u(num(k[tot_key]))
        if k['Status'].startswith('Paid'):
            h = find(rf"MF {ql}")
            if len(h) == 1 and u(-h[0][1]['amt']) == amt: cash(post(h[0][1]['date'], 'FEE_PAY', f"MF/{ql}", [(2100, amt, {}), (1100, -amt, {})], k['_file']), h[0][0])
            else: issues.append(f"fee {ql} payment not found in bank")
        else: post(Q_END, 'ACCR_FEE', f"ACCR/MF/{ql}", [(5100, amt, {}), (2100, -amt, {})], k['_file'])
    for k in vend:
        amt = u(num(k[tot_key])); gl = 5210 if k['Service'] == 'valuer' else 5200
        if k['Status'].startswith('Paid'):
            h = find(re.escape(f"INV {k['Invoice No']}") + r'(?!\d)')
            if len(h) == 1 and u(-h[0][1]['amt']) == amt: cash(post(h[0][1]['date'], 'EXP_PAY', f"INV/{k['Invoice No']}", [(2200, amt, {}), (1100, -amt, {})], k['_file']), h[0][0])
            else: issues.append(f"invoice {k['Invoice No']} payment not found in bank")
        else: post(Q_END, 'ACCR_EXP', f"ACCR/{k['Invoice No']}", [(gl, amt, {}), (2200, -amt, {})], k['_file'])
    # capital call
    CA_ = P(f"CapitalCall_{C['call']}_Allocation.xlsx"); ck = xl_kv(CA_, 'Call'); call_rows = xl_table(CA_, 'Allocation', ['Investor ID', 'Amount called'])
    call_rows = [r for r in call_rows if str(r['Investor ID']).startswith('LP-')]
    called = {r['Investor ID']: u(num(r['Amount called'])) for r in call_rows}; call_notice, call_due = dt(ck['Notice date']), dt(ck['Due date'])
    post(call_notice, 'CALL_ISSUE', f"{C['call']}/ISSUE", [(1400, sum(called.values()), {})] + [(3100, -a, {'investor': k}) for k, a in called.items()], 'CapitalCall_%s_Allocation.xlsx Allocation' % C['call'])
    receipts = {}; units_new = {}
    for k, b, m in find(rf"CALL {C['call']} (LP-\w+)"):
        i = m.group(1); a = u(b['amt']); receipts[i] = dict(date=b['date'], amt=a, late=(b['date'] - call_due).days)
        cash(post(b['date'], 'CALL_RCPT', f"{C['call']}/{i}", [(1100, a, {}), (1400, -a, {'investor': i})], f"bank {b['loc']}"), k); units_new[i] = int(a * sc / par)
    lpi = {}
    for k, b, m in find(rf"LPI {C['call']} (LP-\w+)"):
        i = m.group(1); a = u(b['amt']); lpi[i] = a
        cash(post(b['date'], 'LPI', f"LPI/{C['call']}/{i}", [(1100, a, {}), (4500, -a, {})], f"bank {b['loc']}"), k)
    # disbursements in the quarter
    cost = {k: num(col(v, 'Cost')) for k, v in open_ins.items()}; principal = {k: num(col(v, 'Principal')) for k, v in open_ins.items()}; qty = {k: int(v['Quantity']) for k, v in open_ins.items()}
    q_tr = [t for t in tranches if Q_START <= t['date'] <= Q_END]; fx_checks = []
    for t in q_tr:
        amt = fn(t['inr'], t['rate']); h = find(rf"DISB {t['ins']} T{t['no']}")
        if A: fx_checks.append((f"Disbursement {t['ins']} T{t['no']} {t['date']:%d-%b}", t['rate'], fx.get(t['date'])))
        if len(h) == 1 and u(-h[0][1]['amt']) == amt and h[0][1]['date'] == t['date']:
            cash(post(t['date'], 'DISB', f"DISB/{t['ins']}/T{t['no']}", [(1200, amt, {'instrument': t['ins']}), (1100, -amt, {})], f"Deal_Master Tranches!row {t['row']}"), h[0][0])
        else: issues.append(f"disbursement {t['ins']} T{t['no']} not matched in bank")
        cost[t['ins']] += amt; qty[t['ins']] += t['units']
    # distribution
    DS = P(f"Distribution_{C['dist']}_Schedule.xlsx"); dk = xl_kv(DS, 'Distribution'); drows = [r for r in xl_table(DS, 'Schedule', ['Investor ID', 'Gross', 'Net paid']) if str(r['Investor ID']).startswith('LP-')]
    dist = {r['Investor ID']: dict(gross=u(num(r['Gross'])), income=u(num(r['Income'])), rate=num(col(r, 'rate')), wht=u(num(col(r, 'amount'))), net=u(num(r['Net paid']))) for r in drows}
    decl, payd = dt(dk['Declaration date']), dt(dk['Payment date']); twht = sum(d['wht'] for d in dist.values()); tgross = sum(d['gross'] for d in dist.values())
    post(decl, 'DIST_DECL', f"{C['dist']}/DECL", [(3200, d['gross'], {'investor': k}) for k, d in dist.items()] + [(2300, -(tgross - twht), {}), (2500, -twht, {})], f"Distribution_{C['dist']}_Schedule.xlsx Schedule")
    paid_net = {}
    for k, b, m in find(rf"DIST {C['dist']} (LP-\w+)"):
        i = m.group(1); a = u(-b['amt']); paid_net[i] = dict(amt=a, date=b['date'])
        cash(post(b['date'], 'DIST_PAY', f"{C['dist']}/{i}", [(2300, a, {'investor': i}), (1100, -a, {})], f"bank {b['loc']}"), k)
    # coupons / PIK: accrual schedule recomputed from terms (ACT/365, day after allotment to period end inclusive)
    sched = {}; rate_end = fx[Q_END] if A else D(1)
    for k, x in ins.items():
        if not (x['cash'] or x['pik']): continue
        segs = [(principal[k], (Q_END - OPEN_DT).days)] + [(t['inr'], (Q_END - t['date']).days) for t in q_tr if t['ins'] == k]
        c_inr = q(sum(p * x['cash'] * n / 365 for p, n in segs)); p_inr = q(sum(p * x['pik'] * n / 365 for p, n in segs)); c_fn = fn(c_inr, rate_end)
        sched[k] = dict(cash_inr=c_inr, pik=p_inr, cash_fn=c_fn, segs=segs)
        post(Q_END, 'ACCR_INT', f"ACCR/{k}/Q2FY27", [(1300, c_fn, {'instrument': k}), (4100, -c_fn, {'instrument': k})], 'Deal_Master Instruments + Tranches (recomputed)')
        h = find(rf"CPN {k} Q2FY27")
        if len(h) == 1 and u(h[0][1]['amt']) == c_fn:
            cash(post(Q_END, 'CPN_RCPT', f"CPN/{k}/Q2FY27", [(1100, c_fn, {}), (1300, -c_fn, {'instrument': k})], f"bank {h[0][1]['loc']}"), h[0][0]); sched[k]['narr'] = h[0][1]['narr']
        else: issues.append(f"coupon {k} not matched in bank (expected {c_fn})")
        if p_inr:
            post(Q_END, 'ACCR_PIK', f"PIK/{k}/Q2FY27", [(1300, p_inr, {'instrument': k}), (4110, -p_inr, {'instrument': k})], 'Deal_Master (recomputed)')
            post(Q_END, 'PIK_CAP', f"PIKCAP/{k}/Q2FY27", [(1200, p_inr, {'instrument': k}), (1300, -p_inr, {'instrument': k})], 'Deal_Master (recomputed)')
            cost[k] += p_inr
    for t in q_tr: principal[t['ins']] += t['inr']
    for k in sched: principal[k] += sched[k]['pik']
    # bank-originated lines
    for k, b, m in find(r"^INT CR"): cash(post(b['date'], 'BANK_INT', 'BANK/INT', [(1100, u(b['amt']), {}), (4200, -u(b['amt']), {})], f"bank {b['loc']}"), k)
    for k, b, m in find(r"CHGS"): cash(post(b['date'], 'BANK_CHG', 'BANK/CHG', [(5300, u(-b['amt']), {}), (1100, u(b['amt']), {})], f"bank {b['loc']}"), k)
    # FX translation (A) and valuation
    if A:
        cum = sum(fn(principal[k], rate_end) - cost[k] for k in ins); mv = cum - open_tb[1220]
        post(Q_END, 'FX_TRANSL', 'FX/30SEP26', [(4700, -mv, {}), (1220, mv, {})], 'FX_Rates csv + Deal_Master (recomputed)')
    VI = P(f"Valuation_Inputs_{C['short']}_30Sep26.xlsx"); vrows = {r['Instrument']: r for r in xl_table(VI, 'Summary', ['Instrument', 'Fair value'])}; vcov = xl_kv(VI, 'Cover')
    adj_fn = {}
    for k, r in vrows.items():
        a = fn(num(r['FV adjustment (INR cr)']), rate_end); adj_fn[k] = a; mv_ = a - num(col(open_ins[k], 'FV adjustment (' + ('USD' if A else 'INR cr')))
        if mv_: post(Q_END, 'VALUATION', f"VAL/{k}/30SEP26", [(1210, mv_, {'instrument': k}), (4600, -mv_, {'instrument': k})], f"Valuation_Inputs Summary!row {r['_row']}")
    # ---------------- trial balance, NAV, capital accounts ----------------
    tq = {}
    for j in J:
        for l in j['lines']: tq[l['gl']] = tq.get(l['gl'], D(0)) + l['amt']
    close_tb = dict(open_tb)
    for g, a in tq.items(): close_tb[g] = close_tb.get(g, D(0)) + a
    nav = lambda t: sum(a for g, a in t.items() if TYPE.get(g) in ('a', 'l'))
    nav_open, nav_close = nav(open_tb), nav(close_tb)
    pl = {}
    for g, a in tq.items():
        if g in CAT: pl[CAT[g]] = pl.get(CAT[g], D(0)) - a
    wa = {k: v for k, v in w.items() if inv[k]['cls'] == 'A'}
    alloc = {c: prorate(pl.get(c, D(0)), wa if c == 'fee' else w) for c in ('income', 'fee', 'expense', 'fv', 'fx')}
    UR = P(f"Unit_Register_{C['short']}.xlsx"); ul = xl_table(UR, 'Unit Ledger', ['Event date', 'Investor ID', 'Units'])
    hold = {r['Investor ID']: r for r in xl_table(UR, 'Holdings', ['Investor ID', 'Units at 30-Sep']) if str(r['Investor ID']).startswith('LP-')}
    cap = {}
    for k in inv:
        o = num(col(open_cap[k], 'Opening capital')); units = int(open_cap[k]['Units']) + units_new.get(k, 0)
        c = o + called.get(k, D(0)) - dist[k]['gross'] + sum(alloc[x].get(k, D(0)) for x in alloc)
        cap[k] = dict(opening=o, closing=c, units=units, nav_per_unit=q(c * sc / units, 4), contributions=called.get(k, D(0)), distributions_income=-dist[k]['gross'])
    cls_nav = {c: sum(v['closing'] for k, v in cap.items() if inv[k]['cls'] == c) for c in ('A', 'B')}
    cls_units = {c: sum(v['units'] for k, v in cap.items() if inv[k]['cls'] == c) for c in ('A', 'B')}
    # ================= RULES =================
    # R1 / R2
    days = sorted({b['date'] for b in bank}); bad = []; gl_bal = open_tb[1100]
    cash_by_day = {}
    for j in J:
        for l in j['lines']:
            if l['gl'] == 1100: cash_by_day[j['date']] = cash_by_day.get(j['date'], D(0)) + l['amt']
    for d_ in sorted(set(days) | set(cash_by_day)):
        gl_bal += cash_by_day.get(d_, D(0)); st = [b['bal'] for b in bank if b['date'] <= d_]
        if u(st[-1] if st else open_bank) != gl_bal: bad.append(f"{d_}: bank {u(st[-1]) if st else ''} vs GL {gl_bal}")
    add('R1', 'Bank = GL cash on every transaction day (opening and each day-end)', not bad and u(open_bank) == open_tb[1100], f"bank close {bank[-1]['bal']:,.2f}", f"GL 1100 {close_tb[1100] * sc:,.2f}",
        f"{len(days)} day-ends compared; opening {open_bank:,.2f}" + ('; ' + '; '.join(bad[:3]) if bad else ''), f"{C['bank']} ({prim}) vs journals")
    ncash = sum(1 for j in J for l in j['lines'] if l['gl'] == 1100); unm = [bank[k]['loc'] for k in range(len(bank)) if k not in used]
    add('R2', 'Every bank line matched to exactly one journal cash line (amount, date, reference)', not unm and ncash == len(bank) and not issues, f"{len(bank)} bank lines", f"{ncash} journal cash lines, {len(unm)} unmatched",
        '; '.join(issues + unm) or 'zero unmatched', f"{C['bank']} ({prim})")
    # R4 custody
    with open(P(f"Demat_Transaction_Statement_{C['short']}_Jul-Sep26.csv")) as f: dtx = list(csv.DictReader(f))
    hold_pdf = {r[0]: int(num(r[3])) for t in pdf_tables(P(f"Demat_Holding_Statement_{C['short']}_30Sep26.pdf")) for r in t[1:]}
    ok = True; det = []
    for k, x in ins.items():
        ob = next(int(r['Balance']) for r in dtx if r['ISIN'] == x['isin'] and r['Particulars'] == 'Opening Balance'); cb = next(int(r['Balance']) for r in dtx if r['ISIN'] == x['isin'] and r['Particulars'] == 'Closing Balance')
        cr = [(dt(r['Date']), int(r['Credit'])) for r in dtx if r['ISIN'] == x['isin'] and r['Credit']]
        exp_cr = [(t['demat'], t['units']) for t in q_tr if t['ins'] == k]
        good = ob == int(open_ins[k]['Quantity']) and cb == qty[k] == hold_pdf.get(x['isin']) and cr == exp_cr and sum(t['units'] for t in tranches if t['ins'] == k) == qty[k]
        ok &= good; det.append(f"{k}: open {ob:,} / close {cb:,} / credits {len(cr)}")
    add('R4', 'Custody = instrument register (holdings 30-Jun and 30-Sep; credits = tranche units on allotment date)', ok, '; '.join(det), '; '.join(f"{k}: {int(open_ins[k]['Quantity']):,} / {qty[k]:,}" for k in ins), '', 'Demat_Holding_Statement pdf, Demat_Transaction_Statement csv vs Deal_Master Tranches, Opening_Balances')
    # R5 calls
    notices = [pdf_kv(p) for p in sorted(glob.glob(P(f"CapitalCall_{C['call']}_Notice_*.pdf")))]
    n_tot = sum(u(num(n[f"Amount now called ({C['ccy']})"])) for n in notices); a_tot = sum(called.values()); r_tot = sum(r['amt'] for r in receipts.values())
    gl3100 = -sum(l['amt'] for j in J for l in j['lines'] if l['gl'] == 3100); pct = num(ck['Percentage of commitment'])
    n_ok = all(u(num(n[f"Amount now called ({C['ccy']})"])) == called[n['Investor ID']] and dt(n['Due date']) == call_due and dt(n['Notice date']) == call_notice for n in notices) and len(notices) == len(inv)
    split_ok = all(num(r['Investment component']) + num(r['Fee component']) + num(r['Expense component']) == num(r['Amount called']) for r in call_rows)
    add('R5', 'Call: notices = allocation = % x commitments = receipts (+ outstanding) = bank credits = GL 3100 / 1400', n_ok and split_ok and n_tot == a_tot == r_tot == gl3100 == committed * pct and close_tb.get(1400, 0) == 0 and all(receipts[k]['amt'] == called[k] for k in called),
        f"notices {n_tot} / allocation {a_tot}", f"receipts {r_tot} / GL 3100 {gl3100} / outstanding {close_tb.get(1400, D(0))}", f"{len(notices)} notices; {pct * 100:.0f}% of {committed}; late payers: " + (', '.join(f"{k} ({r['late']}d)" for k, r in receipts.items() if r['late'] > 0) or 'none'),
        f"CapitalCall_{C['call']}_Notice_*.pdf, _Allocation.xlsx, bank, journals")
    # R6 late interest
    lr = num(terms['Late-payment interest (% p.a.)']) / 100
    exp_lpi = {k: q(r['amt'] * lr * r['late'] / 365) for k, r in receipts.items() if r['late'] > 0}
    add('R6', 'Late-payment interest = rate x days late x amount = bank receipt = GL 4500', exp_lpi == lpi and -tq.get(4500, D(0)) == sum(exp_lpi.values()), f"computed {dict((k, str(v)) for k, v in exp_lpi.items()) or 'none due'}", f"bank {dict((k, str(v)) for k, v in lpi.items()) or 'none'} / GL 4500 {-tq.get(4500, D(0))}",
        f"rate {lr * 100:.0f}% p.a. ACT/365 from PPM term sheet", 'PPM_Term_Sheet pdf, bank, journals')
    # R7 distributions
    dn = {n['Investor ID']: n for n in (pdf_kv(p) for p in sorted(glob.glob(P(f"Distribution_{C['dist']}_Notice_*.pdf"))))}
    tx = 'WHT' if A else 'TDS'
    n_ok = len(dn) == len(dist) and all(u(num(dn[k][f"Gross distribution ({C['ccy']})"])) == d['gross'] and u(num(dn[k][f"{tx} withheld ({C['ccy']})"])) == d['wht'] and u(num(dn[k][f"Net amount payable ({C['ccy']})"])) == d['net'] for k, d in dist.items())
    rate_ok = all(d['rate'] == inv[k]['wht'] and d['wht'] == q(d['gross'] * inv[k]['wht']) and d['net'] == d['gross'] - d['wht'] and d['income'] == d['gross'] for k, d in dist.items())
    bank_ok = all(paid_net.get(k, {}).get('amt') == d['net'] and paid_net[k]['date'] == payd for k, d in dist.items())
    pf_ok = True; pf_note = 'n/a (no bulk file for the onshore scheme)'
    if A:
        pf = [r for r in csv.reader(open(P(f"Distribution_{C['dist']}_PaymentFile.csv"))) if r and r[0] in ('D', 'T')]
        pf_net = sum(u(num(r[4])) for r in pf if r[0] == 'D'); pf_ok = pf_net + twht == tgross and u(num(pf[-1][2])) == pf_net and int(pf[-1][1]) == len(dist); pf_note = f"payment file net {pf_net} + WHT {twht} = {pf_net + twht}"
    ch = pdf_kv(P(C['challan'])); ch_amt = u(num(ch[f"Amount deposited ({C['ccy']})"])); ch_ok = ch_amt == twht and dt(ch['Deposit date']) > Q_END and dt(ch['Deposit date']) == dt(dk[f"{tx} deposit due date"])
    certs = [pdf_kv(p) for p in sorted(glob.glob(P(C['cert'])))]; cert_ok = len(certs) == 3 and all(u(num(c[f"{tx} amount ({C['ccy']})"])) == dist[c['Investor ID']]['wht'] and c['Challan No'] == ch['Challan No'] for c in certs)
    add('R7', 'Distribution: schedule = notices = lines; rate from investor register; bank debits = net; GL 3200 = gross; GL 2500 = tax at 30-Sep; challan clears 2500 in Oct; certificates',
        n_ok and rate_ok and bank_ok and pf_ok and ch_ok and cert_ok and tq[3200] == tgross and -close_tb[2500] == twht, f"gross {tgross} = net {tgross - twht} + {tx} {twht}",
        f"GL 3200 {tq[3200]} / GL 2500 {-close_tb[2500]} / bank net {sum(p['amt'] for p in paid_net.values())} / challan {ch_amt} on {ch['Deposit date']}", f"{pf_note}; {len(certs)} certificates tie; tax payable is a liability at 30-Sep, not in cash",
        f"Distribution_{C['dist']}_Schedule.xlsx, notices, bank, {C['challan']}")
    # R8 accruals
    vp = {k: num(r['Principal (INR cr)']) for k, r in vrows.items()}
    cp_ok = all(('narr' in s) for s in sched.values()); det = []
    for k, s in sched.items():
        det.append(f"{k}: cash {s['cash_inr']} cr" + (f" PIK {s['pik']} cr" if s['pik'] else '') + f" on {' + '.join(f'{p}x{n}d' for p, n in s['segs'])}")
        if A and 'narr' in s:
            m = re.search(r'/INR/ ([\d,\.]+) @ ([\d\.]+)', s['narr']); cp_ok &= bool(m) and num(m.group(1)) == s['cash_inr'] * 10000000 and D(m.group(2)) == rate_end
            if m: fx_checks.append((f"Coupon {k} 30-Sep", D(m.group(2)), fx.get(Q_END)))
    gl_int = -(tq.get(4100, D(0))); gl_pik = -(tq.get(4110, D(0)))
    add('R8', 'Accruals: schedule (ACT/365, tranche part-periods) = GL 4100/4110 = coupon receipts; 1300 clears; PIK capitalised into principal = valuer principal',
        cp_ok and gl_int == sum(s['cash_fn'] for s in sched.values()) and gl_pik == sum(s['pik'] for s in sched.values()) and close_tb.get(1300, 0) == 0 and all(vp[k] == principal[k] for k in ins),
        f"schedule cash {sum(s['cash_fn'] for s in sched.values())} / PIK {sum(s['pik'] for s in sched.values())}", f"GL 4100 {gl_int} / 4110 {gl_pik} / 1300 closing {close_tb.get(1300, D(0))}", '; '.join(det), 'Deal_Master, bank narrations, journals, Valuation_Inputs Summary')
    # R9 FX
    if A:
        cum = close_tb[1220]; rec = sum(fn(principal[k], rate_end) - cost[k] for k in ins)
        add('R9', 'FX: every INR-linked journal uses the daily table; 30-Sep translation at 89.40; GL 1220 = recomputed', all(a == b for _, a, b in fx_checks) and rate_end == MEMO and cum == rec,
            '; '.join(f"{n}: {a}" for n, a, b in fx_checks) + f"; closing {rate_end}", f"table: {'; '.join(str(b) for _, a, b in fx_checks)}; 1220 cumulative {cum} (movement {tq[1220]})",
            '; '.join(f"{k}: INR {principal[k]} cr -> {fn(principal[k], rate_end)} vs cost {cost[k]}" for k in ins), 'FX_Rates_USDINR_Daily_Jul-Sep26.csv, Deal_Master Tranches, bank narrations')
    else: add('R9', 'FX', True, 'not applicable', 'INR scheme - no FX', '', '', 'N/A')
    # R10 valuation
    vt = pdf_tables(P(f"Valuation_Report_{C['short']}_30Sep26.pdf")); vs = next(t for t in vt if 'Fair value (INR cr)' in [c.replace('\n', ' ') for c in t[0]])
    rep = {r[0]: (num(r[4]), num(r[6]), num(r[7])) for r in vs[1:]}; vkv = pdf_kv(P(f"Valuation_Report_{C['short']}_30Sep26.pdf"))
    cal = xl_table(P(C['cal']), 'Calendar', ['Ref', 'Obligation', 'Due date'])
    vrow = next(r for r in cal if 'aluation' in r['Obligation']); recd = dt(vcov['Received by FME'])
    ok = all(rep[k] == (num(r['Principal (INR cr)']), num(r['FV adjustment (INR cr)']), num(r['Fair value (INR cr)'])) and rep[k][2] == rep[k][0] + rep[k][1] for k, r in vrows.items()) and close_tb[1210] == sum(adj_fn.values()) \
        and dt(vrow['Completed / filed date']) <= recd + timedelta(days=15) and dt(vrow['Due date']) == recd + timedelta(days=15) and dt(vkv['Report date']) == dt(vcov['Report date (date)'])
    add('R10', 'Valuation: report PDF = inputs workbook; GL 1210 = fair-value adjustment; dispatch within 15 days of receipt', ok, '; '.join(f"{k}: FV {v[2]} cr (adj {v[1]})" for k, v in rep.items()),
        f"GL 1210 {close_tb[1210]} (movement {tq.get(1210, D(0))}); received {recd:%d-%b}, dispatched {dt(vrow['Completed / filed date']):%d-%b}, limit {recd + timedelta(days=15):%d-%b}", '', 'Valuation_Report pdf p.1 table 2, Valuation_Inputs xlsx, calendar')
    # R11 trial balances
    TB = P(f"Tally_{C['short']}_TrialBalance_30Sep26.xlsx"); ws = openpyxl.load_workbook(TB, data_only=True)['Trial Balance']; tled = {}; gt = None
    for r in ws.iter_rows(values_only=True):
        if r[0] and str(r[0]).startswith('    '): tled[str(r[0]).strip()] = [num(x) for x in r[1:7]]
        if r[0] == 'Grand Total': gt = [num(x) for x in r[1:7]]
    sums = [sum(v[i] for v in tled.values()) for i in range(6)]
    add('R11', 'GL trial balance: debits = credits at 30-Jun and 30-Sep', sum(open_tb.values()) == 0 and sum(close_tb.values()) == 0, f"30-Jun Dr {sum(a for a in open_tb.values() if a > 0)} / Cr {-sum(a for a in open_tb.values() if a < 0)}",
        f"30-Sep Dr {sum(a for a in close_tb.values() if a > 0)} / Cr {-sum(a for a in close_tb.values() if a < 0)}", '', 'Opening_Balances_30Jun26_locked.xlsx + journals')
    add('R11', 'Tally trial balance: opening, transactions and closing each balance; ledger rows foot to Grand Total', gt[0] == gt[1] and gt[2] == gt[3] and gt[4] == gt[5] and sums == gt,
        f"opening {gt[0]:,.2f} / {gt[1]:,.2f}; transactions {gt[2]:,.2f} / {gt[3]:,.2f}", f"closing {gt[4]:,.2f} / {gt[5]:,.2f}", f"{len(tled)} ledgers", f"Tally_{C['short']}_TrialBalance_30Sep26.xlsx")
    # R12 Tally bridge
    root = ET.parse(P(f"Tally_{C['short']}_DayBook_Q2FY27.xml")).getroot(); V = []
    for v in root.iter('VOUCHER'):
        ls = [(e.findtext('LEDGERNAME'), -D(e.findtext('AMOUNT')), e.findtext('ISDEEMEDPOSITIVE')) for e in v.findall('ALLLEDGERENTRIES.LIST')]
        V.append(dict(guid=v.findtext('GUID'), no=v.findtext('VOUCHERNUMBER'), date=datetime.strptime(v.findtext('DATE'), '%Y%m%d').date(), vt=v.findtext('VOUCHERTYPENAME'), narr=v.findtext('NARRATION'), lines=ls))
    v_bal = all(sum(a for _, a, _ in v['lines']) == 0 and all((a > 0) == (f == 'Yes') for _, a, f in v['lines']) for v in V)
    xml_dr = {}; xml_cr = {}
    for v in V:
        for l, a, _ in v['lines']:
            if a > 0: xml_dr[l] = xml_dr.get(l, D(0)) + a
            else: xml_cr[l] = xml_cr.get(l, D(0)) - a
    tb_tx = all(tled.get(l, [0] * 6)[2] == xml_dr.get(l, 0) and tled.get(l, [0] * 6)[3] == xml_cr.get(l, 0) for l in set(xml_dr) | set(xml_cr) | set(tled))
    lm = {r['Name of Ledger']: (num(r['Opening Balance']) if r['Dr/Cr'] == 'Dr' else -num(r['Opening Balance'])) for r in xl_table(P(f"Tally_{C['short']}_LedgerMasters.xlsx"), 'Ledgers', ['Name of Ledger', 'Opening Balance'])}
    lm_ok = all(lm[l] == v[0] - v[1] for l, v in tled.items())
    add('R12', 'Tally day book: every voucher balances; TB transactions = XML; ledger-master openings = TB openings', v_bal and tb_tx and lm_ok, f"{len(V)} vouchers", f"{len(tled)} ledgers", '', f"Tally_{C['short']}_DayBook_Q2FY27.xml, TB, LedgerMasters")
    conv = (sc * MEMO) if A else sc
    tclose = {}; topen = {}
    for l, v in tled.items():
        g = led2gl(l); tclose[g] = tclose.get(g, D(0)) + (v[4] - v[5]) / conv; topen[g] = topen.get(g, D(0)) + (v[0] - v[1]) / conv
    if not A:
        sig = lambda d_, lines: (d_, tuple(sorted((g, q(a, 6)) for g, a in lines)))
        pool = {}
        for j in J: pool.setdefault(sig(j['date'], [(l['gl'], l['amt']) for l in j['lines']]), []).append(j)
        unmatched_v = []
        for v in V:
            agg = {}
            for l, a, _ in v['lines']: agg[led2gl(l)] = agg.get(led2gl(l), D(0)) + a / conv
            s = sig(v['date'], list(agg.items())); s2 = None
            if pool.get(s): pool[s].pop()
            else:
                # journals with several lines on one GL (per investor) - compare aggregated
                for key, js in pool.items():
                    if js and key[0] == v['date']:
                        ag2 = {}
                        for g, a in key[1]: ag2[g] = ag2.get(g, D(0)) + a
                        if {g: q(a, 6) for g, a in agg.items()} == ag2: s2 = key; break
                if s2: pool[s2].pop()
                else: unmatched_v.append(v['no'])
        left = sum(len(x) for x in pool.values()); diffs = {g: tclose.get(g, D(0)) - close_tb.get(g, D(0)) for g in set(tclose) | set(close_tb) if tclose.get(g, D(0)) != close_tb.get(g, D(0))}
        add('R12', 'Tally bridge (statutory book): every voucher <-> one GL journal; TB ledger balances = mapped GL balances (100%)', not unmatched_v and left == 0 and not diffs,
            f"{len(V)} vouchers, {len(unmatched_v)} unmatched", f"{len(J)} journals, {left} unmatched; {len(diffs)} GL balance differences", '', 'Tally XML/TB vs journals')
        bridge = []
    else:
        # voucher level: match on (date, debit total in USD at memo rate, cash leg present)
        key = lambda d_, tot, c: (d_, q(tot, 2), c); pool = {}
        for j in J: pool.setdefault(key(j['date'], sum(l['amt'] for l in j['lines'] if l['amt'] > 0) * sc, any(l['gl'] == 1100 for l in j['lines'])), []).append(j)
        bridge = []; expl = {}; unmatched_v = []; memo_ok = True
        def explain(g, a, code): expl[(g, code)] = expl.get((g, code), D(0)) + a
        for v in V:
            tot_inr = sum(a for _, a, _ in v['lines'] if a > 0); usd = tot_inr / MEMO; k = key(v['date'], usd, any(led2gl(l) == 1100 for l, _, _ in v['lines']))
            m = re.search(r'\(USD ([\d,\.]+) @ ([\d\.]+)\)', v['narr']); memo_ok &= bool(m) and num(m.group(1)) == q(usd, 2) and D(m.group(2)) == MEMO
            if not pool.get(k): unmatched_v.append(v['no']); continue
            j = pool[k].pop(0); daily = fxon(v['date']); d_m = tot_inr - usd * daily
            bridge.append(dict(voucher=v['no'], date=str(v['date']), journal=j['ref'], tally_inr=f"{tot_inr:,.2f}", gl_usd=f"{usd:,.2f}", daily_rate=str(daily), code='M', difference_inr=f"{d_m:,.2f}",
                               reason=f"memo-rate restatement: recorded at 89.40, daily rate {daily}"))
            tg, jg = {}, {}
            for l, a, _ in v['lines']: tg[led2gl(l)] = tg.get(led2gl(l), D(0)) + a / conv
            for l in j['lines']: jg[l['gl']] = jg.get(l['gl'], D(0)) + l['amt']
            for g in set(tg) | set(jg):
                if q(tg.get(g, 0), 6) != q(jg.get(g, 0), 6):
                    explain(g, tg.get(g, D(0)) - jg.get(g, D(0)), 'A')
                    bridge.append(dict(voucher=v['no'], date=str(v['date']), journal=j['ref'], gl=g, code='A', difference_usd_m=str(q(tg.get(g, D(0)) - jg.get(g, D(0)), 6)), reason='cash-basis entry in Tally; accrual / receivable entry in GL'))
        left = [j for js in pool.values() for j in js]; bad_left = []
        for j in left:
            code = 'F' if j['kind'] == 'FX_TRANSL' else ('A' if j['kind'] in ('ACCR_INT', 'ACCR_FEE', 'ACCR_EXP', 'ACCR_PIK', 'PIK_CAP', 'CALL_ISSUE') else None)
            if not code: bad_left.append(j['ref']); continue
            for l in j['lines']: explain(l['gl'], -l['amt'], code)
            bridge.append(dict(voucher='(none)', date=str(j['date']), journal=j['ref'], code=code, difference_usd_m=str(sum(l['amt'] for l in j['lines'] if l['amt'] > 0)),
                               reason='FX translation not booked in Tally' if code == 'F' else 'accrual / receivable not booked in Tally'))
        # opening differences (prior-period accruals and translation) by GL
        for g in set(topen) | set(open_tb):
            dlt = q(topen.get(g, D(0)) - open_tb.get(g, D(0)), 6)
            if dlt:
                code = 'F' if g == 1220 else 'A'
                if g == 3900:
                    f_part = open_tb.get(1220, D(0)) * -1; explain(g, -open_tb.get(1220, D(0)) * -1 * -1, 'F') if False else None
                    explain(g, dlt + open_tb.get(1220, D(0)), 'A'); explain(g, -open_tb.get(1220, D(0)), 'F')
                    bridge.append(dict(voucher='(opening)', journal='opening 3900', gl=g, code='A+F', difference_usd_m=str(dlt), reason='prior-period accruals (A) and FX translation (F) not in Tally'))
                else:
                    explain(g, dlt, code); bridge.append(dict(voucher='(opening)', journal=f'opening {g}', gl=g, code=code, difference_usd_m=str(dlt), reason='prior-period ' + ('FX translation' if code == 'F' else 'accrual') + ' not in Tally'))
        resid = {}
        for g in set(tclose) | set(close_tb):
            r_ = q(tclose.get(g, D(0)) - close_tb.get(g, D(0)) - sum(a for (gg, c), a in expl.items() if gg == g), 6)
            if r_: resid[g] = r_
        codes = sorted({b['code'] for b in bridge})
        add('R12', 'Tally bridge (memo-rate book): every voucher matched; every GL journal without a voucher and every ledger difference explained by M / A / F; residual nil',
            not unmatched_v and not bad_left and not resid and memo_ok, f"{len(V)} vouchers matched, {len(unmatched_v)} unmatched; narration USD x 89.40 = INR on every voucher",
            f"{len(left)} GL journals not in Tally (codes {', '.join(sorted({('F' if j['kind'] == 'FX_TRANSL' else 'A') for j in left}))}); unexplained residual by GL: {resid or 'nil'}",
            f"{len(bridge)} bridge lines written to validation_report.json; M total INR {sum(num(b['difference_inr']) for b in bridge if b['code'] == 'M'):,.2f}", 'Tally XML/TB vs journals, FX table')
    # R13 NAV
    reg_units = {k: int(v['Units at 30-Sep-2026']) for k, v in hold.items()}; led_units = {}
    for r in ul: led_units[r['Investor ID']] = led_units.get(r['Investor ID'], 0) + int(r['Units'])
    add('R13', 'NAV = assets - liabilities = sum of capital accounts = sum of class NAVs; units = unit register', nav_close == sum(c['closing'] for c in cap.values()) == sum(cls_nav.values()) and nav_open == sum(c['opening'] for c in cap.values())
        and reg_units == led_units == {k: c['units'] for k, c in cap.items()}, f"NAV {nav_close} ({C['ccy']} {nav_close * sc:,.2f}); opening {nav_open}",
        f"capital accounts {sum(c['closing'] for c in cap.values())}; class A {cls_nav['A']} / B {cls_nav['B']}; units {sum(reg_units.values()):,} (A {cls_units['A']:,} / B {cls_units['B']:,})",
        f"NAV per unit: fund {q(nav_close * sc / sum(reg_units.values()), 4)}, class A {q(cls_nav['A'] * sc / cls_units['A'], 4)}, class B {q(cls_nav['B'] * sc / cls_units['B'], 4)} (fee charged to class A only)",
        'journals, Unit_Register xlsx (Unit Ledger, Holdings)')
    # R14 performance
    calls = hist_calls + [(call_due, a_tot)]; dists = [(payd, tgross)]; paid = sum(a for _, a in calls)
    perf = dict(paid_in=paid, distributed=tgross, irr=xirr([(d_, -a) for d_, a in calls] + dists + [(Q_END, nav_close)]), tvpi=q((tgross + nav_close) / paid, 6), dpi=q(tgross / paid, 6), rvpi=q(nav_close / paid, 6))
    carry = carry_on_liquidation(nav_close, calls, dists, num(terms['Hurdle rate (% p.a.)']) / 100, num(terms['Carried interest (%)']) / 100)
    e = expected[sid]; ep = e['performance']
    add('R14', 'Performance recomputed from call due dates, distribution dates and NAV (paid-in denominators); carry provision on hypothetical liquidation', abs(perf['irr'] - ep['irr']) < 1e-6 and all(D(ep[k]) == perf[k] for k in ('paid_in', 'distributed', 'tvpi', 'dpi', 'rvpi')) and carry == D(e['carry_provision']),
        f"IRR {perf['irr'] * 100:.4f}% TVPI {perf['tvpi']} DPI {perf['dpi']} RVPI {perf['rvpi']}; carry {carry}", f"expected IRR {ep['irr'] * 100:.4f}% TVPI {ep['tvpi']} DPI {ep['dpi']} RVPI {ep['rvpi']}; carry {e['carry_provision']}",
        f"{len(calls)} calls, 1 distribution; NAV below hurdle so carry provision is nil", 'Opening_Balances Calls, call allocation, distribution schedule, journals')
    # R15 reports (dataset stage: prior filed report must tie to the locked opening books in the same layout)
    q1 = xl_kv(P(C['q1']), 'Report'); q1i = xl_table(P(C['q1']), 'Investors', ['Investor ID', 'Commitment'])
    ok = num(q1['Net asset value']) == nav_open and num(q1['Cumulative drawn']) == -open_tb[3100] and num(q1['Cash and bank']) == open_tb[1100] and num(q1['Investments at cost']) == open_tb[1200] \
        and num(q1['Total commitments']) == committed == sum(num(col(r, 'Commitment')) for r in q1i)
    add('R15', 'Reports: Q1 FY27 report as filed ties to the locked 30-Jun books and registers (layout reused for Q2)', ok, f"report NAV {num(q1['Net asset value'])}, drawn {num(q1['Cumulative drawn'])}", f"books NAV {nav_open}, drawn {-open_tb[3100]}",
        'The Q2 FY27 report is an output of the backend (next phase); this rule will be re-run on it for the locked NAV version.', C['q1'], 'PARTIAL' if ok else 'FAIL')
    # R16 calendar evidence
    mh = {m['file']: m['sha256'] for m in manifest['files']}; done = [r for r in cal if r['Status'] in ('Filed', 'Done')]; bad = []
    for r in done:
        ef = r.get('Evidence file'); rel = f"{C['folder']}/{ef}" if ef else None
        if not ef or not os.path.exists(os.path.join(ROOT, rel)) or sha(os.path.join(ROOT, rel)) != mh.get(rel): bad.append(r['Ref'])
    add('R16', 'Calendar: every Filed / Done obligation has an evidence file that exists and matches its manifest hash', not bad, f"{len(done)} filed/done of {len(cal)} obligations", f"{len(done) - len(bad)} with verified evidence", f"{sum(1 for r in cal if r.get('Verify'))} rows carry a verify flag (reconstructed dates)" + (f"; missing: {bad}" if bad else ''), C['cal'])
    # R17 KYC gate
    kyc = xl_table(P(f"KYC_Register_{C['short']}.xlsx"), 'KYC Register', ['Investor ID', 'Status', 'Next refresh']); bad = [r['Investor ID'] for r in kyc if r['Status'] != 'Complete' and r['Investor ID'] in called and not dt(r['Next refresh date']) > call_notice]
    add('R17', 'KYC gate: no investor with status other than Complete is in the call unless its refresh falls due after the call date', not bad and len(kyc) == len(inv), '; '.join(f"{r['Investor ID']}: {r['Status']} (refresh {dt(r['Next refresh date']):%d-%b-%Y})" for r in kyc if r['Status'] != 'Complete') or 'all Complete',
        f"call notice date {call_notice:%d-%b-%Y}", '', f"KYC_Register_{C['short']}.xlsx, call allocation")
    # R18 covenants
    def mis_val(path, syn):
        wb = openpyxl.load_workbook(path, data_only=True)
        for ws_ in wb.worksheets:
            rows = list(ws_.iter_rows(values_only=True))
            for ri, r in enumerate(rows):
                for ci, c in enumerate(r):
                    if isinstance(c, str) and any(c.strip().lower().startswith(s) for s in syn):
                        vals = [rr[ci] for rr in rows[ri + 1:] if rr[ci] is not None and isinstance(rr[ci], (int, float))]
                        if vals: return num(vals[-1]), f"{ws_.title}!R{ri + 1}C{ci + 1}"
        raise KeyError((path, syn))
    ok = True; det = []; breaches = []
    for k, x in ins.items():
        sold = coll = D(0)
        for mth in ('Jul26', 'Aug26', 'Sep26'):
            f_ = P(f"Developer_MIS_{x['spv']}_{mth}.xlsx"); sold += mis_val(f_, ['units sold', 'nos. booked'])[0]; coll += mis_val(f_, ['collections', 'receipts'])[0]
        cert = P(f"Covenant_Certificate_{x['spv']}_30Sep26.pdf"); ck_ = pdf_kv(cert); ct = [t for t in pdf_tables(cert) if t[0][0] == 'Test'][0]
        cover = q(coll / cov_ds[k], 2); mins = {r['Test']: num(r['Minimum']) for r in cov_terms if r['Instrument ID'] == k}
        exp_res = {'Sales velocity': 'PASS' if sold >= mins['Sales velocity (units sold in quarter)'] else 'BREACH', 'Collection cover': 'PASS' if cover >= mins['Collection cover'] else 'BREACH'}
        got = {('Sales velocity' if 'velocity' in r[0] else 'Collection cover'): (num(r[1]), num(r[2]), r[3]) for r in ct[1:]}
        good = num(ck_['Units sold in quarter']) == sold and num(ck_['Collections in quarter (INR cr)']) == coll and got['Sales velocity'][1] == sold and got['Collection cover'][1] == cover \
            and all(got[t][2] == exp_res[t] for t in got) and got['Sales velocity'][0] == mins['Sales velocity (units sold in quarter)'] and got['Collection cover'][0] == mins['Collection cover']
        ok &= good; det.append(f"{x['spv']}: sold {sold} (min {mins['Sales velocity (units sold in quarter)']}), cover {cover} (min {mins['Collection cover']})")
        breaches += [f"{x['spv']} {t}" for t in exp_res if exp_res[t] == 'BREACH']
    bn = [r for r in cal if 'breach notice' in r['Obligation'].lower()]; bd = Q_END; n = 0
    while n < 10:
        bd += timedelta(days=1); n += bd.weekday() < 5
    bn_ok = (not breaches and not bn) or (breaches and bn and dt(bn[0]['Due date']) == bd)
    add('R18', 'Covenants: MIS Jul-Sep actuals (two developer layouts) = covenant certificates; breach flags; breach-notice due date', ok and bn_ok and e['covenants'] and sorted(breaches) == sorted(f"{ins[i]['spv']} {'Sales velocity' if 'velocity' in t else 'Collection cover'}" for i, c in e['covenants'].items() for t in c['breached']),
        '; '.join(det), f"breaches: {', '.join(breaches) or 'none'}" + (f"; notice due {bd:%d-%b-%Y} (10 business days, weekends only) = calendar {dt(bn[0]['Due date']):%d-%b-%Y}" if bn else ''), '', 'Developer_MIS_*.xlsx (6 files), Covenant_Certificate_*.pdf, Deal_Master Covenants, calendar')
    # R19 limits
    lim = num(terms['Single-investee limit (% of investable funds)']) / 100; target = num(terms[f"Target corpus ({'USD m' if A else 'INR cr'})"]); mc = num(terms[f"Minimum corpus ({'USD m' if A else 'INR cr'})"])
    big = max(cost.values()); bk_ = max(cost, key=cost.get); on_t = big / target; on_c = big / committed; borrow = sum(a for g, a in close_tb.items() if 2600 <= g < 2700)
    st = 'PASS' if on_c <= lim else ('WARN' if on_t <= lim else 'FAIL')
    add('R19', 'Limits: single-investee exposure, leverage, corpus >= minimum (PPM terms)', st != 'FAIL' and committed >= mc and borrow == 0, f"largest {bk_} cost {big}: {on_t * 100:.2f}% of target corpus {target}; {on_c * 100:.2f}% of commitments {committed}",
        f"limit {lim * 100:.0f}% of investable funds; leverage {borrow} (limit nil); corpus {committed} >= minimum {mc}",
        '' if st == 'PASS' else f"WITHIN the limit only if investable funds are measured on target corpus; on total commitments the exposure is {on_c * 100:.2f}% and exceeds {lim * 100:.0f}%. The brief's Section 6 amounts produce this - decision needed (see docs/known_limitations.md).",
        'PPM_Term_Sheet pdf, Deal_Master, journals', st if committed >= mc and borrow == 0 else 'FAIL')
    # supplementary
    if A:
        fc = pdf_kv(P('FCGPR_Acknowledgement_I-A1_T2.pdf')); t2 = next(t for t in q_tr if t['ins'] == 'I-A1')
        add('S1', 'FEMA: FC-GPR allotment date = tranche date; due = allotment + 30 days; filed on or before due', dt(fc['Allotment date']) == t2['date'] and dt(fc['Due date']) == t2['date'] + timedelta(days=30) and dt(fc['Filed date']) <= dt(fc['Due date']),
            f"allotment {fc['Allotment date']}, filed {fc['Filed date']}", f"due {fc['Due date']}", f"ack {fc['Acknowledgement No']}", 'FCGPR_Acknowledgement_I-A1_T2.pdf, Deal_Master Tranches')
    fr = num(terms['Management fee rate (% p.a.)']) / 100; f2k = fee_inv['Q2FY27']; fee_calc = q(committed * fr / 4); fee_doc = u(num(f2k[f"Management fee ({C['ccy']})"])); a_only = q(sum(wa.values()) * fr / 4, 6)
    add('S2', 'Fee engine: rate x commitments x 1/4 = invoice (+ GST) = GL 5100', fee_calc == fee_doc and tq[5100] == u(num(f2k[tot_key])), f"computed {fee_calc} (+ GST {u(num(f2k['GST (' + C['ccy'] + ')']))})", f"invoice {fee_doc}; GL 5100 {tq[5100]}",
        f"Fee base is TOTAL commitments ({committed}) as in the brief's golden totals; on Class A commitments only ({sum(wa.values())}) the fee would be {a_only}. Decision needed.", f"{C['fee']}_Fee_Invoice_Q2FY27.pdf, PPM_Term_Sheet", 'WARN' if fee_calc == fee_doc and tq[5100] == u(num(f2k[tot_key])) else 'FAIL')
    # golden totals
    def cmp_tb(exp_tb, got): return all(eq(D(v), got.get(int(g), D(0)), D(0)) for g, v in exp_tb.items()) and all(str(g) in exp_tb or a == 0 for g, a in got.items())
    g_ok = cmp_tb(e['opening_tb'], open_tb) and cmp_tb(e['closing_tb'], close_tb) and D(e['nav_close']) == nav_close and D(e['bank']['closing']) == u(bank[-1]['bal']) and int(e['units_total']) == sum(reg_units.values()) \
        and all(D(e['capital_accounts'][k]['closing']) == c['closing'] and D(e['capital_accounts'][k]['opening']) == c['opening'] and D(e['capital_accounts'][k]['nav_per_unit']) == c['nav_per_unit'] for k, c in cap.items()) \
        and all(e['custody'][x['isin']]['close'] == qty[k] for k, x in ins.items()) and D(e['wht_payable']) == twht and e['counts']['journals_q2'] == len(J) and e['counts']['bank_lines'] == len(bank)
    add('G1', 'Golden totals: books rebuilt from the source files = expected_results.json (TBs, NAV, capital accounts, bank, custody, tax payable, counts) - exact', g_ok, f"rebuilt NAV {nav_close}, cash {close_tb[1100]}, {len(J)} journals", f"expected NAV {e['nav_close']}, cash {e['bank']['closing']}, {e['counts']['journals_q2']} journals", '', 'expected_results.json')
    if A:
        brief = {1100: '24.2826', 1200: '40.6982', 1210: '1.0067', 1220: '-0.4298', 1300: '0', 2100: '-0.5250', 2200: '-0.1050', 2500: '-0.1200', 3100: '-66', 3200: '1.2'}
        bo = {1100: '18.1232', 1200: '29.4812', 1210: '0.2472', 1220: '-0.2677', 2100: '-0.5250', 2200: '-0.0600', 3100: '-48', 3900: '1.0013'}
        d1 = {g: close_tb[g] - D(v) for g, v in brief.items() if close_tb[g] != D(v)}; d0 = {g: open_tb[g] - D(v) for g, v in bo.items() if open_tb[g] != D(v)}
        res_q = sum(pl.values())
        add('G2', "Brief Section 6.1 golden totals (tolerance 0.0005): closing TB, NAV 64.8077, bank 24,282,600, units 660,000, opening TB, NAV 46.9987, result 1.0090",
            all(abs(v) <= TOL for v in list(d1.values()) + list(d0.values())) and eq(nav_close, '64.8077') and bank[-1]['bal'] == D('24282600') and sum(reg_units.values()) == 660000 and eq(nav_open, '46.9987') and eq(res_q, '1.0090'),
            f"NAV {nav_close}; bank {bank[-1]['bal']:,.2f}; opening NAV {nav_open}; quarter result {res_q}", "brief: NAV 64.8077; bank 24,282,600.00; opening NAV 46.9987; quarter result 1.0090",
            f"differences within tolerance: opening accumulated result {open_tb[3900]} vs brief 1.0013 and quarter result {res_q} vs 1.0090 (the brief's own opening TB is out of balance by 0.0002); closing TB differences: {d1 or 'none'}", 'brief Section 6.1')
    return dict(open_tb=open_tb, close_tb=close_tb, nav_open=nav_open, nav_close=nav_close, capital=cap, classes={c: dict(nav=cls_nav[c], units=cls_units[c]) for c in cls_nav}, performance=perf, pl=pl,
                journals=[dict(date=str(j['date']), kind=j['kind'], ref=j['ref'], src=j['src'], bank=(bank[j['bank']]['loc'] if j['bank'] is not None else None), lines=[{k: (str(v) if isinstance(v, D) else v) for k, v in l.items()} for l in j['lines']]) for j in J],
                bridge=bridge)


def main():
    manifest = json.load(open(os.path.join(ROOT, 'manifest.json'))); expected = json.load(open(os.path.join(ROOT, 'expected_results.json'))); books = {}
    for sid in ('A', 'B'): books[sid] = run(sid, manifest, expected)
    bad = [m['file'] for m in manifest['files'] if not os.path.exists(os.path.join(ROOT, m['file'])) or sha(os.path.join(ROOT, m['file'])) != m['sha256']]
    R.add('R20', 'all', 'Manifest: every listed file exists and matches its SHA-256', not bad, f"{len(manifest['files'])} files", f"{len(bad)} mismatches", '', 'manifest.json')
    if '--skip-determinism' not in sys.argv:
        with tempfile.TemporaryDirectory() as td:
            subprocess.run([sys.executable, '-m', 'generator', '--seed', str(manifest['seed']), '--out', td], check=True, capture_output=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            m2 = {m['file']: m['sha256'] for m in json.load(open(os.path.join(td, 'manifest.json')))['files']}; m1 = {m['file']: m['sha256'] for m in manifest['files']}
            df = [f for f in m1 if m1[f] != m2.get(f)]
        R.add('R20', 'all', 'Determinism: generator re-run with the same seed gives identical hashes (PDF timestamps normalised)', not df and len(m1) == len(m2), f"{len(m1)} files, seed {manifest['seed']}", f"{len(df)} differing", ', '.join(df[:5]), 'generator re-run')
    names = ' '.join(m['file'] for m in manifest['files']); txt = names
    for m in manifest['files']:
        p = os.path.join(ROOT, m['file'])
        if m['format'] in ('csv', 'xml', 'mt940'): txt += open(p, errors='ignore').read()
    R.add('N1', 'all', 'Names: the firm name does not appear in file names or text-format files (PDF/xlsx text is scanned in the QA step)', 'hdfc' not in txt.lower(), 'occurrences', txt.lower().count('hdfc'), '', 'manifest + csv/xml/mt940')
    cnt = {s: sum(1 for r in R.rows if r['status'] == s) for s in ('PASS', 'WARN', 'PARTIAL', 'FAIL', 'N/A')}
    def ser(o):
        if isinstance(o, D): return str(o)
        if isinstance(o, dict): return {str(k): ser(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)): return [ser(x) for x in o]
        return o
    out = os.path.dirname(os.path.abspath(__file__))
    json.dump(dict(dataset=ROOT, summary=cnt, rules=R.rows, books=ser(books)), open(os.path.join(out, 'validation_report.json'), 'w'), indent=1)
    col_ = {'PASS': '#1a7f37', 'FAIL': '#c62828', 'WARN': '#b26a00', 'PARTIAL': '#b26a00', 'N/A': '#667'}
    es = html.escape
    rows = ''.join(f"<tr><td><b>{r['rule']}</b></td><td>{r['scheme']}</td><td>{es(r['title'])}</td><td><span class='b' style='background:{col_[r['status']]}'>{r['status']}</span></td><td>{es(r['left'])}</td><td>{es(r['right'])}</td>"
                   f"<td>{es(r['detail'])}</td><td class='s'>{es(r['src'])}</td></tr>" for r in R.rows)
    def tbt(sid):
        b = books[sid]; gls = sorted(set(b['open_tb']) | set(b['close_tb']))
        return f"<h2>Scheme {sid} - trial balance rebuilt from source files ({'USD m' if sid == 'A' else 'INR cr'}, debit positive)</h2><table><tr><th>GL</th><th class='n'>30-Jun-2026</th><th class='n'>30-Sep-2026 (pre-closing)</th></tr>" + \
            ''.join(f"<tr><td>{g}</td><td class='n'>{b['open_tb'].get(g, D(0))}</td><td class='n'>{b['close_tb'].get(g, D(0))}</td></tr>" for g in gls) + \
            f"<tr><th>NAV</th><th class='n'>{b['nav_open']}</th><th class='n'>{b['nav_close']}</th></tr></table><table><tr><th>Investor</th><th class='n'>Opening</th><th class='n'>Closing</th><th class='n'>Units</th><th class='n'>NAV / unit</th></tr>" + \
            ''.join(f"<tr><td>{k}</td><td class='n'>{c['opening']}</td><td class='n'>{c['closing']}</td><td class='n'>{c['units']:,}</td><td class='n'>{c['nav_per_unit']}</td></tr>" for k, c in b['capital'].items()) + '</table>'
    page = f"""<!doctype html><html><head><meta charset='utf-8'><title>Validation report - Q2 FY27 dataset</title><style>
body{{font-family:-apple-system,Segoe UI,Arial,sans-serif;font-size:13px;color:#16202b;margin:24px;background:#fff}} h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:15px;margin:22px 0 6px}}
table{{border-collapse:collapse;width:100%;margin:6px 0 14px}} th,td{{border:1px solid #d5dbe1;padding:5px 7px;vertical-align:top;text-align:left}} th{{background:#f1f4f7}} .n{{text-align:right;font-variant-numeric:tabular-nums}}
.b{{color:#fff;border-radius:3px;padding:1px 7px;font-weight:600;font-size:11px;white-space:nowrap}} .s{{color:#556;font-size:11px}} .sum span{{margin-right:14px}} .wrap{{overflow-x:auto}}</style></head><body>
<h1>Reconciliation and validation report - Q2 FY27 synthetic dataset</h1><div>Dataset: {es(ROOT)} · {len(manifest['files'])} source files · seed {manifest['seed']} · tolerance 0.0005 (scheme unit); file-to-file checks are exact</div>
<p class='sum'>{''.join(f"<span><span class='b' style='background:{col_[k]}'>{k}</span> {v}</span>" for k, v in cnt.items() if v)}</p>
<p>Every figure below is rebuilt from the source files by posting rules in <code>validation/run.py</code>; the generator's internal state is not read. A = GIFT IFSC scheme (USD), B = onshore AIF (INR).</p>
<div class='wrap'><table><tr><th>Rule</th><th>Sch.</th><th>Check</th><th>Status</th><th>Left side</th><th>Right side</th><th>Detail</th><th>Source pointers</th></tr>{rows}</table></div>{tbt('A')}{tbt('B')}</body></html>"""
    open(os.path.join(out, 'validation_report.html'), 'w').write(page)
    print(cnt)
    for r in R.rows:
        if r['status'] not in ('PASS', 'N/A'): print(f"  {r['status']:8} {r['rule']} {r['scheme']} {r['title'][:70]} | {r['left'][:90]} | {r['right'][:90]} | {r['detail'][:120]}")
    sys.exit(1 if cnt['FAIL'] else 0)


main()
