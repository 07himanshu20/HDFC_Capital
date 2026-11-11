"""Parsers: one function per document type.  Each reads only its own file and returns plain records.

`extract_scheme()` classifies a scheme's uploaded files with the catalog, runs the parsers and returns a
`Bundle` -- everything the books engine and the dashboard need, plus the file register (hash, type,
feeds) and a per-file parse log.  Nothing here posts journals or computes NAV; see engine/books.py.
"""
import os
import re
import csv
import glob
import xml.etree.ElementTree as ET
from decimal import Decimal as D
from datetime import datetime, date

import xlrd
import mt940

from ..catalog import classify, BY_KEY, BANK_TYPES, CATALOG
from .util import (num, dt, dt_or_none, pdf_kv, pdf_tables, pdf_text, xl_kv, xl_table, xl_rows, xl_sheets, col, col_or,
                   sha_file, quarter_end, qcode, prev_quarter_end, clear_cache)


class ParseError(Exception):
    pass


class Bundle(dict):
    """dict of parsed sections + helpers; keys are documented in extract_scheme()"""


def _unit_scale(unit):
    u = unit.lower()
    if u.endswith(' m'):
        return D(1000000)
    if u.endswith(' cr'):
        return D(10000000)
    if u.endswith(' bn'):
        return D(1000000000)
    return D(1)


# ------------------------------------------------------------------ opening balances (shared workbook)
def parse_opening(path, sid):
    meta = xl_kv(path, f'{sid} Meta')
    tb_rows = xl_table(path, f'{sid} TB', ['GL code', 'Balance'])
    return dict(
        meta=meta,
        as_at=dt(meta['As at']),
        unit=str(meta['Unit']),
        status=str(meta.get('Status', '')),
        closing_rate=(num(meta[k]) if (k := next((k for k in meta if k.startswith('Closing rate')), None)) and str(meta[k]) not in ('n/a', '') else None),
        nav=num(meta.get('Net asset value')),
        units=int(meta.get('Units in issue') or 0),
        tb={int(r['GL code']): num(r['Balance']) for r in tb_rows},
        gl={int(r['GL code']): (str(r['Account']), str(r['Type'])) for r in tb_rows},
        instruments={r['Instrument ID']: r for r in xl_table(path, f'{sid} Instruments', ['Instrument ID', 'Principal'])},
        capital={r['Investor ID']: r for r in xl_table(path, f'{sid} Capital', ['Investor ID', 'Units'])},
        calls=[(str(r['Call']), dt(r['Due date']), num(col(r, 'Amount'))) for r in xl_table(path, f'{sid} Calls', ['Call', 'Due date'])],
    )


def opening_schemes(path):
    return sorted({s.split(' ')[0] for s in xl_sheets(path) if s.endswith(' Meta')})


# ------------------------------------------------------------------ masters
def parse_ppm(p):
    kv = pdf_kv(p)
    head = pdf_text(p).split('\n')[1] if pdf_text(p).count('\n') else ''
    reg = re.search(r'(IFSCA|SEBI) Reg\. No\. ([^\s·]+)', head)
    trustee = re.search(r'Trustee: ([^·]+?) ·', head)
    mgr = re.search(r'(?:FME|Investment Manager): ([^·]+?) ·', head)
    tax_key = next((k for k in kv if k.endswith('on distributions (default %)')), None)
    return dict(kv=kv, reg_no=reg.group(2) if reg else '', trustee=trustee.group(1).strip() if trustee else '', manager=mgr.group(1).strip() if mgr else '',
                tax_name=tax_key.split(' ')[0] if tax_key else 'TDS', tax_default=num(kv[tax_key]) / 100 if tax_key else D('0.1'))


def parse_investor_register(p):
    sheets = xl_sheets(p)
    inv = xl_table(p, 'Investors', ['Investor ID', 'Commitment'])
    classes = xl_table(p, 'Classes', ['Class', 'Par value']) if 'Classes' in sheets else []
    closes = xl_table(p, 'Closes', ['Close', 'Date']) if 'Closes' in sheets else []
    sl = xl_table(p, 'Side Letters', ['Investor ID', 'Clause type']) if 'Side Letters' in sheets else None
    return dict(investors=inv, classes=classes, closes=closes, side_letters=sl)


def parse_side_letters(p):
    return xl_table(p, 'Side Letters', ['Investor ID', 'Clause type'])


