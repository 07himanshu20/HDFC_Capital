"""Books engine: posts the quarter's journals from parsed documents, matches every bank line, and builds the
trial balance, NAV, capital accounts, performance and the Tally bridge.  Then runs the reconciliation rules.

Ported from validation/run.py (which was checked against the golden totals) so the numbers are identical.
Input is a parsing.extract.Bundle; nothing here reads files.
"""
import re
from decimal import Decimal as D
from datetime import timedelta, date

from ..parsing.util import q, num, dt, nows, col, dmy, quarter_end, qcode, prev_quarter_end
from .coa import GL, TYPE, CAT, led2gl

TOL = D('0.0005')


def prorate(total, w, p=6):
    tw = sum(w.values())
    out = {k: q(total * v / tw, p) for k, v in w.items()}
    k = max(w, key=lambda z: (w[z], z))
    out[k] += q(total, p) - sum(out.values())
    return out


def xirr(flows):
    t0 = min(d for d, _ in flows)
    f = lambda r: sum(float(a) / (1 + r) ** ((d - t0).days / 365.0) for d, a in flows)
    lo, hi = -0.99, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return round((lo + hi) / 2, 6)


def carry_on_liquidation(nav, calls, dists, hurdle, carry, q_end):
    g = lambda d, a: float(a) * (1 + float(hurdle)) ** ((q_end - d).days / 365.0)
    paid = sum(a for _, a in calls)
    dist = sum(a for _, a in dists)
    hurdle_amt = max(D(str(round(sum(g(d, a) for d, a in calls) - sum(g(d, a) for d, a in dists), 6))) - (paid - dist), D(0))
    rem = max(D(nav) - (paid - dist), D(0))
    t2 = min(rem, hurdle_amt)
    rem -= t2
    cu = min(rem, q(hurdle_amt * carry / (1 - carry), 6))
    rem -= cu
    return q(cu + rem * carry, 6)


# order of journals inside one day (matches the order a fund accountant posts them)
KIND_RANK = {'FEE_PAY': 0, 'EXP_PAY': 1, 'CALL_ISSUE': 2, 'CALL_RCPT': 3, 'DISB': 4, 'LPI': 5, 'DIST_DECL': 6, 'DIST_PAY': 7,
             'ACCR_INT': 8, 'CPN_RCPT': 8, 'ACCR_PIK': 8, 'PIK_CAP': 8, 'BANK_INT': 9, 'BANK_CHG': 10, 'ACCR_FEE': 11, 'ACCR_EXP': 12,
             'FX_TRANSL': 13, 'VALUATION': 14}
INS_SUB = {'ACCR_INT': 0, 'CPN_RCPT': 1, 'ACCR_PIK': 2, 'PIK_CAP': 3}
ROLE_RANK = {'trustee': 0, 'administrator': 1, 'rta': 1, 'legal': 2, 'audit': 3, 'valuer': 4}


class Results:
    def __init__(s):
        s.rows = []

    def add(s, rule, scheme, title, ok, left, right, detail='', src='', status=None):
        s.rows.append(dict(rule=rule, scheme=scheme, title=title, status=status or ('PASS' if ok else 'FAIL'), left=str(left), right=str(right), detail=detail, src=src))


def eq(a, b, tol=TOL):
    return abs(D(a) - D(b)) <= tol


