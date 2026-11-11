"""Renderers part 1: bank, custody, Tally, calls, distributions."""
import csv, io
from decimal import Decimal as D
from datetime import date, timedelta
import openpyxl
from .core import q, dmy, MEMO, Q_START, Q_END, OPEN_DT, GL, MANAGER, MAKER, CHECKER
from .base import *


def ctx(B):
    S = B.S; A = S['id'] == 'A'
    return S, A, S['folder'], (us if A else ind), (lambda x: q(D(x) * S['scale'], 2)), S['ccy']


def lh(S):
    return (S['name'], f"{S['category']} · {S['regulator']} Reg. No. {S['reg_no']} · Trustee: {S['providers']['trustee']} · "
                       f"{'FME' if S['id'] == 'A' else 'Investment Manager'}: {MANAGER['name']} · "
                       f"{MANAGER['addr_ifsc'] if S['id'] == 'A' else MANAGER['addr_in']}")


def r_bank(o, B):
    S, A, F, mf, base, cur = ctx(B); bk = S['bank']
    stem = f"{F}/IBU_Statement_SchemeA_USD_Jul-Sep26" if A else f"{F}/Bank_Statement_SchemeB_INR_Jul-Sep26"
    acname = f"{S['providers']['trustee'].upper()} A/C {S['name'].upper()}"
    ob = base(B.open_cash); feeds = ['bank_account', 'bank_line']
    hdr = ['Txn date', 'Value date', 'Narration', 'Cheque/Ref', 'Debit', 'Credit', 'Balance'] if A else ['Date', 'Narration', 'Chq/Ref', 'Withdrawal', 'Deposit', 'Balance']
    rows = []
    for b in B.bank:
        a = base(b['amt']); dr, cr = (mf(-a), '') if a < 0 else ('', mf(a))
        r = [dmy(b['date']), dmy(b['value_date']), b['narration'], b['ref'], dr, cr, mf(base(b['balance']))]
        rows.append(r if A else r[:1] + r[2:])
    n = len(hdr); num = (n - 3, n - 2, n - 1)
    info = kv([('Account name', acname), ('Account number', bk['acct']), ('Currency', cur), ('SWIFT' if A else 'IFSC', bk['swift'] or bk['ifsc']),
               ('Branch', bk['branch']), ('Statement period', '01-Jul-2026 to 30-Sep-2026'), ('Opening balance as on 30-Jun-2026', mf(ob))])
    per = 9; blocks = [info]; pages = [rows[i:i + per] for i in range(0, len(rows), per)]
    for k, pg in enumerate(pages):
        body = ([[dmy(OPEN_DT)] + [''] * (n - 4) + ['', '', mf(ob)]] if k == 0 else []) + pg
        if k == 0: body[0][2 if A else 1] = 'OPENING BALANCE B/F'
        td = sum(base(b['amt']) for b in B.bank[k * per:(k + 1) * per] if b['amt'] < 0); tc = sum(base(b['amt']) for b in B.bank[k * per:(k + 1) * per] if b['amt'] > 0)
        body.append(['PAGE TOTAL'] + [''] * (n - 4) + [mf(-td), mf(tc), ''])
        blocks += [table(hdr, body, num, 'stmt' if A else ''), brk() if k < len(pages) - 1 else '']
    td = sum(base(b['amt']) for b in B.bank if b['amt'] < 0); tc = sum(base(b['amt']) for b in B.bank if b['amt'] > 0)
    blocks += [kv([('Number of transactions', len(B.bank)), ('Total debits', mf(-td)), ('Total credits', mf(tc)), ('Closing balance as on 30-Sep-2026', mf(base(B.bank[-1]['balance'])))]),
               note('This is a computer-generated statement and does not require a signature. Please report discrepancies within 15 days.')]
    o.pdf(stem + '.pdf', doc('bank' if A else 'bankb', bk['name'], bk['branch'] + (' · SWIFT ' + bk['swift'] if A else ' · IFSC ' + bk['ifsc']),
                             'STATEMENT OF ACCOUNT', blocks), feeds, 'Bank (IBU)' if A else 'Bank', 'Bank & custody reconciliation', landscape=True)
    if A:
        # MT940: one statement message per booking day
        m = []; bal = ob; sn = 0
        f9 = lambda v: f"{v:.2f}".replace('.', ',')
        for d in sorted({b['date'] for b in B.bank}):
            sn += 1
            m += [f":20:FGIB{d:%y%m%d}STMT", f":25:{bk['swift']}/{bk['acct']}", f":28C:{sn:05d}/001", f":60F:C{(OPEN_DT if sn == 1 else prev):%y%m%d}USD{f9(bal)}"]
            for b in [b for b in B.bank if b['date'] == d]:
                a = base(b['amt']); bal += a
                m.append(f":61:{d:%y%m%d}{d:%m%d}{'D' if a < 0 else 'C'}{f9(abs(a))}{b['tcode']}{b['ref']}//{b['ref']}")
                nar = b['narration']; m.append(':86:' + '\n'.join(nar[i:i + 65] for i in range(0, len(nar), 65)))
            m += [f":62F:C{d:%y%m%d}USD{f9(bal)}", '-']; prev = d
        o.text(stem + '.mt940', '\n'.join(m) + '\n', feeds, 'Bank (IBU) - SWIFT MT940', 'Ingestion / Bank reconciliation', nl='\r\n')
        s = io.StringIO(); w = csv.writer(s, quoting=csv.QUOTE_MINIMAL, lineterminator='\n')
        w.writerow(['Account Name', acname]); w.writerow(['Account No', bk['acct'], 'Currency', cur]); w.writerow(['Period', '01/07/2026', '30/09/2026'])
        w.writerow(['Opening Balance', us(ob)]); w.writerow([])
        w.writerow(['Txn Date', 'Value Date', 'Narration', 'Ref No', 'Debit', 'Credit', 'Balance'])
        for b in B.bank:
            a = base(b['amt']); w.writerow([f"{b['date']:%d/%m/%Y}", f"{b['value_date']:%d/%m/%Y}", b['narration'], b['ref'], us(-a) if a < 0 else '', us(a) if a > 0 else '', us(base(b['balance']))])
        o.text(stem + '.csv', s.getvalue(), feeds, 'Bank (IBU) - CSV download', 'Ingestion / Bank reconciliation')
    else:
        import xlwt
        wb = xlwt.Workbook(); ws = wb.add_sheet('Statement'); bold = xlwt.easyxf('font: bold on'); nf = xlwt.easyxf(num_format_str='#,##0.00')
        for r, t in enumerate([bk['name'], f"Account: {bk['acct']}   IFSC: {bk['ifsc']}   Branch: {bk['branch']}", f"Account name: {acname}",
                               'Statement from 01-07-2026 to 30-09-2026']): ws.write(r, 0, t, bold if r == 0 else xlwt.Style.default_style)
        for c, t in enumerate(hdr): ws.write(5, c, t, bold)
        ws.write(6, 0, f"{OPEN_DT:%d-%m-%Y}"); ws.write(6, 1, 'OPENING BALANCE B/F'); ws.write(6, 5, float(ob), nf)
        for r, b in enumerate(B.bank, 7):
            a = base(b['amt']); ws.write(r, 0, f"{b['date']:%d-%m-%Y}"); ws.write(r, 1, b['narration']); ws.write(r, 2, b['ref'])
            if a < 0: ws.write(r, 3, float(-a), nf)
            else: ws.write(r, 4, float(a), nf)
            ws.write(r, 5, float(base(b['balance'])), nf)
        ws.col(1).width = 22000
        s = io.BytesIO(); wb.save(s); o.raw(stem + '.xls', s.getvalue(), feeds, 'Bank - XLS download', 'Ingestion / Bank reconciliation')


