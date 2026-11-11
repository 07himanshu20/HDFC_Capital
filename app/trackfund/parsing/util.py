"""Low-level readers shared by every parser (ported from validation/run.py so results stay identical)."""
import re
import hashlib
import calendar
from decimal import Decimal as D, ROUND_HALF_UP
from datetime import datetime, date, timedelta

import openpyxl
import pdfplumber


def q(x, p=4):
    return D(x).quantize(D(1).scaleb(-p), ROUND_HALF_UP)


def num(s):
    if s is None or s == '':
        return D(0)
    if isinstance(s, (int, float)):
        return D(str(round(s, 6)))
    return D(str(s).replace(',', '').replace('%', '').strip() or '0')


def dt(s):
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    s = str(s).strip()
    for f in ('%d-%b-%Y', '%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    raise ValueError(s)


def dt_or_none(s):
    if s in (None, '', 'n/a'):
        return None
    try:
        return dt(s)
    except ValueError:
        return None


def nows(s):
    return re.sub(r'\s+', '', s or '')


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(p):
    with open(p, 'rb') as f:
        return sha_bytes(f.read())


def dmy(d):
    return f"{d.day:02d}-{d:%b-%Y}"


def quarter_end(d):
    """last day of the calendar quarter that contains d"""
    m = ((d.month - 1) // 3 + 1) * 3
    return date(d.year, m, calendar.monthrange(d.year, m)[1])


def fy_quarter(d):
    """Indian fiscal quarter label for a quarter-end date: 30-Sep-2026 -> ('Q2', 27)"""
    fy = d.year + 1 if d.month >= 4 else d.year
    qn = ((d.month - 4) % 12) // 3 + 1
    return f"Q{qn}", fy % 100


def qcode(d):
    qn, fy = fy_quarter(d)
    return f"{qn}FY{fy:02d}"


def prev_quarter_end(d):
    first = date(d.year, d.month, 1)
    m_start = first.month - 2
    y = first.year
    if m_start <= 0:
        m_start += 12
        y -= 1
    return date(y, m_start, 1) - timedelta(days=1)


# ---------------- PDF ----------------
_pdf_cache = {}


def _pdf(p):
    if p not in _pdf_cache:
        with pdfplumber.open(p) as f:
            _pdf_cache[p] = ('\n'.join(pg.extract_text() or '' for pg in f.pages), [t for pg in f.pages for t in pg.extract_tables()])
    return _pdf_cache[p]


def clear_cache():
    _pdf_cache.clear()
    _xl_cache.clear()


def pdf_text(p):
    return _pdf(p)[0]


def pdf_kv(p):
    out = {}
    for ln in pdf_text(p).split('\n'):
        if ': ' in ln:
            k, v = ln.split(': ', 1)
            out.setdefault(k.strip(), v.strip())
    return out


def pdf_tables(p):
    return _pdf(p)[1]


# ---------------- XLSX ----------------
_xl_cache = {}


def _wb(p):
    if p not in _xl_cache:
        _xl_cache[p] = openpyxl.load_workbook(p, data_only=True)
    return _xl_cache[p]


def xl_sheets(p):
    return _wb(p).sheetnames


def xl_rows(p, sheet):
    return list(_wb(p)[sheet].iter_rows(values_only=True))


def xl_kv(p, sheet):
    return {str(r[0]).strip(): r[1] for r in _wb(p)[sheet].iter_rows(values_only=True) if r[0] is not None and len(r) > 1 and r[1] is not None}


def xl_table(p, sheet, must):
    """locate the header row by content (not position) and return rows as dicts with their sheet row number"""
    rows = xl_rows(p, sheet)
    for hi, r in enumerate(rows):
        cells = [str(c).strip() if c is not None else '' for c in r]
        if sum(1 for c in cells if c) >= 2 and all(any(m.lower() in c.lower() for c in cells) for m in must):
            out = []
            for k, rr in enumerate(rows[hi + 1:], hi + 2):
                if rr[0] is None:
                    break
                d = dict(zip(cells, rr))
                d['_row'] = k
                out.append(d)
            return out
    raise KeyError(f'{p}:{sheet}: header {must} not found')


def col(row, *keys):
    for k in row:
        if all(x.lower() in k.lower() for x in keys):
            return row[k]
    raise KeyError(keys)


def col_or(row, default, *keys):
    try:
        return col(row, *keys)
    except KeyError:
        return default
