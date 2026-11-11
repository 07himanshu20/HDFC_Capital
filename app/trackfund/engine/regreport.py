"""Regulator quarterly report: IFSCA quarterly report (GIFT IFSC scheme) or SEBI quarterly activity report (onshore scheme).

The layout is taken from the previous quarter's report as filed: same sheet names (Report, Investments, Investors), part
headings, row labels and column headings. So the workbook generated for this quarter can be uploaded next quarter as the
prior report and is read by the same parser (rule R15).

`model()` runs at ingestion and is stored with the dashboard data (`reg_report`), so the on-screen preview and the file
show the same figures. `write_workbook()` and `verify_workbook()` run when a user generates the file from a locked NAV.
"""
import re
from collections import Counter
from decimal import Decimal as D

import openpyxl
from openpyxl.styles import Font, Alignment

from .coa import TYPE
from ..parsing.util import num, col, col_or

SHEET_WIDTHS = {'Report': [34, 60], 'Investments': [18, 40, 18, 18, 18, 18, 18], 'Investors': [18, 44, 18, 18, 18, 18]}


def _fmt(v):
    """number format with as many decimals as the value needs (2 to 4), as in the filed workbooks"""
    if not isinstance(v, D):
        return 'General'
    for p in (2, 3):
        if v == v.quantize(D(1).scaleb(-p)):
            return '#,##0.' + '0' * p
    return '#,##0.0000'


def title_base(prior_title, regulator):
    b = re.split(r'\s+-\s+Q\d\s*FY\s*\d\d', str(prior_title or ''))[0].strip()
    return b or f"{regulator} quarterly report"


def file_name(prior_file, qcode):
    stem = re.sub(r'_Q\dFY\d\d(_as_filed)?\.xlsx$', '', prior_file.split('/')[-1], flags=re.I)
    return f"{stem}_{qcode}.xlsx"


def model(X, Bk, meta, investors, instruments):
    P = X['period']
    pr = X['prior_report']
    unit = X['opening']['unit']
    tb = Bk['close_tb']
    g = lambda k: tb.get(k, D(0))

    committed = num(meta['committed'])
    drawn = -g(3100)
    assets = sum(v for k, v in tb.items() if TYPE.get(k) == 'a')
    liabilities = -sum(v for k, v in tb.items() if TYPE.get(k) == 'l')
    nav = Bk['nav_close']
    receivables = g(1300) + g(1400)

    part_a = [['Name of scheme', meta['name']], ['Registration no', meta['reg_no']], ['Category', meta['category']],
              ['Manager', X['ppm'].get('manager') or pr['kv'].get('Manager', '')],
              ['Reporting period', f"{P['label']} ({P['q_start']:%d-%b-%Y} to {P['q_end']:%d-%b-%Y})"], ['Reporting currency', unit]]
    part_b = [['Target corpus', num(meta['target'])], ['Total commitments', committed], ['Cumulative drawn', drawn], ['Undrawn commitments', committed - drawn],
              ['Cumulative distributions', g(3200)], ['Number of investors', len(investors)]]
    part_c = [['Cash and bank', g(1100)], ['Investments at cost', g(1200)], ['Fair-value adjustment', g(1210)]]
    if 1220 in tb:                       # schemes whose functional currency is not INR carry FX translation on INR assets
        part_c.append(['FX translation', g(1220)])
    if receivables:
        part_c.append(['Accrued income and receivables', receivables])
    part_c += [['Liabilities', liabilities], ['Net asset value', nav], ['Borrowings / leverage', D(0)]]   # the chart of accounts has no borrowing account

    # portfolio: one row per instrument held at quarter end
    prior_ins = {str(r.get('Instrument')): r for r in pr.get('investments', [])}
    sectors = Counter(str(col_or(r, '', 'Sector')) for r in prior_ins.values())
    common_sector = next(iter(sectors)) if len(sectors) == 1 else ''
    ins_rows = []
    for x in instruments:
        p = prior_ins.get(x['id'], {})
        ins_rows.append([x['id'], x['spv_name'], x['kind_long'], x['city'], str(col_or(p, common_sector, 'Sector')), num(x['principal']), num(x['cost'])])

    # investors: drawn = drawn as filed last quarter + called this quarter
    prior_inv = {str(r['Investor ID']): r for r in pr['investors']}
    inv_rows = []
    for i in investors:
        p = prior_inv.get(i['id'])
        before = num(col_or(p, 0, 'Drawn')) if p else D(0)
        inv_rows.append([i['id'], i['type'], i['country'], i['cls'], num(i['commit']), before + num(Bk['capital'][i['id']]['contributions'])])

    f4 = lambda v: f"{v:,.4f}"
    inv_c, inv_d, ins_c = sum((r[4] for r in inv_rows), D(0)), sum((r[5] for r in inv_rows), D(0)), sum((r[6] for r in ins_rows), D(0))
    ties = [
        ['Part C adds up to the NAV', assets - liabilities == nav, f"assets {f4(assets)} less liabilities {f4(liabilities)} = {f4(assets - liabilities)}; NAV {f4(nav)}"],
        ['Investor commitments add up to total commitments', inv_c == committed, f"{f4(inv_c)} vs {f4(committed)} (PPM)"],
        ['Investor drawn adds up to cumulative drawn', inv_d == drawn, f"{f4(inv_d)} vs {f4(drawn)} (GL 3100)"],
        ['Instrument cost adds up to investments at cost', ins_c == g(1200), f"{f4(ins_c)} vs {f4(g(1200))} (GL 1200)"],
    ]
    as_at = f"{P['q_end']:%d-%b-%Y}"
    return dict(
        title=title_base(pr.get('title'), meta['regulator']), regulator=meta['regulator'], file_name=file_name(X['prior_report_file'], P['qcode']),
        note=pr.get('note', ''), period=P['label'], period_code=P['qcode'], unit=unit, prior_file=X['prior_report_file'],
        parts=[dict(h='PART A - SCHEME PARTICULARS', rows=part_a), dict(h='PART B - CAPITAL', rows=part_b), dict(h='PART C - ASSETS AND LIABILITIES', rows=part_c)],
        investments=dict(title=f"Portfolio at {as_at}", head=['Instrument', 'Investee', 'Type', 'City', 'Sector', 'Principal (INR cr)', f"Cost ({unit})"], rows=ins_rows),
        investors=dict(title=f"Investor profile at {as_at}", head=['Investor ID', 'Type', 'Country', 'Class', f"Commitment ({unit})", f"Drawn ({unit})"], rows=inv_rows),
        ties=ties, ok=all(t[1] for t in ties),
    )