def sec_name(x):
    c = f"{x['cash'] * 100 + x['pik'] * 100:.2f}% " if x['cash'] else ''
    return f"{x['spv_name'].upper()} {c}{x['kind']} FV {x['fv']}"


def r_demat(o, B):
    S, A, F, mf, base, cur = ctx(B); dp = S['dp']
    holder = f"{S['providers']['trustee']} A/c {S['name']}"
    rows = [[x['isin'], sec_name(x), ind(x['fv']), f"{B.custody[x['isin']]['close']:,}", ind(D(x['fv']) * B.custody[x['isin']]['close'])] for x in S['instruments']]
    o.pdf(f"{F}/Demat_Holding_Statement_{S['short']}_30Sep26.pdf",
          doc('dp', dp['name'], f"Depository Participant · {dp['depository']} · DP ID {dp['dp_id']}", 'STATEMENT OF HOLDING AS ON 30-Sep-2026',
              [kv([('DP ID', dp['dp_id']), ('Client ID', dp['client']), ('Sole/First holder', holder), ('Account status', 'Active'), ('Statement date', '30-Sep-2026')]),
               table(['ISIN', 'Security description', 'Face value (INR)', 'Quantity (free balance)', 'Value at face (INR)'], rows, (2, 3, 4)),
               note('Value shown at face value. This statement is system generated. Pledge/lock-in balances: Nil.')]),
          ['custody_account', 'custody_holding'], 'Custodian / DP', 'Bank & custody reconciliation')
    s = io.StringIO(); w = csv.writer(s, lineterminator='\n')
    w.writerow(['DP ID', 'Client ID', 'ISIN', 'Security Name', 'Date', 'Particulars', 'Reference', 'Credit', 'Debit', 'Balance'])
    for x in S['instruments']:
        bal = B.custody[x['isin']]['open']
        w.writerow([dp['dp_id'], dp['client'], x['isin'], sec_name(x), f"{Q_START:%d-%m-%Y}", 'Opening Balance', '', '', '', bal])
        for c in [c for c in B.cust if c['isin'] == x['isin'] and c['date'] >= Q_START]:
            bal += c['qty']; w.writerow([dp['dp_id'], dp['client'], x['isin'], sec_name(x), f"{c['date']:%d-%m-%Y}", 'By Corporate Action - Allotment', c['ref'], c['qty'], '', bal])
        w.writerow([dp['dp_id'], dp['client'], x['isin'], sec_name(x), f"{Q_END:%d-%m-%Y}", 'Closing Balance', '', '', '', bal])
    o.text(f"{F}/Demat_Transaction_Statement_{S['short']}_Jul-Sep26.csv", s.getvalue(), ['custody_txn'], 'Custodian / DP', 'Bank & custody reconciliation')