def parse_kyc_register(p):
    return dict(register=xl_table(p, 'KYC Register', ['Investor ID', 'Status', 'Next refresh']),
                documents=xl_table(p, 'Documents', ['Investor ID', 'Document type']),
                screening=xl_table(p, 'Screening Log', ['Investor ID', 'Run date']),
                fatca=xl_table(p, 'FATCA-CRS', ['Investor ID', 'FATCA status']))


def parse_deal_master(p):
    return dict(instruments=xl_table(p, 'Instruments', ['Instrument ID', 'ISIN']),
                tranches=xl_table(p, 'Tranches', ['Instrument ID', 'Tranche no']),
                covenants=xl_table(p, 'Covenants', ['Instrument ID', 'Test', 'Minimum']),
                cov_basis={r['Instrument ID']: num(col(r, 'debt service')) for r in xl_table(p, 'Covenant basis', ['Instrument ID', 'debt service'])})


def parse_instrument_summary(p):
    return pdf_kv(p)


def parse_unit_register(p, q_end):
    return dict(ledger=xl_table(p, 'Unit Ledger', ['Event date', 'Investor ID', 'Units']),
                holdings=[r for r in xl_table(p, 'Holdings', ['Investor ID', f"Units at {q_end:%d-%b-%Y}"]) if str(r['Investor ID']).startswith('LP-')])


# ------------------------------------------------------------------ bank
def parse_bank_pdf(p, fx_scheme):
    out = []
    for t in pdf_tables(p):
        for r in t[1:]:
            r = [(c or '').replace('\n', ' ') for c in r]
            if 'TOTAL' in r[0] or 'OPENING' in ' '.join(r):
                continue
            n = len(r)
            dr, cr, bal = num(r[n - 3]), num(r[n - 2]), num(r[n - 1])
            out.append(dict(date=dt(r[0].replace(' ', '')), narr=r[2 if fx_scheme else 1], ref=r[3 if fx_scheme else 2], amt=cr - dr, bal=bal))
    lines = pdf_text(p).split('\n')
    kv = pdf_kv(p)
    head = dict(name=lines[0].strip(), header2=lines[1].strip() if len(lines) > 1 else '')
    return dict(lines=out, kv=kv, head=head)


def parse_bank_mt940(p, open_dt):
    raw = open(p).read().replace('\r\n', '\n')
    tr = mt940.parse(raw)
    cl = {datetime.strptime(m[0], '%y%m%d').date(): D(m[1].replace(',', '.')) for m in re.findall(r':62F:C(\d{6})[A-Z]{3}([\d,]+)', raw)}
    m60 = re.search(r':60F:C' + open_dt.strftime('%y%m%d') + r'[A-Z]{3}([\d,]+)', raw)
    op60 = D(m60.group(1).replace(',', '.')) if m60 else None
    bank = []
    bal = op60 or D(0)
    for k, t in enumerate(tr):
        a = t.data['amount'].amount
        bal += a
        bank.append(dict(date=t.data['date'], narr=t.data['transaction_details'].replace('\n', ''), ref=t.data['customer_reference'], amt=a, bal=bal, loc=f":61: #{k + 1}"))
    return dict(lines=bank, closings=cl, opening=op60)


def parse_bank_csv(p):
    rows = list(csv.reader(open(p)))
    hi = next(i for i, r in enumerate(rows) if r and r[0] == 'Txn Date')
    return dict(lines=[dict(date=dt(r[0]), narr=r[2], ref=r[3], amt=num(r[5]) - num(r[4]), bal=num(r[6]), loc=f"row {i + 1}") for i, r in enumerate(rows[hi + 1:], hi + 1) if r])


def parse_bank_xls(p):
    ws = xlrd.open_workbook(p).sheet_by_index(0)
    hi = next(i for i in range(ws.nrows) if ws.cell_value(i, 0) == 'Date')
    lines = []
    for i in range(hi + 2, ws.nrows):
        v = ws.row_values(i)
        lines.append(dict(date=dt(v[0]), narr=v[1], ref=v[2], amt=num(v[4]) - num(v[3]), bal=num(v[5]), loc=f"Statement!row {i + 1}"))
    return dict(lines=lines, opening=num(ws.cell_value(hi + 1, 5)))


def parse_fx(p):
    with open(p) as f:
        return {dt(r['Date']): D(r['Reference Rate']) for r in csv.DictReader(f)}