# ------------------------------------------------------------------ file
def _d(v):
    """values come back from the stored JSON as floats; amounts are 4-decimal at most"""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, int):
        return v
    return D(str(round(v, 6))).normalize() if v != int(v) else D(int(v))


def _cell_value(v):
    return float(v) if isinstance(v, D) else v


def write_workbook(m, prep, path):
    """m: the stored model (floats); prep: list of [label, value] for Part D (who prepared it, from which NAV version)"""
    bold = Font(bold=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Report'
    ws.append([f"{m['title']} - {m['period']}"])
    ws['A1'].font = bold
    ws.append([m['note']] if m.get('note') else [])
    ws.append([])
    parts = m['parts'] + [dict(h='PART D - PREPARATION AND FILING', rows=prep)]
    for part in parts:
        ws.append([part['h']])
        ws.cell(ws.max_row, 1).font = bold
        for label, v in part['rows']:
            v = _d(v)
            ws.append([label, _cell_value(v)])
            ws.cell(ws.max_row, 2).number_format = _fmt(v)
            ws.cell(ws.max_row, 2).alignment = Alignment(horizontal='left')
    for sheet in ('investments', 'investors'):
        t = m[sheet]
        s = wb.create_sheet(sheet.capitalize())
        s.append([t['title']])
        s['A1'].font = bold
        s.append([m['note']] if m.get('note') else [])
        s.append([])
        s.append(t['head'])
        for c in s[s.max_row]:
            c.font = bold
        for r in t['rows']:
            s.append([_cell_value(_d(v)) for v in r])
            for k, v in enumerate(r, 1):
                s.cell(s.max_row, k).number_format = _fmt(_d(v))
    for s in wb.worksheets:
        for k, w in enumerate(SHEET_WIDTHS[s.title]):
            s.column_dimensions[openpyxl.utils.get_column_letter(k + 1)].width = w
    wb.properties.creator = 'TrackFund'
    wb.properties.title = f"{m['title']} - {m['period']}"
    wb.save(path)


def verify_workbook(path, books, parse):
    """
    Read the generated file back with `parse` (the prior-report parser that next quarter's ingestion uses) and tie it to the
    closing books.  books: dict(nav, drawn, cash, investments, committed) as Decimals.  Returns (ok, checks).
    """
    r = parse(path)
    kv = r['kv']
    v = lambda k: num(kv.get(k))
    inv = r['investors']
    ins = r['investments']
    part_c = v('Cash and bank') + v('Investments at cost') + v('Fair-value adjustment') + v('FX translation') + v('Accrued income and receivables') - v('Liabilities')
    checks = [
        ['Net asset value', v('Net asset value'), books['nav']],
        ['Cumulative drawn', v('Cumulative drawn'), books['drawn']],
        ['Cash and bank', v('Cash and bank'), books['cash']],
        ['Investments at cost', v('Investments at cost'), books['investments']],
        ['Total commitments', v('Total commitments'), books['committed']],
        ['Part C total equals the NAV line', part_c, v('Net asset value')],      # arithmetic inside the file
        ['Investors sheet: commitments', sum((num(col(x, 'Commitment')) for x in inv), D(0)), books['committed']],
        ['Investors sheet: drawn', sum((num(col(x, 'Drawn')) for x in inv), D(0)), books['drawn']],
        ['Investments sheet: cost', sum((num(col(x, 'Cost')) for x in ins), D(0)), books['investments']],
    ]
    out = [[n, f"{a:,.4f}", f"{b:,.4f}", a == b] for n, a, b in checks]     # compared as exact decimals; shown to 4 places
    return all(c[3] for c in out), out