def grp(l, bankled):
    if l == bankled: return 'Bank Accounts'
    for k, g in (('Investment in', 'Investments'), ('Fair Value Adj', 'Investments'), ('Interest Accrued', 'Current Assets'), ('Call Money', 'Current Assets'),
                 ('Payable', 'Current Liabilities'), ('Unit Capital', 'Capital Account'), ('Distribution to', 'Capital Account'), ('Profit & Loss', 'Primary'),
                 ('Interest on NCD', 'Direct Incomes'), ('PIK Interest', 'Direct Incomes'), ('Interest on Bank', 'Indirect Incomes'), ('Late Payment', 'Indirect Incomes'),
                 ('Unrealised Gain', 'Indirect Incomes')):
        if k in l: return 'Duties & Taxes' if ('WHT' in l or 'TDS' in l) else g
    return 'Indirect Expenses'


GORDER = ['Capital Account', 'Current Liabilities', 'Duties & Taxes', 'Investments', 'Current Assets', 'Bank Accounts', 'Direct Incomes', 'Indirect Incomes', 'Indirect Expenses', 'Primary']


def tally_tb(B):
    bl = B.S['bank']['ledger']; op, dr, cr = {}, {}, {}
    for v in B.tv[:B.n_hist_tv]:
        for l, a in v['lines']:
            k = l if grp(l, bl) not in ('Direct Incomes', 'Indirect Incomes', 'Indirect Expenses') else 'Profit & Loss A/c'
            op[k] = op.get(k, D(0)) + a
    for v in B.tv[B.n_hist_tv:]:
        for l, a in v['lines']:
            op.setdefault(l, D(0))
            if a > 0: dr[l] = dr.get(l, D(0)) + a
            else: cr[l] = cr.get(l, D(0)) - a
    return {l: (op[l], dr.get(l, D(0)), cr.get(l, D(0)), op[l] + dr.get(l, D(0)) - cr.get(l, D(0))) for l in op}