def parse_demat_txn(p):
    with open(p) as f:
        return list(csv.DictReader(f))


def parse_demat_holding(p):
    kv = pdf_kv(p)
    lines = pdf_text(p).split('\n')
    hold = {r[0]: int(num(r[3])) for t in pdf_tables(p) for r in t[1:]}
    dep = re.search(r'Depository Participant · (.+?) · DP ID', lines[1]) if len(lines) > 1 else None
    return dict(kv=kv, hold=hold, dp_name=lines[0].strip(), depository=dep.group(1).strip() if dep else '')


# ------------------------------------------------------------------ fees, calls, distributions
def parse_kv_pdf(p):
    return pdf_kv(p)


def parse_call_allocation(p):
    return dict(kv=xl_kv(p, 'Call'), rows=[r for r in xl_table(p, 'Allocation', ['Investor ID', 'Amount called']) if str(r['Investor ID']).startswith('LP-')])


def parse_dist_schedule(p):
    return dict(kv=xl_kv(p, 'Distribution'), rows=[r for r in xl_table(p, 'Schedule', ['Investor ID', 'Gross', 'Net paid']) if str(r['Investor ID']).startswith('LP-')])


def parse_payment_file(p):
    return [r for r in csv.reader(open(p)) if r and r[0] in ('D', 'T')]


# ------------------------------------------------------------------ portfolio
def parse_valuation_inputs(p):
    sheets = xl_sheets(p)
    return dict(summary={r['Instrument']: r for r in xl_table(p, 'Summary', ['Instrument', 'Fair value'])}, cover=xl_kv(p, 'Cover'),
                inputs={r['Instrument']: r for r in xl_table(p, 'Inputs', ['Instrument', 'Yield'])} if 'Inputs' in sheets else {})


def parse_valuation_report(p):
    vt = pdf_tables(p)
    vs = next(t for t in vt if 'Fair value (INR cr)' in [c.replace('\n', ' ') for c in t[0]])
    return dict(kv=pdf_kv(p), table={r[0]: (num(r[4]), num(r[6]), num(r[7])) for r in vs[1:]})


MIS_SYN = dict(sold=['units sold', 'nos. booked'], cum=['cumulative units sold', 'cum. nos.'], value=['sales value', 'booking value'],
               coll=['collections', 'receipts'], esc=['rera escrow balance', 'escrow bal.'], cons=['construction %', '% complete'],
               cost=['cost incurred to date', 'spent to date'], ctc=['cost to complete', 'balance cost'])


def parse_mis(p):
    """Two developer layouts: one sheet per topic (layout 1) or a single MIS sheet with abbreviated headers (layout 2).
    Headers are located by synonym, so either layout maps to the same fields."""
    import openpyxl
    wb = openpyxl.load_workbook(p, data_only=True)
    layout = 2 if wb.sheetnames == ['MIS'] or 'MIS' in wb.sheetnames else 1
    found = {}
    months = None
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        for ri, r in enumerate(rows):
            for ci, c in enumerate(r):
                if not isinstance(c, str):
                    continue
                s = c.strip().lower()
                for fld, syn in MIS_SYN.items():
                    if fld in found:
                        continue
                    if any(s.startswith(x) for x in syn) and not (fld == 'sold' and s.startswith('cumulative')):
                        vals = [(rr[0], rr[ci]) for rr in rows[ri + 1:] if len(rr) > ci and rr[ci] is not None and isinstance(rr[ci], (int, float))]
                        if vals:
                            found[fld] = dict(vals=vals, loc=f"{ws.title}!R{ri + 1}C{ci + 1}", header=c.strip())
                            if months is None:
                                months = [str(v[0]) for v in vals]
    cover = {}
    for ws in wb.worksheets:
        for r in ws.iter_rows(values_only=True):
            if r and r[0] and len(r) > 1 and r[1] is not None and isinstance(r[0], str):
                cover.setdefault(r[0].strip(), r[1])
    return dict(layout=layout, fields=found, months=months or [], cover=cover)


def parse_covenant_cert(p):
    kv = pdf_kv(p)
    ct = [t for t in pdf_tables(p) if t[0][0] == 'Test'][0]
    return dict(kv=kv, tests=[(r[0], num(r[1]), num(r[2]), r[3]) for r in ct[1:]])