def compute(X, settings=None, expected=None):
    """X: Bundle from parsing.extract.extract_scheme.  Returns a dict with books, rules and supporting detail."""
    settings = settings or {}
    sid = X['scheme']['id']
    A = X['scheme']['fx']
    sc = X['scheme']['scale']
    ccy = X['scheme']['ccy']
    P = X['period']
    Q_START, Q_END, OPEN_DT = P['q_start'], P['q_end'], P['open_dt']
    QC, PQC = P['qcode'], P['prev_qcode']
    R = Results()
    u = lambda base: D(base) / sc
    add = lambda rule, title, ok, l, r, detail='', src='', status=None: R.add(rule, sid, title, ok, l, r, detail, src, status)
    files = X['_files']
    short = re.sub(r'^Investor_Register_|\.xlsx$', '', files['investor_register'][0])

    # ---------------- masters ----------------
    op = X['opening']
    open_tb = dict(op['tb'])
    open_ins = op['instruments']
    open_cap = op['capital']
    hist_calls = [(d_, a) for _, d_, a in op['calls']]
    inv = {}
    for r in X['investor_register']['investors']:
        inv[r['Investor ID']] = dict(cls=r['Unit class'], commit=u(num(col(r, 'Commitment'))), wht=num(col(r, 'rate')), name=r['Legal name'], row=r)
    terms = X['ppm']['kv']
    par = num(terms[f"Unit par value ({ccy})"])
    committed = sum(i['commit'] for i in inv.values())
    w = {k: v['commit'] for k, v in inv.items()}
    DMI = X['deal']
    ins = {r['Instrument ID']: dict(isin=r['ISIN'], kind=r['Kind'], cash=num(col(r, 'Cash coupon')) / 100, pik=num(col(r, 'PIK coupon')) / 100, spv=r['Project SPV'],
                                    spv_name=r['SPV legal name'], row=r) for r in DMI['instruments']}
    tranches = [dict(ins=r['Instrument ID'], no=int(r['Tranche no']), date=dt(r['Disbursement date']), inr=num(col(r, 'Amount (INR cr)')),
                     rate=num(col(r, 'FX rate')) if A else D(1), units=int(r['Units allotted']), demat=dt(r['Demat credit date']), row=r['_row'])
                for r in DMI['tranches']]
    cov_terms = DMI['covenants']
    cov_ds = DMI['cov_basis']
    fx = X['fx']
    fxon = lambda d: fx[max(k for k in fx if k <= d)]
    fn = lambda inr, rate: q(inr * 10 / rate) if A else D(inr)
    memo = None
    if A:
        for v in X['tally']['vouchers']:
            m = re.search(r'@ ([\d\.]+)\)', v['narr'] or '')
            if m:
                memo = D(m.group(1))
                break

    # ---------------- bank ----------------
    BK = X['bank']
    kvb = BK['pdf']['kv']
    stem = BK['file_stem']
    open_bank = num(kvb[f"Opening balance as on {OPEN_DT:%d-%b-%Y}"])
    prim = BK['primary']
    bank = BK['formats'][prim]['lines']
    if prim == 'MT940':
        mt = BK['formats']['MT940']
        day_ok = all(next(b['bal'] for b in reversed(bank) if b['date'] == d) == v for d, v in mt['closings'].items())
        add('R3', 'MT940 opening :60F: = PDF opening; daily :62F: = running balance', mt['opening'] == open_bank and day_ok, mt['opening'], open_bank,
            f"{len(mt['closings'])} daily :62F: balances checked", stem + '.mt940 / .pdf')
    elif prim == 'XLS':
        xo = BK['formats']['XLS']['opening']
        add('R3', 'XLS opening balance = PDF opening balance', xo == open_bank, xo, open_bank, '', stem + '.xls / .pdf')
    for nm in ('PDF', 'CSV', 'XLS', 'MT940'):
        if nm == prim or nm not in BK['formats']:
            continue
        o = BK['formats'][nm]['lines']
        same = len(o) == len(bank) and all(a['date'] == b['date'] and a['amt'] == b['amt'] and a['bal'] == b['bal'] and nows(a['narr']) == nows(b['narr']) and a['ref'] == b['ref'] for a, b in zip(o, bank))
        add('R3', f'{prim} = {nm}: line count, dates, refs, narrations, amounts, balances', same, f"{len(bank)} lines, net {sum(b['amt'] for b in bank):,.2f}",
            f"{len(o)} lines, net {sum(b['amt'] for b in o):,.2f}", '', f"{stem}.{nm.lower()}")
    add('R3', 'PDF summary: closing balance and transaction count', num(kvb[f"Closing balance as on {Q_END:%d-%b-%Y}"]) == bank[-1]['bal'] and int(kvb['Number of transactions']) == len(bank),
        kvb[f"Closing balance as on {Q_END:%d-%b-%Y}"], f"{bank[-1]['bal']:,.2f}", '', stem + '.pdf')
    for b in bank:
        b.setdefault('loc', '')

    # ---------------- posting engine ----------------
    J = []
    used = set()

    def post(d, kind, ref, lines, src, desc, sortkey=None):
        assert sum(a for _, a, _ in lines) == 0, (kind, ref, lines)
        J.append(dict(date=d, kind=kind, ref=ref, desc=desc, lines=[dict(gl=g, amt=D(a), **m) for g, a, m in lines], src=src, bank=None, sortkey=sortkey, seq=len(J)))
        return J[-1]

    def find(pattern):
        return [(k, b, re.search(pattern, b['narr'])) for k, b in enumerate(bank) if k not in used and re.search(pattern, b['narr'])]

    def cash(j, k):
        used.add(k)
        j['bank'] = k

    issues = []
    txm = lambda inr, rate: ({'txn_ccy': 'INR', 'txn_amt': inr, 'rate': rate} if A else {})
    # fees and vendor invoices
    fee_inv = X['fee_invoices']
    tot_key = f"Invoice total ({ccy})"
    qlabel = lambda c: f"{c[:2]} {c[2:]}"
    for ql in (PQC, QC):
        k = fee_inv[ql]
        amt = u(num(k[tot_key]))
        if k['Status'].startswith('Paid'):
            h = find(rf"MF {ql}")
            if len(h) == 1 and u(-h[0][1]['amt']) == amt:
                cash(post(h[0][1]['date'], 'FEE_PAY', f"MF/{ql}", [(2100, amt, {}), (1100, -amt, {})], k['_file'], f"Management fee {qlabel(ql)} paid"), h[0][0])
            else:
                issues.append(f"fee {ql} payment not found in bank")
        else:
            post(Q_END, 'ACCR_FEE', f"ACCR/MF/{ql}", [(5100, amt, {}), (2100, -amt, {})], k['_file'], f"Management fee {qlabel(ql)} accrued")
    vend = sorted(X['vendor_invoices'], key=lambda k: (k.get('Period', ''), ROLE_RANK.get(k.get('Service'), 9), k['_file']))
    for k in sorted(X['vendor_invoices'], key=lambda k: k['_file']):
        amt = u(num(k[tot_key]))
        gl = 5210 if k['Service'] == 'valuer' else 5200
        if k['Status'].startswith('Paid'):
            h = find(re.escape(f"INV {k['Invoice No']}") + r'(?!\d)')
            if len(h) == 1 and u(-h[0][1]['amt']) == amt:
                cash(post(h[0][1]['date'], 'EXP_PAY', f"INV/{k['Invoice No']}", [(2200, amt, {}), (1100, -amt, {})], k['_file'], f"{k['Vendor']} invoice {k['Invoice No']} paid",
                          sortkey=h[0][0]), h[0][0])
            else:
                issues.append(f"invoice {k['Invoice No']} payment not found in bank")
        else:
            post(Q_END, 'ACCR_EXP', f"ACCR/{k['Invoice No']}", [(gl, amt, {}), (2200, -amt, {})], k['_file'], f"{k['Vendor']} {k['Period']} accrued ({k['Invoice No']})",
                 sortkey=f"{k.get('Period', '')}{ROLE_RANK.get(k.get('Service'), 9)}")
    # capital call
    CL = X['call']
    ccode = CL['code']
    ck = CL['alloc']['kv']
    call_rows = CL['alloc']['rows']
    clabel = str(ck.get('Call no', ccode))
    called = {r['Investor ID']: u(num(r['Amount called'])) for r in call_rows}
    call_notice, call_due = dt(ck['Notice date']), dt(ck['Due date'])
    pct = num(ck['Percentage of commitment'])
    post(call_notice, 'CALL_ISSUE', f"{ccode}/ISSUE", [(1400, sum(called.values()), {})] + [(3100, -a, {'investor': k}) for k, a in called.items()],
         f"{CL['file']} Allocation", f"Capital call {clabel} issued ({pct * 100:.0f}% of commitments)")
    receipts = {}
    units_new = {}
    for k, b, m in find(rf"CALL {ccode} (LP-\w+)"):
        i = m.group(1)
        a = u(b['amt'])
        receipts[i] = dict(date=b['date'], amt=a, late=(b['date'] - call_due).days)
        cash(post(b['date'], 'CALL_RCPT', f"{ccode}/{i}", [(1100, a, {}), (1400, -a, {'investor': i})], f"bank {b['loc']}", f"{clabel} receipt - {inv[i]['name']}", sortkey=k), k)
        units_new[i] = int(a * sc / par)
    lpi = {}
    for k, b, m in find(rf"LPI {ccode} (LP-\w+)"):
        i = m.group(1)
        a = u(b['amt'])
        lpi[i] = a
        late = receipts.get(i, {}).get('late', 0)
        cash(post(b['date'], 'LPI', f"LPI/{ccode}/{i}", [(1100, a, {}), (4500, -a, {'investor': i})], f"bank {b['loc']}",
                  f"Late-payment interest {clabel} - {inv[i]['name']} ({late} days)", sortkey=k), k)
    # disbursements in the quarter
    cost = {k: num(col(v, 'Cost')) for k, v in open_ins.items()}
    principal = {k: num(col(v, 'Principal')) for k, v in open_ins.items()}
    qty = {k: int(v['Quantity']) for k, v in open_ins.items()}
    q_tr = [t for t in tranches if Q_START <= t['date'] <= Q_END]
    fx_checks = []
    for t in q_tr:
        amt = fn(t['inr'], t['rate'])
        t['fn'] = amt
        h = find(rf"DISB {t['ins']} T{t['no']}")
        if A:
            fx_checks.append((f"Disbursement {t['ins']} T{t['no']} {t['date']:%d-%b}", t['rate'], fx.get(t['date'])))
        if len(h) == 1 and u(-h[0][1]['amt']) == amt and h[0][1]['date'] == t['date']:
            cash(post(t['date'], 'DISB', f"DISB/{t['ins']}/T{t['no']}", [(1200, amt, {'instrument': t['ins'], **txm(t['inr'], t['rate'])}), (1100, -amt, {})],
                      f"Deal_Master Tranches!row {t['row']}", f"Disbursement {t['ins']} tranche {t['no']} - {ins[t['ins']]['spv_name']}", sortkey=h[0][0]), h[0][0])
        else:
            issues.append(f"disbursement {t['ins']} T{t['no']} not matched in bank")
        cost[t['ins']] += amt
        qty[t['ins']] += t['units']
    for t in tranches:
        if 'fn' not in t:
            t['fn'] = q(t['inr'] * 10 / t['rate']) if A else t['inr']
    # distribution
    DI = X['dist']
    dcode = DI['code']
    dk = DI['schedule']['kv']
    drows = DI['schedule']['rows']
    dlabel = str(dk.get('Distribution no', dcode))
    dist = {r['Investor ID']: dict(gross=u(num(r['Gross'])), income=u(num(r['Income'])), roc=u(num(col(r, 'Return of capital'))), gain=u(num(col(r, 'Capital gain'))),
                                   rate=num(col(r, 'rate')), wht=u(num(col(r, 'amount'))), net=u(num(r['Net paid']))) for r in drows}
    decl, payd = dt(dk['Declaration date']), dt(dk['Payment date'])
    twht = sum(d['wht'] for d in dist.values())
    tgross = sum(d['gross'] for d in dist.values())
    post(decl, 'DIST_DECL', f"{dcode}/DECL", [(3200, d['gross'], {'investor': k}) for k, d in dist.items()] + [(2300, -(tgross - twht), {}), (2500, -twht, {})],
         f"{DI['file']} Schedule", f"Distribution {dlabel} declared (income)")
    paid_net = {}
    for k, b, m in find(rf"DIST {dcode} (LP-\w+)"):
        i = m.group(1)
        a = u(-b['amt'])
        paid_net[i] = dict(amt=a, date=b['date'])
        cash(post(b['date'], 'DIST_PAY', f"{dcode}/{i}", [(2300, a, {'investor': i}), (1100, -a, {})], f"bank {b['loc']}", f"{dlabel} net paid - {inv[i]['name']}", sortkey=k), k)
    # coupons / PIK: accrual schedule recomputed from terms (ACT/365, day after allotment to period end inclusive)
    sched = {}
    rate_end = fx[Q_END] if A else D(1)
    for k, x in ins.items():
        if not (x['cash'] or x['pik']):
            continue
        segs = [(principal[k], (Q_END - OPEN_DT).days)] + [(t['inr'], (Q_END - t['date']).days) for t in q_tr if t['ins'] == k]
        c_inr = q(sum(p * x['cash'] * n / 365 for p, n in segs))
        p_inr = q(sum(p * x['pik'] * n / 365 for p, n in segs))
        c_fn = fn(c_inr, rate_end)
        sched[k] = dict(cash_inr=c_inr, pik=p_inr, cash_fn=c_fn, segs=segs)
        m_ = {'instrument': k, **txm(c_inr, rate_end)}
        post(Q_END, 'ACCR_INT', f"ACCR/{k}/{QC}", [(1300, c_fn, dict(m_)), (4100, -c_fn, dict(m_))], 'Deal_Master Instruments + Tranches (recomputed)',
             f"Coupon accrued {k} {QC}", sortkey=(k, 0))
        h = find(rf"CPN {k} {QC}")
        if len(h) == 1 and u(h[0][1]['amt']) == c_fn:
            cash(post(Q_END, 'CPN_RCPT', f"CPN/{k}/{QC}", [(1100, c_fn, {}), (1300, -c_fn, dict(m_))], f"bank {h[0][1]['loc']}",
                      f"Coupon received {k} {QC} - {x['spv_name']}", sortkey=(k, 1)), h[0][0])
            sched[k]['narr'] = h[0][1]['narr']
        else:
            issues.append(f"coupon {k} not matched in bank (expected {c_fn})")
        if p_inr:
            post(Q_END, 'ACCR_PIK', f"PIK/{k}/{QC}", [(1300, p_inr, {'instrument': k}), (4110, -p_inr, {'instrument': k})], 'Deal_Master (recomputed)',
                 f"PIK interest accrued {k} {QC}", sortkey=(k, 2))
            post(Q_END, 'PIK_CAP', f"PIKCAP/{k}/{QC}", [(1200, p_inr, {'instrument': k}), (1300, -p_inr, {'instrument': k})], 'Deal_Master (recomputed)',
                 f"PIK capitalised into principal {k} {QC}", sortkey=(k, 3))
            cost[k] += p_inr
    principal_open = dict(principal)
    for t in q_tr:
        principal[t['ins']] += t['inr']
    for k in sched:
        principal[k] += sched[k]['pik']
    # bank-originated lines
    for k, b, m in find(r"^INT CR"):
        cash(post(b['date'], 'BANK_INT', 'BANK/INT', [(1100, u(b['amt']), {}), (4200, -u(b['amt']), {})], f"bank {b['loc']}", 'Bank deposit interest credited'), k)
    for k, b, m in find(r"CHGS"):
        cash(post(b['date'], 'BANK_CHG', 'BANK/CHG', [(5300, u(-b['amt']), {}), (1100, u(b['amt']), {})], f"bank {b['loc']}", 'Bank charges'), k)
    # FX translation (A) and valuation
    fx_work = []
    if A:
        cum = sum(fn(principal[k], rate_end) - cost[k] for k in ins)
        mv = cum - open_tb[1220]
        post(Q_END, 'FX_TRANSL', f"FX/{Q_END:%d%b%y}".upper(), [(4700, -mv, {}), (1220, mv, {})], 'FX_Rates csv + Deal_Master (recomputed)', f"FX translation of INR assets at {rate_end}")
        fx_work = [dict(instrument=k, inr=principal[k], rate=rate_end, translated=fn(principal[k], rate_end), cost=cost[k], cumulative=fn(principal[k], rate_end) - cost[k]) for k in ins]
    VI = X['valuation_inputs']
    vrows = VI['summary']
    vcov = VI['cover']
    adj_fn = {}
    val_items = {}
    fv_hdr = 'FV adjustment (' + ('USD' if A else 'INR cr')
    for k, r in vrows.items():
        a = fn(num(r['FV adjustment (INR cr)']), rate_end)
        adj_fn[k] = a
        mv_ = a - num(col(open_ins[k], fv_hdr))
        val_items[k] = dict(adj_fn=a, movement_fn=mv_, row=r)
        if mv_:
            m_ = {'instrument': k, **txm(num(r['FV adjustment (INR cr)']), rate_end)}
            post(Q_END, 'VALUATION', f"VAL/{k}/{Q_END:%d%b%y}".upper(), [(1210, mv_, dict(m_)), (4600, -mv_, dict(m_))], f"Valuation_Inputs Summary!row {r['_row']}",
                 f"Fair-value adjustment {k} ({dmy(Q_END)} valuation)", sortkey=k)

    # ---------------- order and number the journals ----------------
    def jkey(j):
        sk = j['sortkey']
        if j['kind'] in INS_SUB:
            sk = sk
        elif j['kind'] in ('CALL_RCPT', 'DIST_PAY', 'EXP_PAY', 'LPI', 'DISB'):
            sk = (str(sk).zfill(6), 0)
        else:
            sk = (str(sk) if sk is not None else '', 0)
        return (j['date'], KIND_RANK[j['kind']], sk if isinstance(sk, tuple) else (sk, 0), j['seq'])
    J.sort(key=jkey)
    seq0 = int(settings.get('journal_seq_start', 1))
    for n, j in enumerate(J):
        j['no'] = f"{sid}-JV-{seq0 + n:04d}"

    # ---------------- trial balance, NAV, capital accounts ----------------
    tq = {}
    for j in J:
        for l in j['lines']:
            tq[l['gl']] = tq.get(l['gl'], D(0)) + l['amt']
    close_tb = dict(open_tb)
    for g, a in tq.items():
        close_tb[g] = close_tb.get(g, D(0)) + a
    nav = lambda t: sum(a for g, a in t.items() if TYPE.get(g) in ('a', 'l'))
    nav_open, nav_close = nav(open_tb), nav(close_tb)
    pl = {}
    for g, a in tq.items():
        if g in CAT:
            pl[CAT[g]] = pl.get(CAT[g], D(0)) - a
    wa = {k: v for k, v in w.items() if inv[k]['cls'] == 'A'}
    alloc = {c: prorate(pl.get(c, D(0)), wa if c == 'fee' else w) for c in ('income', 'fee', 'expense', 'fv', 'fx')}
    UR = X['units']
    ul = UR['ledger']
    hold = {r['Investor ID']: r for r in UR['holdings']}
    cap = {}
    for k in inv:
        o = num(col(open_cap[k], 'Opening capital'))
        units = int(open_cap[k]['Units']) + units_new.get(k, 0)
        c = o + called.get(k, D(0)) - dist[k]['gross'] + sum(alloc[x].get(k, D(0)) for x in alloc)
        cap[k] = dict(cls=inv[k]['cls'], opening=o, contributions=called.get(k, D(0)), distributions_roc=D(0), distributions_income=-dist[k]['gross'],
                      income_alloc=alloc['income'].get(k, D(0)), fee_alloc=alloc['fee'].get(k, D(0)), expense_alloc=alloc['expense'].get(k, D(0)),
                      fv_alloc=alloc['fv'].get(k, D(0)), fx_alloc=alloc['fx'].get(k, D(0)), carry_alloc=D(0), closing=c, units=units,
                      units_open=int(open_cap[k]['Units']), nav_per_unit=q(c * sc / units, 4))
    cls_nav = {c: sum(v['closing'] for k, v in cap.items() if inv[k]['cls'] == c) for c in ('A', 'B')}
    cls_units = {c: sum(v['units'] for k, v in cap.items() if inv[k]['cls'] == c) for c in ('A', 'B')}
    cls_units_open = {c: sum(v['units_open'] for k, v in cap.items() if inv[k]['cls'] == c) for c in ('A', 'B')}
    classes = {c: dict(nav=cls_nav[c], units=cls_units[c], nav_per_unit=q(cls_nav[c] * sc / cls_units[c], 4) if cls_units[c] else D(0), units_open=cls_units_open[c]) for c in ('A', 'B')}

    # ================= RULES =================
    days = sorted({b['date'] for b in bank})
    bad = []
    gl_bal = open_tb[1100]
    cash_by_day = {}
    for j in J:
        for l in j['lines']:
            if l['gl'] == 1100:
                cash_by_day[j['date']] = cash_by_day.get(j['date'], D(0)) + l['amt']
    for d_ in sorted(set(days) | set(cash_by_day)):
        gl_bal += cash_by_day.get(d_, D(0))
        st = [b['bal'] for b in bank if b['date'] <= d_]
        if u(st[-1] if st else open_bank) != gl_bal:
            bad.append(f"{d_}: bank {u(st[-1]) if st else ''} vs GL {gl_bal}")
    add('R1', 'Bank = GL cash on every transaction day (opening and each day-end)', not bad and u(open_bank) == open_tb[1100], f"bank close {bank[-1]['bal']:,.2f}",
        f"GL 1100 {close_tb[1100] * sc:,.2f}", f"{len(days)} day-ends compared; opening {open_bank:,.2f}" + ('; ' + '; '.join(bad[:3]) if bad else ''), f"{stem} ({prim}) vs journals")
    ncash = sum(1 for j in J for l in j['lines'] if l['gl'] == 1100)
    unm = [bank[k]['loc'] for k in range(len(bank)) if k not in used]
    add('R2', 'Every bank line matched to exactly one journal cash line (amount, date, reference)', not unm and ncash == len(bank) and not issues,
        f"{len(bank)} bank lines", f"{ncash} journal cash lines, {len(unm)} unmatched", '; '.join(issues + unm) or 'zero unmatched', f"{stem} ({prim})")
    # R4 custody
    dtx = X['demat_txn']
    hold_pdf = X['demat_holding']['hold']
    ok = True
    det = []
    for k, x in ins.items():
        ob = next(int(r['Balance']) for r in dtx if r['ISIN'] == x['isin'] and r['Particulars'] == 'Opening Balance')
        cb = next(int(r['Balance']) for r in dtx if r['ISIN'] == x['isin'] and r['Particulars'] == 'Closing Balance')
        cr = [(dt(r['Date']), int(r['Credit'])) for r in dtx if r['ISIN'] == x['isin'] and r['Credit']]
        exp_cr = [(t['demat'], t['units']) for t in q_tr if t['ins'] == k]
        good = ob == int(open_ins[k]['Quantity']) and cb == qty[k] == hold_pdf.get(x['isin']) and cr == exp_cr and sum(t['units'] for t in tranches if t['ins'] == k) == qty[k]
        ok &= good
        det.append(f"{k}: open {ob:,} / close {cb:,} / credits {len(cr)}")
    add('R4', f'Custody = instrument register (holdings {OPEN_DT:%d-%b} and {Q_END:%d-%b}; credits = tranche units on allotment date)', ok, '; '.join(det),
        '; '.join(f"{k}: {int(open_ins[k]['Quantity']):,} / {qty[k]:,}" for k in ins), '', 'Demat_Holding_Statement pdf, Demat_Transaction_Statement csv vs Deal_Master Tranches, Opening_Balances')
    # R5 calls
    notices = CL['notices']
    n_tot = sum(u(num(n[f"Amount now called ({ccy})"])) for n in notices)
    a_tot = sum(called.values())
    r_tot = sum(r['amt'] for r in receipts.values())
    gl3100 = -sum(l['amt'] for j in J for l in j['lines'] if l['gl'] == 3100)
    n_ok = all(u(num(n[f"Amount now called ({ccy})"])) == called[n['Investor ID']] and dt(n['Due date']) == call_due and dt(n['Notice date']) == call_notice for n in notices) and len(notices) == len(inv)
    split_ok = all(num(r['Investment component']) + num(r['Fee component']) + num(r['Expense component']) == num(r['Amount called']) for r in call_rows)
    add('R5', 'Call: notices = allocation = % x commitments = receipts (+ outstanding) = bank credits = GL 3100 / 1400',
        n_ok and split_ok and n_tot == a_tot == r_tot == gl3100 == committed * pct and close_tb.get(1400, 0) == 0 and all(receipts.get(k, {}).get('amt') == called[k] for k in called),
        f"notices {n_tot} / allocation {a_tot}", f"receipts {r_tot} / GL 3100 {gl3100} / outstanding {close_tb.get(1400, D(0))}",
        f"{len(notices)} notices; {pct * 100:.0f}% of {committed}; late payers: " + (', '.join(f"{k} ({r['late']}d)" for k, r in receipts.items() if r['late'] > 0) or 'none'),
        f"CapitalCall_{ccode}_Notice_*.pdf, _Allocation.xlsx, bank, journals")
    # R6 late interest
    lr = num(terms['Late-payment interest (% p.a.)']) / 100
    exp_lpi = {k: q(r['amt'] * lr * r['late'] / 365) for k, r in receipts.items() if r['late'] > 0}
    add('R6', 'Late-payment interest = rate x days late x amount = bank receipt = GL 4500', exp_lpi == lpi and -tq.get(4500, D(0)) == sum(exp_lpi.values()),
        f"computed {dict((k, str(v)) for k, v in exp_lpi.items()) or 'none due'}", f"bank {dict((k, str(v)) for k, v in lpi.items()) or 'none'} / GL 4500 {-tq.get(4500, D(0))}",
        f"rate {lr * 100:.0f}% p.a. ACT/365 from PPM term sheet", 'PPM_Term_Sheet pdf, bank, journals')
    # R7 distributions
    dn = {n['Investor ID']: n for n in DI['notices']}
    tx = X['ppm']['tax_name']
    n_ok = len(dn) == len(dist) and all(u(num(dn[k][f"Gross distribution ({ccy})"])) == d['gross'] and u(num(dn[k][f"{tx} withheld ({ccy})"])) == d['wht']
                                        and u(num(dn[k][f"Net amount payable ({ccy})"])) == d['net'] for k, d in dist.items())
    rate_ok = all(d['rate'] == inv[k]['wht'] and d['wht'] == q(d['gross'] * inv[k]['wht']) and d['net'] == d['gross'] - d['wht'] and d['income'] == d['gross'] for k, d in dist.items())
    bank_ok = all(paid_net.get(k, {}).get('amt') == d['net'] and paid_net[k]['date'] == payd for k, d in dist.items())
    pf_ok = True
    pf_note = 'n/a (no bulk file for the onshore scheme)'
    if DI['payment_file']:
        pf = DI['payment_file']
        pf_net = sum(u(num(r[4])) for r in pf if r[0] == 'D')
        pf_ok = pf_net + twht == tgross and u(num(pf[-1][2])) == pf_net and int(pf[-1][1]) == len(dist)
        pf_note = f"payment file net {pf_net} + WHT {twht} = {pf_net + twht}"
    ch = X['challan']
    ch_amt = u(num(ch[f"Amount deposited ({ccy})"]))
    ch_ok = ch_amt == twht and dt(ch['Deposit date']) > Q_END and dt(ch['Deposit date']) == dt(dk[f"{tx} deposit due date"])
    certs = X['tax_certs']
    exp_certs = sum(1 for k in dist if inv[k]['row'].get('FME or sponsor') != 'Yes')
    cert_ok = len(certs) == exp_certs and all(u(num(c[f"{tx} amount ({ccy})"])) == dist[c['Investor ID']]['wht'] and c['Challan No'] == ch['Challan No'] for c in certs)
    add('R7', f'Distribution: schedule = notices = lines; rate from investor register; bank debits = net; GL 3200 = gross; GL 2500 = tax at {Q_END:%d-%b}; challan clears 2500 in {(Q_END + timedelta(days=1)):%b}; certificates',
        n_ok and rate_ok and bank_ok and pf_ok and ch_ok and cert_ok and tq[3200] == tgross and -close_tb[2500] == twht, f"gross {tgross} = net {tgross - twht} + {tx} {twht}",
        f"GL 3200 {tq[3200]} / GL 2500 {-close_tb[2500]} / bank net {sum(p['amt'] for p in paid_net.values())} / challan {ch_amt} on {ch['Deposit date']}",
        f"{pf_note}; {len(certs)} certificates tie; tax payable is a liability at {Q_END:%d-%b}, not in cash", f"{DI['file']}, notices, bank, {X['challan_file']}")
    # R8 accruals
    vp = {k: num(r['Principal (INR cr)']) for k, r in vrows.items()}
    cp_ok = all(('narr' in s) for s in sched.values())
    det = []
    for k, s in sched.items():
        det.append(f"{k}: cash {s['cash_inr']} cr" + (f" PIK {s['pik']} cr" if s['pik'] else '') + f" on {' + '.join(f'{p}x{n}d' for p, n in s['segs'])}")
        if A and 'narr' in s:
            m = re.search(r'/INR/ ([\d,\.]+) @ ([\d\.]+)', s['narr'])
            cp_ok &= bool(m) and num(m.group(1)) == s['cash_inr'] * 10000000 and D(m.group(2)) == rate_end
            if m:
                fx_checks.append((f"Coupon {k} {Q_END:%d-%b}", D(m.group(2)), fx.get(Q_END)))
    gl_int = -(tq.get(4100, D(0)))
    gl_pik = -(tq.get(4110, D(0)))
    add('R8', 'Accruals: schedule (ACT/365, tranche part-periods) = GL 4100/4110 = coupon receipts; 1300 clears; PIK capitalised into principal = valuer principal',
        cp_ok and gl_int == sum(s['cash_fn'] for s in sched.values()) and gl_pik == sum(s['pik'] for s in sched.values()) and close_tb.get(1300, 0) == 0 and all(vp[k] == principal[k] for k in ins),
        f"schedule cash {sum(s['cash_fn'] for s in sched.values())} / PIK {sum(s['pik'] for s in sched.values())}", f"GL 4100 {gl_int} / 4110 {gl_pik} / 1300 closing {close_tb.get(1300, D(0))}",
        '; '.join(det), 'Deal_Master, bank narrations, journals, Valuation_Inputs Summary')
    # R9 FX
    if A:
        cum = close_tb[1220]
        rec = sum(fn(principal[k], rate_end) - cost[k] for k in ins)
        add('R9', f'FX: every INR-linked journal uses the daily table; {Q_END:%d-%b} translation at {memo}; GL 1220 = recomputed', all(a == b for _, a, b in fx_checks) and rate_end == memo and cum == rec,
            '; '.join(f"{n}: {a}" for n, a, b in fx_checks) + f"; closing {rate_end}", f"table: {'; '.join(str(b) for _, a, b in fx_checks)}; 1220 cumulative {cum} (movement {tq[1220]})",
            '; '.join(f"{k}: INR {principal[k]} cr -> {fn(principal[k], rate_end)} vs cost {cost[k]}" for k in ins), f"{files['fx_rates'][0]}, Deal_Master Tranches, bank narrations")
    else:
        add('R9', 'FX', True, 'not applicable', 'INR scheme - no FX', '', '', 'N/A')
    # R10 valuation
    rep = X['valuation_report']['table']
    vkv = X['valuation_report']['kv']
    cal = X['calendar']
    vrow = next(r for r in cal if 'aluation' in r['Obligation'])
    recd = dt(vcov['Received by FME'])
    ok = all(rep[k] == (num(r['Principal (INR cr)']), num(r['FV adjustment (INR cr)']), num(r['Fair value (INR cr)'])) and rep[k][2] == rep[k][0] + rep[k][1] for k, r in vrows.items()) \
        and close_tb[1210] == sum(adj_fn.values()) and dt(vrow['Completed / filed date']) <= recd + timedelta(days=15) and dt(vrow['Due date']) == recd + timedelta(days=15) \
        and dt(vkv['Report date']) == dt(vcov['Report date (date)'])
    add('R10', 'Valuation: report PDF = inputs workbook; GL 1210 = fair-value adjustment; dispatch within 15 days of receipt', ok, '; '.join(f"{k}: FV {v[2]} cr (adj {v[1]})" for k, v in rep.items()),
        f"GL 1210 {close_tb[1210]} (movement {tq.get(1210, D(0))}); received {recd:%d-%b}, dispatched {dt(vrow['Completed / filed date']):%d-%b}, limit {recd + timedelta(days=15):%d-%b}", '',
        'Valuation_Report pdf p.1 table 2, Valuation_Inputs xlsx, calendar')
    # R11 trial balances
    TT = X['tally']['tb']
    tled = TT['ledgers']
    gt = TT['grand_total']
    sums = [sum(v[i] for v in tled.values()) for i in range(6)]
    add('R11', f'GL trial balance: debits = credits at {OPEN_DT:%d-%b} and {Q_END:%d-%b}', sum(open_tb.values()) == 0 and sum(close_tb.values()) == 0,
        f"{OPEN_DT:%d-%b} Dr {sum(a for a in open_tb.values() if a > 0)} / Cr {-sum(a for a in open_tb.values() if a < 0)}",
        f"{Q_END:%d-%b} Dr {sum(a for a in close_tb.values() if a > 0)} / Cr {-sum(a for a in close_tb.values() if a < 0)}", '', f"{files['opening_balances'][0]} + journals")
    add('R11', 'Tally trial balance: opening, transactions and closing each balance; ledger rows foot to Grand Total', gt[0] == gt[1] and gt[2] == gt[3] and gt[4] == gt[5] and sums == gt,
        f"opening {gt[0]:,.2f} / {gt[1]:,.2f}; transactions {gt[2]:,.2f} / {gt[3]:,.2f}", f"closing {gt[4]:,.2f} / {gt[5]:,.2f}", f"{len(tled)} ledgers", X['tally']['files']['tb'])
    # R12 Tally
    V = X['tally']['vouchers']
    v_bal = all(sum(a for _, a, _ in v['lines']) == 0 and all((a > 0) == (f == 'Yes') for _, a, f in v['lines']) for v in V)
    xml_dr = {}
    xml_cr = {}
    for v in V:
        for l, a, _ in v['lines']:
            if a > 0:
                xml_dr[l] = xml_dr.get(l, D(0)) + a
            else:
                xml_cr[l] = xml_cr.get(l, D(0)) - a
    tb_tx = all(tled.get(l, [0] * 6)[2] == xml_dr.get(l, 0) and tled.get(l, [0] * 6)[3] == xml_cr.get(l, 0) for l in set(xml_dr) | set(xml_cr) | set(tled))
    lm = {r['Name of Ledger']: (num(r['Opening Balance']) if r['Dr/Cr'] == 'Dr' else -num(r['Opening Balance'])) for r in X['tally']['ledgers']}
    lm_ok = all(lm[l] == v[0] - v[1] for l, v in tled.items())
    add('R12', 'Tally day book: every voucher balances; TB transactions = XML; ledger-master openings = TB openings', v_bal and tb_tx and lm_ok, f"{len(V)} vouchers", f"{len(tled)} ledgers", '',
        f"{X['tally']['files']['daybook']}, TB, LedgerMasters")
    conv = (sc * memo) if A else sc
    tclose = {}
    topen = {}
    for l, v in tled.items():
        g = led2gl(l)
        tclose[g] = tclose.get(g, D(0)) + (v[4] - v[5]) / conv
        topen[g] = topen.get(g, D(0)) + (v[0] - v[1]) / conv
    v2j = {}
    if not A:
        sig = lambda d_, lines: (d_, tuple(sorted((g, q(a, 6)) for g, a in lines)))
        pool = {}
        for j in sorted(J, key=lambda j: j['seq']):
            pool.setdefault(sig(j['date'], [(l['gl'], l['amt']) for l in j['lines']]), []).append(j)
        unmatched_v = []
        for v in V:
            agg = {}
            for l, a, _ in v['lines']:
                agg[led2gl(l)] = agg.get(led2gl(l), D(0)) + a / conv
            s = sig(v['date'], list(agg.items()))
            s2 = None
            if pool.get(s):
                v2j[v['no']] = pool[s].pop()
            else:
                for key, js in pool.items():
                    if js and key[0] == v['date']:
                        ag2 = {}
                        for g, a in key[1]:
                            ag2[g] = ag2.get(g, D(0)) + a
                        if {g: q(a, 6) for g, a in agg.items()} == ag2:
                            s2 = key
                            break
                if s2:
                    v2j[v['no']] = pool[s2].pop()
                else:
                    unmatched_v.append(v['no'])
        left = sum(len(x) for x in pool.values())
        diffs = {g: tclose.get(g, D(0)) - close_tb.get(g, D(0)) for g in set(tclose) | set(close_tb) if tclose.get(g, D(0)) != close_tb.get(g, D(0))}
        add('R12', 'Tally bridge (statutory book): every voucher <-> one GL journal; TB ledger balances = mapped GL balances (100%)', not unmatched_v and left == 0 and not diffs,
            f"{len(V)} vouchers, {len(unmatched_v)} unmatched", f"{len(J)} journals, {left} unmatched; {len(diffs)} GL balance differences", '', 'Tally XML/TB vs journals')
        bridge = []
    else:
        key = lambda d_, tot, c: (d_, q(tot, 2), c)
        pool = {}
        for j in sorted(J, key=lambda j: j['seq']):
            pool.setdefault(key(j['date'], sum(l['amt'] for l in j['lines'] if l['amt'] > 0) * sc, any(l['gl'] == 1100 for l in j['lines'])), []).append(j)
        bridge = []
        expl = {}
        unmatched_v = []
        memo_ok = True

        def explain(g, a, code):
            expl[(g, code)] = expl.get((g, code), D(0)) + a
        for v in V:
            tot_inr = sum(a for _, a, _ in v['lines'] if a > 0)
            usd = tot_inr / memo
            k = key(v['date'], usd, any(led2gl(l) == 1100 for l, _, _ in v['lines']))
            m = re.search(r'\(USD ([\d,\.]+) @ ([\d\.]+)\)', v['narr'])
            memo_ok &= bool(m) and num(m.group(1)) == q(usd, 2) and D(m.group(2)) == memo
            if not pool.get(k):
                unmatched_v.append(v['no'])
                continue
            j = pool[k].pop(0)
            v2j[v['no']] = j
            daily = fxon(v['date'])
            d_m = tot_inr - usd * daily
            bridge.append(dict(voucher=v['no'], date=str(v['date']), journal=j['ref'], tally_inr=f"{tot_inr:,.2f}", gl_usd=f"{usd:,.2f}", daily_rate=str(daily), code='M',
                               difference_inr=f"{d_m:,.2f}", reason=f"memo-rate restatement: recorded at {memo}, daily rate {daily}"))
            tg, jg = {}, {}
            for l, a, _ in v['lines']:
                tg[led2gl(l)] = tg.get(led2gl(l), D(0)) + a / conv
            for l in j['lines']:
                jg[l['gl']] = jg.get(l['gl'], D(0)) + l['amt']
            for g in set(tg) | set(jg):
                if q(tg.get(g, 0), 6) != q(jg.get(g, 0), 6):
                    explain(g, tg.get(g, D(0)) - jg.get(g, D(0)), 'A')
                    bridge.append(dict(voucher=v['no'], date=str(v['date']), journal=j['ref'], gl=g, code='A', difference_usd_m=str(q(tg.get(g, D(0)) - jg.get(g, D(0)), 6)),
                                       reason='cash-basis entry in Tally; accrual / receivable entry in GL'))
        left = [j for js in pool.values() for j in js]
        bad_left = []
        for j in left:
            code = 'F' if j['kind'] == 'FX_TRANSL' else ('A' if j['kind'] in ('ACCR_INT', 'ACCR_FEE', 'ACCR_EXP', 'ACCR_PIK', 'PIK_CAP', 'CALL_ISSUE') else None)
            if not code:
                bad_left.append(j['ref'])
                continue
            for l in j['lines']:
                explain(l['gl'], -l['amt'], code)
            bridge.append(dict(voucher='(none)', date=str(j['date']), journal=j['ref'], code=code, difference_usd_m=str(sum(l['amt'] for l in j['lines'] if l['amt'] > 0)),
                               reason='FX translation not booked in Tally' if code == 'F' else 'accrual / receivable not booked in Tally'))
        for g in set(topen) | set(open_tb):
            dlt = q(topen.get(g, D(0)) - open_tb.get(g, D(0)), 6)
            if dlt:
                code = 'F' if g == 1220 else 'A'
                if g == 3900:
                    explain(g, dlt + open_tb.get(1220, D(0)), 'A')
                    explain(g, -open_tb.get(1220, D(0)), 'F')
                    bridge.append(dict(voucher='(opening)', journal='opening 3900', gl=g, code='A+F', difference_usd_m=str(dlt), reason='prior-period accruals (A) and FX translation (F) not in Tally'))
                else:
                    explain(g, dlt, code)
                    bridge.append(dict(voucher='(opening)', journal=f'opening {g}', gl=g, code=code, difference_usd_m=str(dlt),
                                       reason='prior-period ' + ('FX translation' if code == 'F' else 'accrual') + ' not in Tally'))
        resid = {}
        for g in set(tclose) | set(close_tb):
            r_ = q(tclose.get(g, D(0)) - close_tb.get(g, D(0)) - sum(a for (gg, c), a in expl.items() if gg == g), 6)
            if r_:
                resid[g] = r_
        add('R12', 'Tally bridge (memo-rate book): every voucher matched; every GL journal without a voucher and every ledger difference explained by M / A / F; residual nil',
            not unmatched_v and not bad_left and not resid and memo_ok, f"{len(V)} vouchers matched, {len(unmatched_v)} unmatched; narration USD x {memo} = INR on every voucher",
            f"{len(left)} GL journals not in Tally (codes {', '.join(sorted({('F' if j['kind'] == 'FX_TRANSL' else 'A') for j in left}))}); unexplained residual by GL: {resid or 'nil'}",
            f"{len(bridge)} bridge lines written to validation_report.json; M total INR {sum(num(b['difference_inr']) for b in bridge if b['code'] == 'M'):,.2f}", 'Tally XML/TB vs journals, FX table')
    for vno, j in v2j.items():
        j['tally'] = vno
    # R13 NAV
    reg_units = {k: int(v[f"Units at {Q_END:%d-%b-%Y}"]) for k, v in hold.items()}
    led_units = {}
    for r in ul:
        led_units[r['Investor ID']] = led_units.get(r['Investor ID'], 0) + int(r['Units'])
    add('R13', 'NAV = assets - liabilities = sum of capital accounts = sum of class NAVs; units = unit register',
        nav_close == sum(c['closing'] for c in cap.values()) == sum(cls_nav.values()) and nav_open == sum(c['opening'] for c in cap.values())
        and reg_units == led_units == {k: c['units'] for k, c in cap.items()}, f"NAV {nav_close} ({ccy} {nav_close * sc:,.2f}); opening {nav_open}",
        f"capital accounts {sum(c['closing'] for c in cap.values())}; class A {cls_nav['A']} / B {cls_nav['B']}; units {sum(reg_units.values()):,} (A {cls_units['A']:,} / B {cls_units['B']:,})",
        f"NAV per unit: fund {q(nav_close * sc / sum(reg_units.values()), 4)}, class A {classes['A']['nav_per_unit']}, class B {classes['B']['nav_per_unit']} (fee charged to class A only)",
        'journals, Unit_Register xlsx (Unit Ledger, Holdings)')
    # R14 performance
    calls = hist_calls + [(call_due, a_tot)]
    dists = [(payd, tgross)]
    paid = sum(a for _, a in calls)
    perf = dict(paid_in=paid, distributed=tgross, nav=nav_close, irr=xirr([(d_, -a) for d_, a in calls] + dists + [(Q_END, nav_close)]), tvpi=q((tgross + nav_close) / paid, 6),
                dpi=q(tgross / paid, 6), rvpi=q(nav_close / paid, 6))
    hurdle = num(terms['Hurdle rate (% p.a.)']) / 100
    carry_rate = num(terms['Carried interest (%)']) / 100
    carry = carry_on_liquidation(nav_close, calls, dists, hurdle, carry_rate, Q_END)
    e = (expected or {}).get(sid)
    if e:
        ep = e['performance']
        add('R14', 'Performance recomputed from call due dates, distribution dates and NAV (paid-in denominators); carry provision on hypothetical liquidation',
            abs(perf['irr'] - ep['irr']) < 1e-6 and all(D(ep[k]) == perf[k] for k in ('paid_in', 'distributed', 'tvpi', 'dpi', 'rvpi')) and carry == D(e['carry_provision']),
            f"IRR {perf['irr'] * 100:.4f}% TVPI {perf['tvpi']} DPI {perf['dpi']} RVPI {perf['rvpi']}; carry {carry}",
            f"expected IRR {ep['irr'] * 100:.4f}% TVPI {ep['tvpi']} DPI {ep['dpi']} RVPI {ep['rvpi']}; carry {e['carry_provision']}",
            f"{len(calls)} calls, 1 distribution; NAV below hurdle so carry provision is nil" if carry == 0 else f"{len(calls)} calls, 1 distribution; carry provision {carry}",
            'Opening_Balances Calls, call allocation, distribution schedule, journals')
    else:
        add('R14', 'Performance recomputed from call due dates, distribution dates and NAV (paid-in denominators); carry provision on hypothetical liquidation', True,
            f"IRR {perf['irr'] * 100:.4f}% TVPI {perf['tvpi']} DPI {perf['dpi']} RVPI {perf['rvpi']}; carry {carry}", 'no expected results supplied',
            f"{len(calls)} calls, 1 distribution", 'Opening_Balances Calls, call allocation, distribution schedule, journals')
    # R15 prior report ties to the locked opening books
    q1 = X['prior_report']['kv']
    q1i = X['prior_report']['investors']
    ok = num(q1['Net asset value']) == nav_open and num(q1['Cumulative drawn']) == -open_tb[3100] and num(q1['Cash and bank']) == open_tb[1100] and num(q1['Investments at cost']) == open_tb[1200] \
        and num(q1['Total commitments']) == committed == sum(num(col(r, 'Commitment')) for r in q1i)
    add('R15', f"Reports: {P['prev_label']} report as filed ties to the locked {OPEN_DT:%d-%b} books and registers (layout reused for {P['label'].split(' ')[0]})", ok,
        f"report NAV {num(q1['Net asset value'])}, drawn {num(q1['Cumulative drawn'])}", f"books NAV {nav_open}, drawn {-open_tb[3100]}",
        f"Generate the {P['label']} report in the Report centre once the NAV is locked: the workbook is read back with the same parser and tied to the closing books, and this check then passes.",
        X['prior_report_file'], 'PARTIAL' if ok else 'FAIL')
    # R16 calendar evidence
    reg = {r['rel']: r for r in X['register']}
    done = [r for r in cal if r['Status'] in ('Filed', 'Done')]
    bad = [r['Ref'] for r in done if not r.get('Evidence file') or r['Evidence file'] not in reg]
    add('R16', 'Calendar: every Filed / Done obligation has an evidence file that exists and matches its manifest hash', not bad, f"{len(done)} filed/done of {len(cal)} obligations",
        f"{len(done) - len(bad)} with verified evidence", f"{sum(1 for r in cal if r.get('Verify'))} rows carry a verify flag (reconstructed dates)" + (f"; missing: {bad}" if bad else ''), X['calendar_file'])
    # R17 KYC gate
    kyc = X['kyc']['register']
    bad = [r['Investor ID'] for r in kyc if r['Status'] != 'Complete' and r['Investor ID'] in called and not dt(r['Next refresh date']) > call_notice]
    add('R17', 'KYC gate: no investor with status other than Complete is in the call unless its refresh falls due after the call date', not bad and len(kyc) == len(inv),
        '; '.join(f"{r['Investor ID']}: {r['Status']} (refresh {dt(r['Next refresh date']):%d-%b-%Y})" for r in kyc if r['Status'] != 'Complete') or 'all Complete',
        f"call notice date {call_notice:%d-%b-%Y}", '', files['kyc_register'][0] + ', call allocation')
    # R18 covenants
    mis_by_ins = {}
    ok = True
    det = []
    breaches = []
    months = [m for m in sorted({mo for spv in X['mis'].values() for mo in spv}, key=lambda s: dt('01-' + s[:3] + '-20' + s[3:]))]
    for k, x in ins.items():
        sold = coll = D(0)
        for mth in months:
            mm = X['mis'][x['spv']][mth]['fields']
            sold += num(mm['sold']['vals'][-1][1])
            coll += num(mm['coll']['vals'][-1][1])
        cc = X['covenant_certs'][x['spv']]
        ck_ = cc['kv']
        cover = q(coll / cov_ds[k], 2)
        mins = {r['Test']: num(r['Minimum']) for r in cov_terms if r['Instrument ID'] == k}
        vel_key = next(t for t in mins if 'velocity' in t.lower())
        cov_key = next(t for t in mins if 'cover' in t.lower())
        exp_res = {'Sales velocity': 'PASS' if sold >= mins[vel_key] else 'BREACH', 'Collection cover': 'PASS' if cover >= mins[cov_key] else 'BREACH'}
        got = {('Sales velocity' if 'velocity' in r[0] else 'Collection cover'): (r[1], r[2], r[3]) for r in cc['tests']}
        good = num(ck_['Units sold in quarter']) == sold and num(ck_['Collections in quarter (INR cr)']) == coll and got['Sales velocity'][1] == sold and got['Collection cover'][1] == cover \
            and all(got[t][2] == exp_res[t] for t in got) and got['Sales velocity'][0] == mins[vel_key] and got['Collection cover'][0] == mins[cov_key]
        ok &= good
        det.append(f"{x['spv']}: sold {sold} (min {mins[vel_key]}), cover {cover} (min {mins[cov_key]})")
        breaches += [f"{x['spv']} {t}" for t in exp_res if exp_res[t] == 'BREACH']
        mis_by_ins[k] = dict(sold=sold, coll=coll, cover=cover, ds=cov_ds[k], mins=mins, vel_key=vel_key, cov_key=cov_key)
    bn = [r for r in cal if 'breach notice' in r['Obligation'].lower()]
    bd = Q_END
    n = 0
    while n < 10:
        bd += timedelta(days=1)
        n += bd.weekday() < 5
    bn_ok = (not breaches and not bn) or (breaches and bn and dt(bn[0]['Due date']) == bd)
    exp_ok = True
    if e and e.get('covenants') is not None:
        exp_ok = sorted(breaches) == sorted(f"{ins[i]['spv']} {'Sales velocity' if 'velocity' in t else 'Collection cover'}" for i, c in e['covenants'].items() for t in c['breached'])
    add('R18', 'Covenants: MIS Jul-Sep actuals (two developer layouts) = covenant certificates; breach flags; breach-notice due date'.replace('Jul-Sep', f"{months[0][:3]}-{months[-1][:3]}" if months else 'Jul-Sep'),
        ok and bn_ok and exp_ok, '; '.join(det),
        f"breaches: {', '.join(breaches) or 'none'}" + (f"; notice due {bd:%d-%b-%Y} (10 business days, weekends only) = calendar {dt(bn[0]['Due date']):%d-%b-%Y}" if bn else ''), '',
        f"Developer_MIS_*.xlsx ({sum(len(v) for v in X['mis'].values())} files), Covenant_Certificate_*.pdf, Deal_Master Covenants, calendar")
    # R19 limits
    unit_lbl = 'USD m' if A else 'INR cr'
    lim = num(terms['Single-investee limit (% of investable funds)']) / 100
    target = num(terms[f"Target corpus ({unit_lbl})"])
    mc = num(terms[f"Minimum corpus ({unit_lbl})"])
    big = max(cost.values())
    bk_ = max(cost, key=cost.get)
    on_t = big / target
    on_c = big / committed
    borrow = sum(a for g, a in close_tb.items() if 2600 <= g < 2700)
    st_ = 'PASS' if on_c <= lim else ('WARN' if on_t <= lim else 'FAIL')
    add('R19', 'Limits: single-investee exposure, leverage, corpus >= minimum (PPM terms)', st_ != 'FAIL' and committed >= mc and borrow == 0,
        f"largest {bk_} cost {big}: {on_t * 100:.2f}% of target corpus {target}; {on_c * 100:.2f}% of commitments {committed}",
        f"limit {lim * 100:.0f}% of investable funds; leverage {borrow} (limit nil); corpus {committed} >= minimum {mc}",
        '' if st_ == 'PASS' else f"WITHIN the limit only if investable funds are measured on target corpus; on total commitments the exposure is {on_c * 100:.2f}% and exceeds {lim * 100:.0f}%. The brief's Section 6 amounts produce this - decision needed (see docs/known_limitations.md).",
        'PPM_Term_Sheet pdf, Deal_Master, journals', st_ if committed >= mc and borrow == 0 else 'FAIL')
    # supplementary
    if X['fcgpr']:
        fc = X['fcgpr'][0]
        t2 = next((t for t in q_tr if t['ins'] == fc.get('Instrument ID')), None)
        if t2:
            add('S1', 'FEMA: FC-GPR allotment date = tranche date; due = allotment + 30 days; filed on or before due',
                dt(fc['Allotment date']) == t2['date'] and dt(fc['Due date']) == t2['date'] + timedelta(days=30) and dt(fc['Filed date']) <= dt(fc['Due date']),
                f"allotment {fc['Allotment date']}, filed {fc['Filed date']}", f"due {fc['Due date']}", f"ack {fc['Acknowledgement No']}", f"{files['fcgpr'][0]}, Deal_Master Tranches")
    fr = num(terms['Management fee rate (% p.a.)']) / 100
    f2k = fee_inv[QC]
    fee_calc = q(committed * fr / 4)
    fee_doc = u(num(f2k[f"Management fee ({ccy})"]))
    a_only = q(sum(wa.values()) * fr / 4, 6)
    fee_ok = fee_calc == fee_doc and tq[5100] == u(num(f2k[tot_key]))
    add('S2', 'Fee engine: rate x commitments x 1/4 = invoice (+ GST) = GL 5100', fee_ok, f"computed {fee_calc} (+ GST {u(num(f2k['GST (' + ccy + ')']))})", f"invoice {fee_doc}; GL 5100 {tq[5100]}",
        f"Fee base is TOTAL commitments ({committed}) as in the brief's golden totals; on Class A commitments only ({sum(wa.values())}) the fee would be {a_only}. Decision needed.",
        f"{f2k['_file']}, PPM_Term_Sheet", 'WARN' if fee_ok and fee_calc != a_only else ('PASS' if fee_ok else 'FAIL'))
    # golden totals (only when an expected-results file was supplied, i.e. acceptance testing)
    if e:
        def cmp_tb(exp_tb, got):
            return all(eq(D(v), got.get(int(g), D(0)), D(0)) for g, v in exp_tb.items()) and all(str(g) in exp_tb or a == 0 for g, a in got.items())
        g_ok = cmp_tb(e['opening_tb'], open_tb) and cmp_tb(e['closing_tb'], close_tb) and D(e['nav_close']) == nav_close and D(e['bank']['closing']) == u(bank[-1]['bal']) \
            and int(e['units_total']) == sum(reg_units.values()) \
            and all(D(e['capital_accounts'][k]['closing']) == c['closing'] and D(e['capital_accounts'][k]['opening']) == c['opening'] and D(e['capital_accounts'][k]['nav_per_unit']) == c['nav_per_unit'] for k, c in cap.items()) \
            and all(e['custody'][x['isin']]['close'] == qty[k] for k, x in ins.items()) and D(e['wht_payable']) == twht and e['counts']['journals_q2'] == len(J) and e['counts']['bank_lines'] == len(bank)
        add('G1', 'Golden totals: books rebuilt from the source files = expected_results.json (TBs, NAV, capital accounts, bank, custody, tax payable, counts) - exact', g_ok,
            f"rebuilt NAV {nav_close}, cash {close_tb[1100]}, {len(J)} journals", f"expected NAV {e['nav_close']}, cash {e['bank']['closing']}, {e['counts']['journals_q2']} journals", '', 'expected_results.json')

    # ---------------- accrual history per instrument (from the tranche register) ----------------
    accr_hist = {}
    rates_known = {OPEN_DT: op['closing_rate']} if A else {}
    booked = settings.get('accrual_history', {})      # prior quarters as booked (from earlier runs or migrated history)
    for k, x in ins.items():
        if not (x['cash'] or x['pik']):
            continue
        trs = sorted([t for t in tranches if t['ins'] == k], key=lambda t: t['date'])
        qe = quarter_end(trs[0]['date'])
        prin = D(0)
        rows = []
        while qe <= Q_END:
            qs = prev_quarter_end(qe)
            opening = prin
            segs = []
            if opening > 0:
                segs.append(('Opening principal', opening, (qe - qs).days))
            for t in trs:
                if qs < t['date'] <= qe:
                    segs.append((f"Tranche {t['no']} from {dmy(t['date'])}", t['inr'], (qe - t['date']).days))
            c_ = q(sum(p * x['cash'] * dd / 365 for _, p, dd in segs))
            p_ = q(sum(p * x['pik'] * dd / 365 for _, p, dd in segs))
            prin = opening + sum(t['inr'] for t in trs if qs < t['date'] <= qe) + p_
            rate = (rate_end if qe == Q_END else rates_known.get(qe)) if A else D(1)
            fn_ = (fn(c_, rate) + p_ if rate else None) if A else c_ + p_
            if qe == Q_END and k in sched:
                fn_ = sched[k]['cash_fn'] + (sched[k]['pik'] if not A else D(0))
            elif qcode(qe) in booked.get(k, {}):
                h_ = booked[k][qcode(qe)]
                rate = D(str(h_['rate'])) if h_.get('rate') is not None else rate
                fn_ = D(str(h_['fn'])) if h_.get('fn') is not None else fn_
            rows.append(dict(period=qcode(qe), start=qs + timedelta(days=1), end=qe, opening=opening, segs=[dict(n=n_, p=p, d=dd) for n_, p, dd in segs], cash=c_, pik=p_,
                             closing=prin, rate=rate, fn=fn_))
            qe = quarter_end(qe + timedelta(days=1))
        accr_hist[k] = rows

    return dict(
        sid=sid, A=A, scale=sc, ccy=ccy, memo=memo, period=P, journals=J, bank=bank, bank_primary=prim, open_bank=open_bank, open_tb=open_tb, close_tb=close_tb, tq=tq,
        nav_open=nav_open, nav_close=nav_close, pl=pl, capital=cap, classes=classes, performance=perf, carry=carry, calls_perf=calls, dists_perf=dists,
        units_total=sum(c['units'] for c in cap.values()), units_open_total=sum(c['units_open'] for c in cap.values()),
        principal=principal, principal_open=principal_open, cost=cost, qty=qty, tranches=tranches, q_tr=q_tr, sched=sched, accr_hist=accr_hist, fx_work=fx_work,
        val_items=val_items, mis_by_ins=mis_by_ins, months=months, rate_end=rate_end, inv=inv, ins=ins, committed=committed, par=par,
        call=dict(code=ccode, label=clabel, notice=call_notice, due=call_due, pct=pct, called=called, receipts=receipts, lpi=lpi, rows=call_rows, kv=ck),
        dist=dict(code=dcode, label=dlabel, decl=decl, pay=payd, gross=tgross, wht=twht, lines=dist, kv=dk),
        vend=vend, bridge=bridge, rules=R.rows, issues=issues, breaches=breaches, terms=terms, hurdle=hurdle, carry_rate=carry_rate,
    )