def r_tally(o, B):
    S, A, F, mf, base, cur = ctx(B); bl = S['bank']['ledger']; co = f"{S['name']} - FY 2026-27"
    x = ['<ENVELOPE>', ' <HEADER>', '  <TALLYREQUEST>Import Data</TALLYREQUEST>', ' </HEADER>', ' <BODY>', '  <IMPORTDATA>', '   <REQUESTDESC>',
         '    <REPORTNAME>Vouchers</REPORTNAME>', '    <STATICVARIABLES>', f'     <SVCURRENTCOMPANY>{esc(co)}</SVCURRENTCOMPANY>', '    </STATICVARIABLES>',
         '   </REQUESTDESC>', '   <REQUESTDATA>']
    cnt = {}
    for v in B.tv[B.n_hist_tv:]:
        cnt[v['vtype']] = cnt.get(v['vtype'], 0) + 1; v['vno'] = f"{v['vtype'][0]}/{cnt[v['vtype']]:03d}"
        x += ['    <TALLYMESSAGE xmlns:UDF="TallyUDF">', f'     <VOUCHER REMOTEID="{v["guid"]}" VCHTYPE="{v["vtype"]}" ACTION="Create" OBJVIEW="Accounting Voucher View">',
              f'      <DATE>{v["date"]:%Y%m%d}</DATE>', f'      <GUID>{v["guid"]}</GUID>', f'      <NARRATION>{esc(v["narration"])}</NARRATION>',
              f'      <VOUCHERTYPENAME>{v["vtype"]}</VOUCHERTYPENAME>', f'      <VOUCHERNUMBER>{v["vno"]}</VOUCHERNUMBER>',
              f'      <EFFECTIVEDATE>{v["date"]:%Y%m%d}</EFFECTIVEDATE>', f'      <ALTERID>{v["alterid"]}</ALTERID>', '      <ISCANCELLED>No</ISCANCELLED>']
        for l, a in v['lines']:
            x += ['      <ALLLEDGERENTRIES.LIST>', f'       <LEDGERNAME>{esc(l)}</LEDGERNAME>', f'       <ISDEEMEDPOSITIVE>{"Yes" if a > 0 else "No"}</ISDEEMEDPOSITIVE>',
                  f'       <AMOUNT>{-a:.2f}</AMOUNT>', '      </ALLLEDGERENTRIES.LIST>']
        x += ['     </VOUCHER>', '    </TALLYMESSAGE>']
    x += ['   </REQUESTDATA>', '  </IMPORTDATA>', ' </BODY>', '</ENVELOPE>']
    o.text(f"{F}/Tally_{S['short']}_DayBook_Q2FY27.xml", '\n'.join(x) + '\n', ['tally_voucher'], 'Client finance team (Tally export)', 'Tally bridge')
    t = tally_tb(B); assert sum(v[0] for v in t.values()) == 0 and sum(v[3] for v in t.values()) == 0
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'Trial Balance'
    for r, tx in enumerate([co, 'Trial Balance', '1-Jul-2026 to 30-Sep-2026' + (' (books in INR; USD items at memo rate 89.40)' if A else ' (INR)')], 1): ws.cell(r, 1, tx).font = BOLD
    ws.cell(5, 1, 'Particulars').font = BOLD
    for c, tx in ((2, 'Opening Balance'), (4, 'Transactions'), (6, 'Closing Balance')):
        ws.cell(5, c, tx).font = BOLD; ws.merge_cells(start_row=5, start_column=c, end_row=5, end_column=c + 1)
    for c in range(2, 8): ws.cell(6, c, 'Debit' if c % 2 == 0 else 'Credit').font = BOLD
    r = 7; tot = [D(0)] * 6
    sp = lambda v: (v if v > 0 else None, -v if v < 0 else None)
    for g in GORDER:
        ls = sorted(l for l in t if grp(l, bl) == g)
        if not ls: continue
        gr = r; r += 1; gs = [D(0)] * 6
        for l in ls:
            op, d_, c_, cl = t[l]; vals = [*sp(op), d_ or None, c_ or None, *sp(cl)]
            ws.cell(r, 1, '    ' + l)
            for c, v in enumerate(vals, 2):
                if v is not None:
                    ws.cell(r, c, float(v)).number_format = '#,##0.00'; gs[c - 2] += v
            r += 1
        if g != 'Primary':
            ws.cell(gr, 1, g).font = BOLD
            for c, v in enumerate(gs, 2):
                if v: x_ = ws.cell(gr, c, float(v)); x_.number_format = '#,##0.00'; x_.font = BOLD
        else: ws.cell(gr, 1, '(Primary)').font = BOLD
        tot = [a + b for a, b in zip(tot, gs)]
    ws.cell(r, 1, 'Grand Total').font = BOLD
    for c, v in enumerate(tot, 2): x_ = ws.cell(r, c, float(v)); x_.number_format = '#,##0.00'; x_.font = BOLD
    ws.column_dimensions['A'].width = 52
    for c in 'BCDEFG': ws.column_dimensions[c].width = 20
    o.xlsx(f"{F}/Tally_{S['short']}_TrialBalance_30Sep26.xlsx", wb, ['tally_ledger_balance'], 'Client finance team (Tally export)', 'Tally bridge')
    wb = openpyxl.Workbook()
    sheet(wb, 'Ledgers', [co, 'List of Ledgers with opening balances as at 30-Jun-2026 (start of period 1-Jul-2026)'],
          ['Name of Ledger', 'Under', 'Opening Balance', 'Dr/Cr'],
          [[l, grp(l, bl), abs(t[l][0]), 'Dr' if t[l][0] > 0 else ('Cr' if t[l][0] < 0 else '')] for l in sorted(t, key=lambda l: (GORDER.index(grp(l, bl)), l))],
          {1: 52, 2: 24, 3: 20}, first=True)
    o.xlsx(f"{F}/Tally_{S['short']}_LedgerMasters.xlsx", wb, ['tally_ledger_balance', 'gl_account'], 'Client finance team (Tally export)', 'Tally bridge')
    B.tally_tb = t