def parse_cp_checklist(p):
    rows = xl_rows(p, xl_sheets(p)[0])
    out = []
    hdr = None
    for r in rows:
        if r and r[0] == '#':
            hdr = r
            continue
        if hdr and r and r[0] is not None and isinstance(r[0], (int, float)):
            out.append(dict(no=int(r[0]), condition=r[1], met=r[2], detail=str(r[3]) if r[3] is not None else '', evidence=r[4]))
    return dict(rows=out, title=str(rows[0][0]) if rows and rows[0] else '')


# ------------------------------------------------------------------ Tally
def parse_tally_daybook(p):
    root = ET.parse(p).getroot()
    V = []
    for v in root.iter('VOUCHER'):
        ls = [(e.findtext('LEDGERNAME'), -D(e.findtext('AMOUNT')), e.findtext('ISDEEMEDPOSITIVE')) for e in v.findall('ALLLEDGERENTRIES.LIST')]
        V.append(dict(guid=v.findtext('GUID'), no=v.findtext('VOUCHERNUMBER'), date=datetime.strptime(v.findtext('DATE'), '%Y%m%d').date(),
                      vt=v.findtext('VOUCHERTYPENAME'), narr=v.findtext('NARRATION'), lines=ls))
    return V


def parse_tally_tb(p):
    rows = xl_rows(p, 'Trial Balance')
    tled = {}
    groups = {}
    gt = None
    grp = None
    started = False
    for r in rows:
        if r[0] == 'Particulars':
            started = True
            continue
        if started and r[0] and not str(r[0]).startswith('    ') and r[0] != 'Grand Total':
            grp = str(r[0]).strip().strip('()')
        if r[0] and str(r[0]).startswith('    '):
            name = str(r[0]).strip()
            tled[name] = [num(x) for x in r[1:7]]
            groups[name] = grp
        if r[0] == 'Grand Total':
            gt = [num(x) for x in r[1:7]]
    return dict(ledgers=tled, groups=groups, grand_total=gt)


def parse_tally_ledgers(p):
    return xl_table(p, 'Ledgers', ['Name of Ledger', 'Opening Balance'])


# ------------------------------------------------------------------ compliance
def parse_calendar(p):
    return xl_table(p, 'Calendar', ['Ref', 'Obligation', 'Due date'])


def parse_prior_report(p):
    """the previous quarter's regulator report as filed (or as generated by the Report centre: same layout)"""
    rows = xl_rows(p, 'Report')
    title = next((str(r[0]) for r in rows if r and r[0] is not None), '')
    note = next((str(r[0]) for r in rows[1:4] if r and r[0] is not None and len(r) > 1 and r[1] is None and 'LAYOUT' in str(r[0]).upper()), '')
    try:
        investments = xl_table(p, 'Investments', ['Instrument', 'Cost'])
    except KeyError:
        investments = []
    return dict(kv=xl_kv(p, 'Report'), investors=xl_table(p, 'Investors', ['Investor ID', 'Commitment']), title=title, note=note, investments=investments)