def call_alloc(B):
    S = B.S; c = S['call']; tot = S['committed'] * c['pct']
    fee = S['fee_q'] + S['fee_gst']; invt = q(tot * c['inv_part']); exp = tot - invt - fee
    pi, pf, pe = (prorate_(x, B.w) for x in (invt, fee, exp))
    hist = sum(p for _, _, p in S['hist_calls'])
    out = []
    for i in S['investors']:
        k = i['id']; amt = i['commit'] * c['pct']; e = amt - pi[k] - pf[k]
        out.append(dict(i=i, amt=amt, inv=pi[k], fee=pf[k], exp=e, cum=i['commit'] * (hist + c['pct']), unf=i['commit'] * (1 - hist - c['pct']),
                        rc=c['receipts'][k], late=(c['receipts'][k] - c['due']).days))
    return out


def prorate_(t, w):
    from .core import prorate
    return prorate(t, w, 4)


def r_call(o, B):
    S, A, F, mf, base, cur = ctx(B); c = S['call']; bk = S['bank']; al = call_alloc(B); B.call_alloc = al
    for a in al:
        i = a['i']
        blocks = [kv([('Notice No', f"{S['short']}/{c['code']}/{i['id']}"), ('Notice date', dmy(c['notice'])), ('Due date', dmy(c['due'])), ('Investor', i['name']),
                      ('Investor ID', i['id']), ('Unit class', f"Class {i['cls']}"), (f'Capital commitment ({cur})', mf(base(i['commit']))),
                      ('Percentage of commitment called', f"{c['pct'] * 100:.2f}%"), (f'Amount now called ({cur})', mf(base(a['amt']))),
                      (f'of which investment ({cur})', mf(base(a['inv']))), (f'of which management fees ({cur})', mf(base(a['fee']))),
                      (f'of which expenses and reserves ({cur})', mf(base(a['exp']))), (f'Cumulative called after this call ({cur})', mf(base(a['cum']))),
                      (f'Unfunded commitment after this call ({cur})', mf(base(a['unf']))), ('Purpose', c['purpose'])]),
                  p(f"Pursuant to clause 6 of the Contribution Agreement, the {'FME' if A else 'Investment Manager'} hereby calls the amount stated above. "
                    f"Units of {cur} {S['par']} each will be issued at par on receipt of cleared funds."),
                  h('Remittance instructions'),
                  kv([('Beneficiary', f"{S['providers']['trustee']} A/c {S['name']}"), ('Bank', f"{bk['name']}, {bk['branch']}"), ('Account number', bk['acct']),
                      ('SWIFT' if A else 'IFSC (RTGS/NEFT)', bk['swift'] or bk['ifsc']), ('Payment reference', f"CALL {c['code']} {i['id']}")]),
                  p(f"Late payment: amounts not received by the due date bear interest at {S['late_rate'] * 100:.0f}% per annum (ACT/365) from the due date to the date of receipt, "
                    "without prejudice to the default provisions of the Contribution Agreement."),
                  sign(MANAGER['po'], 'Principal Officer', MANAGER['name'])]
        o.pdf(f"{F}/CapitalCall_{c['code']}_Notice_{i['slug']}.pdf", doc('scheme', *lh(S), f"DRAWDOWN NOTICE {c['label']}", blocks,
              'Confidential - for the addressee only'), ['capital_call', 'call_allocation'], 'FME / fund administrator', 'Capital calls')
    wb = openpyxl.Workbook()
    kvsheet(wb, 'Call', [f"{S['name']} - Capital call {c['label']}"],
            [('Call no', c['label']), ('Notice date', c['notice']), ('Due date', c['due']), ('Percentage of commitment', float(c['pct'])), ('Purpose', c['purpose']),
             ('Currency', cur), ('Total commitments', base(S['committed'])), ('Total called', base(S['committed'] * c['pct'])), ('Prepared by (maker)', MAKER), ('Approved by (checker)', CHECKER)], first=True)
    rows = [[a['i']['id'], a['i']['name'], a['i']['cls'], base(a['i']['commit']), base(a['amt']), base(a['inv']), base(a['fee']), base(a['exp']), base(a['cum']), base(a['unf'])] for a in al]
    sheet(wb, 'Allocation', [f"{c['label']} allocation by investor ({cur})"],
          ['Investor ID', 'Investor', 'Class', 'Commitment', 'Amount called', 'Investment component', 'Fee component', 'Expense component', 'Cumulative called', 'Unfunded after call'],
          rows, {2: 44}, total=['Control total', '', ''] + [sum(r[k] for r in rows) for k in range(3, 10)])
    o.xlsx(f"{F}/CapitalCall_{c['code']}_Allocation.xlsx", wb, ['capital_call', 'call_allocation'], 'FME finance (maker) / checker', 'Capital calls')


def r_dist(o, B):
    S, A, F, mf, base, cur = ctx(B); d = S['dist']; tn = S['tax_name']
    ded = f"{S['providers']['trustee']} A/c {S['name']}"
    for L in B.dist_lines:
        i = B.inv[L['investor']]
        blocks = [kv([('Notice No', f"{S['short']}/{d['code']}/{i['id']}"), ('Declaration date', dmy(d['decl'])), ('Payment date', dmy(d['pay'])), ('Investor', i['name']),
                      ('Investor ID', i['id']), ('Unit class', f"Class {i['cls']}"), ('Character of distribution', 'Income (interest/coupon)'),
                      (f'Gross distribution ({cur})', mf(base(L['gross']))), (f'of which income ({cur})', mf(base(L['income']))),
                      (f'of which return of capital ({cur})', mf(0)), (f'of which capital gain ({cur})', mf(0)),
                      (f'{tn} rate', f"{L['wht_rate'] * 100:.2f}%"), (f'{tn} withheld ({cur})', mf(base(L['wht']))), (f'Net amount payable ({cur})', mf(base(L['net']))),
                      ('Recallable amount', 'Nil'), ('Effect on units', 'None - income distributions do not change units'), ('Source', d['source'])]),
                  p(f"Tax has been withheld {'in accordance with clause 14 of the PPM at the rate recorded for the investor' if A else 'under section 194LBB of the Income-tax Act, 1961'} "
                    f"and will be deposited on or before {dmy(d['deposit'])}. A certificate will follow."),
                  sign(MANAGER['po'], 'Principal Officer', MANAGER['name'])]
        o.pdf(f"{F}/Distribution_{d['code']}_Notice_{i['slug']}.pdf", doc('scheme', *lh(S), f"DISTRIBUTION NOTICE {d['label']}", blocks, 'Confidential - for the addressee only'),
              ['distribution', 'distribution_line'], 'FME / fund administrator', 'Distributions')
    wb = openpyxl.Workbook()
    kvsheet(wb, 'Distribution', [f"{S['name']} - Distribution {d['label']}"],
            [('Distribution no', d['label']), ('Declaration date', d['decl']), ('Payment date', d['pay']), ('Currency', cur), ('Total gross', base(d['gross'])),
             ('Character - income', base(d['gross'])), ('Character - return of capital', D('0.00')), ('Character - capital gain', D('0.00')), ('Recallable amount', D('0.00')),
             ('Source', d['source']), (f'{tn} deposit due date', d['deposit']), ('Prepared by (maker)', MAKER), ('Approved by (checker)', CHECKER)], first=True)
    rows = [[L['investor'], B.inv[L['investor']]['name'], B.inv[L['investor']]['cls'], B.ca[L['investor']]['units'], base(L['gross']), base(L['income']), D('0.00'), D('0.00'),
             float(L['wht_rate']), base(L['wht']), base(L['net']), f"DIST {d['code']} {L['investor']}"] for L in B.dist_lines]
    sheet(wb, 'Schedule', [f"{d['label']} schedule by investor ({cur})"],
          ['Investor ID', 'Investor', 'Class', 'Units held', 'Gross', 'Income', 'Return of capital', 'Capital gain', f'{tn} rate', f'{tn} amount', 'Net paid', 'Payment reference'],
          rows, {2: 44, 12: 24}, total=['Control total', '', '', sum(r[3] for r in rows)] + [sum(r[k] for r in rows) for k in range(4, 8)] + [''] + [sum(r[k] for r in rows) for k in (9, 10)] + [''])
    o.xlsx(f"{F}/Distribution_{d['code']}_Schedule.xlsx", wb, ['distribution', 'distribution_line', 'wht_entry'], 'FME finance (maker) / checker', 'Distributions')
    if A:
        s = io.StringIO(); w = csv.writer(s, lineterminator='\n')
        w.writerow(['H', 'BULKPAY', S['bank']['acct'], f"{d['pay']:%Y%m%d}", f"{d['code']}/2026/001"])
        w.writerow(['Record Type', 'Debit Account', 'Value Date', 'Currency', 'Amount', 'Beneficiary Name', 'Beneficiary Bank', 'Beneficiary SWIFT', 'Purpose Code', 'Payment Details'])
        for L in B.dist_lines:
            i = B.inv[L['investor']]
            w.writerow(['D', S['bank']['acct'], f"{d['pay']:%d/%m/%Y}", 'USD', f"{base(L['net']):.2f}", i['name'], i['bank'], i['swift'], 'P9999', f"DIST {d['code']} {i['id']} NET OF WHT"])
        w.writerow(['T', len(B.dist_lines), f"{base(sum(L['net'] for L in B.dist_lines)):.2f}"])
        o.text(f"{F}/Distribution_{d['code']}_PaymentFile.csv", s.getvalue(), ['distribution_line'], 'FME finance - IBU bulk-payment upload', 'Distributions')
    tot = base(sum(L['wht'] for L in B.dist_lines))
    o.pdf(f"{F}/{'WHT_Deposit_Challan_DA1' if A else 'TDS_194LBB_Challan_DB1'}.pdf",
          doc('govt', 'TAX DEPOSIT CHALLAN' if A else 'CHALLAN NO./ITNS 281 - TAX DEDUCTED AT SOURCE', 'Counterfoil - taxpayer copy (synthetic specimen)',
              'Challan receipt', [kv([('Challan No', d['challan']), ('Deposit date', dmy(d['deposit'])), ('Deductor', ded), ('TAN', 'AHMR99999Z' if A else 'MUMR99999Z'),
                                      ('Section', S['tax_section']), ('Nature of payment', f"Tax withheld on income distribution {d['label']}"),
                                      (f'Amount deposited ({cur})', mf(tot)), ('Distribution reference', d['label']), ('Bank / BSR code', '9999999'), ('Status', 'Paid - realised')])]),
          ['wht_entry', 'evidence'], 'Authorised bank / tax portal', 'Distributions')
    for L in B.dist_lines[:3]:
        i = B.inv[L['investor']]
        o.pdf(f"{F}/{'WHT_Certificate' if A else 'Form16A'}_{i['slug']}.pdf",
              doc('scheme', *lh(S), 'CERTIFICATE OF TAX WITHHELD' if A else 'FORM NO. 16A - Certificate under section 203 for tax deducted at source',
                  [kv([('Certificate No', f"{'WHT' if A else '16A'}/{S['short']}/{d['code']}/{i['id']}"), ('Certificate date', dmy(d['cert_date'])), ('Deductor', ded),
                       ('Deductee', i['name']), ('Investor ID', i['id']), ('Tax identification / PAN', i['tin']), ('Section', S['tax_section']),
                       ('Distribution reference', d['label']), ('Date of payment/credit', dmy(d['pay'])), (f'Gross amount ({cur})', mf(base(L['gross']))),
                       (f'{tn} rate', f"{L['wht_rate'] * 100:.2f}%"), (f'{tn} amount ({cur})', mf(base(L['wht']))), ('Challan No', d['challan']), ('Deposit date', dmy(d['deposit']))]),
                   sign(MANAGER['co'], 'Compliance Officer', MANAGER['name'])]), ['wht_entry'], 'FME / deductor', 'Distributions')
    if not A:
        for L in B.dist_lines:
            i = B.inv[L['investor']]
            o.pdf(f"{F}/Form64C_Statement_{i['slug']}.pdf",
                  doc('scheme', *lh(S), 'DRAFT - FORM NO. 64C - Statement of income distributed by an investment fund (FY 2026-27, part-year)',
                      [kv([('Status', 'DRAFT - not issued; final statement due after 31-Mar-2027'), ('Unit holder', i['name']), ('Investor ID', i['id']), ('PAN', i['tin']),
                           ('Period covered', '01-Apr-2026 to 30-Sep-2026'), ('Income paid or credited - interest (INR)', ind(base(L['gross']))),
                           ('Income paid or credited - other heads (INR)', ind(0)), ('Tax deducted u/s 194LBB (INR)', ind(base(L['wht']))), ('Distribution reference', d['label'])]),
                       note('Draft prepared for demonstration of investor income characterisation. Head-wise break-up to be confirmed by tax advisers.')]),
                  ['distribution_line', 'report_run'], 'FME tax team (draft)', 'Report centre')