# ==================================================================
def extract_scheme(sid, files, opening_path, log=None):
    """
    sid           scheme code ('A', 'B', ...) -- the prefix used in the opening-balances workbook
    files         {relative path inside the scheme folder: absolute path}
    opening_path  absolute path of the shared opening-balances workbook
    Returns a Bundle with the parsed sections and `register` (one row per file).
    """
    clear_cache()
    log = log if log is not None else []
    B = Bundle()
    reg = []
    by_type = {}
    for rel in sorted(files):
        d, m = classify(rel)
        reg.append(dict(rel=rel, path=files[rel], doc=d.key if d else None, match=m.groupdict() if m else {}))
        if d:
            by_type.setdefault(d.key, []).append(reg[-1])
        else:
            log.append(('w', f"Unrecognised file ignored: {rel}"))
    reg.append(dict(rel=os.path.basename(opening_path), path=opening_path, doc='opening_balances', match={}, shared=True))
    by_type.setdefault('opening_balances', []).append(reg[-1])
    missing = [d for d in CATALOG if d.required and d.key not in by_type]
    if missing:
        raise ParseError('Missing required files: ' + '; '.join(f"{d.label} ({d.pattern})" for d in missing))
    if not any(t in by_type for t in BANK_TYPES):
        raise ParseError('No bank statement found')

    one = lambda k: by_type[k][0]['path']
    many = lambda k: [(r['rel'], r['path'], r['match']) for r in by_type.get(k, [])]

    # period and scheme basics
    op = parse_opening(opening_path, sid)
    open_dt = op['as_at']
    q_end = quarter_end(date.fromordinal(open_dt.toordinal() + 1))
    q_start = date.fromordinal(open_dt.toordinal() + 1)
    B['period'] = dict(open_dt=open_dt, q_start=q_start, q_end=q_end, qcode=qcode(q_end), prev_qcode=qcode(open_dt),
                       label=f"{qcode(q_end)[:2]} {qcode(q_end)[2:]}", prev_label=f"{qcode(open_dt)[:2]} {qcode(open_dt)[2:]}")
    B['opening'] = op
    ppm = parse_ppm(one('ppm_term_sheet'))
    B['ppm'] = ppm
    ccy = ppm['kv'].get('Functional currency', 'INR')
    fx_scheme = ccy != 'INR'
    B['scheme'] = dict(id=sid, ccy=ccy, fx=fx_scheme, unit=op['unit'], scale=_unit_scale(op['unit']))
    log.append(('k', f"Period {B['period']['label']}: {q_start:%d-%b-%Y} to {q_end:%d-%b-%Y}; functional currency {ccy}; unit {op['unit']}"))

    B['investor_register'] = parse_investor_register(one('investor_register'))
    B['side_letters'] = parse_side_letters(one('side_letters')) if 'side_letters' in by_type else (B['investor_register']['side_letters'] or [])
    B['kyc'] = parse_kyc_register(one('kyc_register'))
    B['deal'] = parse_deal_master(one('deal_master'))
    B['instrument_summaries'] = {kv.get('Instrument ID'): kv for kv in (parse_instrument_summary(p) for _, p, _ in many('instrument_summary'))}
    B['units'] = parse_unit_register(one('unit_register'), q_end)
    B['fx'] = parse_fx(one('fx_rates')) if 'fx_rates' in by_type else {}
    if fx_scheme and not B['fx']:
        raise ParseError('Daily FX rates file is required for a non-INR scheme')

    # bank: every format provided is parsed; the first available of MT940 / XLS / CSV / PDF is primary
    bank = dict(formats={})
    pdfb = parse_bank_pdf(one('bank_pdf'), fx_scheme)
    bank['pdf'] = pdfb
    if 'bank_mt940' in by_type:
        bank['formats']['MT940'] = parse_bank_mt940(one('bank_mt940'), open_dt)
    if 'bank_xls' in by_type:
        bank['formats']['XLS'] = parse_bank_xls(one('bank_xls'))
    if 'bank_csv' in by_type:
        bank['formats']['CSV'] = parse_bank_csv(one('bank_csv'))
    bank['formats']['PDF'] = dict(lines=pdfb['lines'])
    bank['primary'] = next(k for k in ('MT940', 'XLS', 'CSV', 'PDF') if k in bank['formats'])
    # MT940 :86: wraps narrations at a fixed width and the wrap swallows spaces; show the CSV/PDF wording when it is the same text
    if bank['primary'] == 'MT940':
        alt = bank['formats'].get('CSV') or bank['formats']['PDF']
        for a, b in zip(bank['formats']['MT940']['lines'], alt['lines']):
            if re.sub(r'\s+', '', a['narr']) == re.sub(r'\s+', '', b['narr']):
                a['narr_full'] = b['narr']
    bank['file_stem'] = os.path.splitext(by_type['bank_pdf'][0]['rel'])[0]
    B['bank'] = bank
    log.append(('g', f"Bank statement: {len(bank['formats'][bank['primary']]['lines'])} transactions ({' / '.join(bank['formats'])}; primary {bank['primary']})"))

    B['demat_txn'] = parse_demat_txn(one('demat_txn'))
    B['demat_holding'] = parse_demat_holding(one('demat_holding'))

    fee = {}
    for rel, p, m in many('fee_invoice'):
        k = pdf_kv(p)
        k['_file'] = rel
        fee[m['q']] = k
    B['fee_invoices'] = fee
    B['fee_prefix'] = by_type['fee_invoice'][0]['rel'].split('_')[0]
    vend = []
    for rel, p, m in many('vendor_invoice'):
        k = pdf_kv(p)
        k['_file'] = rel
        vend.append(k)
    B['vendor_invoices'] = vend

    calls = {}
    for rel, p, m in many('call_allocation'):
        calls[m['code']] = dict(alloc=parse_call_allocation(p), notices=[], file=rel)
    for rel, p, m in many('call_notice'):
        calls.setdefault(m['code'], dict(alloc=None, notices=[], file=None))['notices'].append(pdf_kv(p))
    if len(calls) != 1:
        raise ParseError(f"Expected one capital call in the quarter, found {len(calls)}: {sorted(calls)}")
    code, c = next(iter(calls.items()))
    B['call'] = dict(code=code, **c)
    dists = {}
    for rel, p, m in many('dist_schedule'):
        dists[m['code']] = dict(schedule=parse_dist_schedule(p), notices=[], payment_file=None, file=rel)
    for rel, p, m in many('dist_notice'):
        dists.setdefault(m['code'], dict(schedule=None, notices=[], payment_file=None, file=None))['notices'].append(pdf_kv(p))
    for rel, p, m in many('dist_payment_file'):
        dists.setdefault(m['code'], dict(schedule=None, notices=[], payment_file=None, file=None))['payment_file'] = parse_payment_file(p)
    if len(dists) != 1:
        raise ParseError(f"Expected one distribution in the quarter, found {len(dists)}: {sorted(dists)}")
    code, d = next(iter(dists.items()))
    B['dist'] = dict(code=code, **d)
    B['challan'] = pdf_kv(one('tax_challan'))
    B['challan_file'] = by_type['tax_challan'][0]['rel']
    B['tax_certs'] = [pdf_kv(p) for _, p, _ in many('tax_certificate')]
    B['tax_cert_glob'] = by_type['tax_certificate'][0]['rel'].split('_')[0] + '_*.pdf' if 'tax_certificate' in by_type else ''

    B['valuation_inputs'] = parse_valuation_inputs(one('valuation_inputs'))
    B['valuation_report'] = parse_valuation_report(one('valuation_report'))
    mis = {}
    for rel, p, m in many('developer_mis'):
        mis.setdefault(m['spv'], {})[m['mon']] = dict(parse_mis(p), file=rel)
    B['mis'] = mis
    B['covenant_certs'] = {m['spv']: dict(parse_covenant_cert(p), file=rel) for rel, p, m in many('covenant_cert')}
    B['cp_checklists'] = [dict(parse_cp_checklist(p), file=rel) for rel, p, _ in many('cp_checklist')]
    B['fcgpr'] = [pdf_kv(p) for _, p, _ in many('fcgpr')]

    B['tally'] = dict(vouchers=parse_tally_daybook(one('tally_daybook')), tb=parse_tally_tb(one('tally_tb')), ledgers=parse_tally_ledgers(one('tally_ledgers')),
                      files=dict(daybook=by_type['tally_daybook'][0]['rel'], tb=by_type['tally_tb'][0]['rel'], ledgers=by_type['tally_ledgers'][0]['rel']))
    B['calendar'] = parse_calendar(one('calendar'))
    B['calendar_file'] = by_type['calendar'][0]['rel']
    B['prior_report'] = parse_prior_report(one('prior_report'))
    B['prior_report_file'] = by_type['prior_report'][0]['rel']
    B['_files'] = {k: [r['rel'] for r in v] for k, v in by_type.items()}

    # file register for the dashboard and the database
    devs = {r['Project SPV']: r['Developer'] for r in B['deal']['instruments']}
    bank_who = 'Bank (IBU)' if by_type['bank_pdf'][0]['rel'].startswith('IBU_') else 'Bank'
    for r in reg:
        r['sha256'] = sha_file(r['path'])
        r['format'] = os.path.splitext(r['rel'])[1].lstrip('.').lower()
        if not r['doc']:
            continue
        d = BY_KEY[r['doc']]
        feeds = list(d.feeds)
        if r['doc'] == 'investor_register' and B['investor_register']['side_letters'] is not None:
            feeds.append('side_letter_term')
        who = d.who
        if '{developer}' in who:
            who = who.format(developer=devs.get(r['match'].get('spv'), ''))
        elif '{bank}' in who:
            who = who.format(bank=bank_who)
        elif who == '{vendor_who}':
            who = 'Fund accounting' if 'AccrualNote' in r['rel'] else 'Service provider'
        r.update(feeds=feeds, who=who, page=d.page, label=d.label, parsed=d.parsed)
    B['register'] = reg
    log.append(('g', f"{len(reg)} files classified into {len(by_type)} document types"))
    return B
