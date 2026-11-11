"""Output infrastructure: deterministic xlsx, Chromium PDFs, registry for manifest/README."""
import io, os, re, zipfile, hashlib, json, datetime as dt
from decimal import Decimal as D
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

FIXED = dt.datetime(2026, 11, 10, 0, 0, 0)


def us(v): return f"{D(v):,.2f}"


def ind(v):
    v = D(v).quantize(D('0.01')); neg = v < 0; s = f"{abs(v):.2f}"; i, f = s.split('.')
    if len(i) > 3:
        h, t = i[:-3], i[-3:]; parts = []
        while len(h) > 2: parts.insert(0, h[-2:]); h = h[:-2]
        if h: parts.insert(0, h)
        i = ','.join(parts + [t])
    return ('-' if neg else '') + i + '.' + f


class Out:
    def __init__(s, root):
        s.root = root; s.pdfs = []; s.reg = {}

    def _p(s, rel, feeds, who, page):
        p = os.path.join(s.root, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        s.reg[rel] = dict(feeds=feeds, who=who, page=page); return p

    def text(s, rel, txt, feeds, who, page, nl='\n'):
        with open(s._p(rel, feeds, who, page), 'w', newline='') as f: f.write(txt.replace('\n', nl) if nl != '\n' else txt)

    def raw(s, rel, data, feeds, who, page):
        with open(s._p(rel, feeds, who, page), 'wb') as f: f.write(data)

    def xlsx(s, rel, wb, feeds, who, page):
        wb.properties.created = FIXED; wb.properties.modified = FIXED; wb.properties.creator = 'export'
        buf = io.BytesIO(); wb.save(buf); zin = zipfile.ZipFile(buf); out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            for n in sorted(zin.namelist()):
                zi = zipfile.ZipInfo(n, (2026, 11, 10, 0, 0, 0)); zi.compress_type = zipfile.ZIP_DEFLATED; zi.external_attr = 0o644 << 16
                data = zin.read(n)
                if n == 'docProps/core.xml':
                    data = re.sub(rb'(<dcterms:(created|modified)[^>]*>)[^<]*', rb'\g<1>2026-11-10T00:00:00Z', data)
                z.writestr(zi, data)
        s.raw(rel, out.getvalue(), feeds, who, page)

    def pdf(s, rel, html, feeds, who, page, landscape=False):
        s.pdfs.append((s._p(rel, feeds, who, page), html, landscape))

    def flush(s):
        from playwright.sync_api import sync_playwright
        foot = ('<div style="font-size:7px;width:100%;padding:0 12mm;color:#555;font-family:Arial;display:flex;justify-content:space-between">'
                '<span class="title"></span><span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>')
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
            pg = b.new_page()
            for path, html, land in s.pdfs:
                pg.set_content(html)
                data = pg.pdf(format='A4', landscape=land, print_background=True, display_header_footer=True, header_template='<span></span>',
                              footer_template=foot, margin=dict(top='14mm', bottom='16mm', left='13mm', right='13mm'))
                data = re.sub(rb"\(D:\d{14}[^)]*\)", b"(D:20261110000000+00'00')", data)
                with open(path, 'wb') as f: f.write(data)
            b.close()


# ---------- xlsx helpers ----------
HFILL = PatternFill('solid', fgColor='D9D9D9'); BOLD = Font(bold=True); THIN = Side(style='thin', color='999999')


def sheet(wb, name, title, headers, rows, widths=None, first=False, hfill=HFILL, total=None, start=None):
    ws = wb.active if first else wb.create_sheet(); ws.title = name; r = 1
    for k, t in enumerate(title or []):
        ws.cell(r, 1, t).font = Font(bold=(k == 0), size=12 if k == 0 else 10, italic=(k > 0)); r += 1
    if title: r += 1
    if start: r = max(r, start)
    for c, h in enumerate(headers, 1):
        x = ws.cell(r, c, h); x.font = BOLD; x.fill = hfill; x.alignment = Alignment(wrap_text=True, vertical='center')
        x.border = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
    hr = r
    for row in rows + ([total] if total else []):
        r += 1
        for c, v in enumerate(row, 1):
            cell = ws.cell(r, c, wr(v))
            fmt(cell, v)
            if total and row is total: cell.font = BOLD
    for c in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(c)].width = (widths or {}).get(c, 18)
    ws.freeze_panes = ws.cell(hr + 1, 1)
    return ws


def wr(v):
    if isinstance(v, D): return float(v)
    return v


def fmt(cell, v):
    if isinstance(v, D):
        e = -v.as_tuple().exponent if v == v else 2
        cell.number_format = '#,##0.00' if e <= 2 else ('#,##0.' + '0' * min(e, 6))
    elif isinstance(v, dt.date): cell.number_format = 'DD-MMM-YYYY'


def kvsheet(wb, name, title, pairs, first=False, w=(34, 60)):
    ws = wb.active if first else wb.create_sheet(); ws.title = name; r = 1
    for k, t in enumerate(title or []):
        ws.cell(r, 1, t).font = Font(bold=(k == 0), size=12 if k == 0 else 10, italic=(k > 0)); r += 1
    r += 1
    for k, v in pairs:
        if v is None: ws.cell(r, 1, k).font = BOLD
        else:
            ws.cell(r, 1, k); c = ws.cell(r, 2, wr(v)); fmt(c, v); c.alignment = Alignment(horizontal='left')
        r += 1
    ws.column_dimensions['A'].width, ws.column_dimensions['B'].width = w
    return ws


# ---------- HTML/PDF helpers ----------
STYLES = {
    'scheme': dict(font="Georgia,'Times New Roman',serif", accent='#1f2f4d', band='border-bottom:3px double #1f2f4d'),
    'fme': dict(font="Georgia,serif", accent='#3b2f5c', band='border-bottom:2px solid #3b2f5c'),
    'bank': dict(font="'Courier New',monospace", accent='#000', band='border-bottom:1px solid #000'),
    'bankb': dict(font="Arial,Helvetica,sans-serif", accent='#7a1420', band='border-bottom:4px solid #7a1420'),
    'dp': dict(font="Arial,sans-serif", accent='#444', band='border:1px solid #444;padding:6px'),
    'valuer': dict(font="'Trebuchet MS',Verdana,sans-serif", accent='#0d6b6b', band='border-left:10px solid #0d6b6b;padding-left:10px'),
    'dev1': dict(font="Calibri,Arial,sans-serif", accent='#b4531a', band='border-bottom:3px solid #b4531a'),
    'dev2': dict(font="Verdana,sans-serif", accent='#2f6b2f', band='border-top:6px solid #2f6b2f;padding-top:6px'),
    'govt': dict(font="'Times New Roman',serif", accent='#000', band='border:2px solid #000;padding:6px;text-align:center'),
    'vendor': dict(font="Arial,sans-serif", accent='#333', band='border-bottom:1px solid #333'),
    'trustee': dict(font="'Palatino Linotype',Georgia,serif", accent='#5a3d1b', band='border-bottom:2px solid #5a3d1b'),
    'law': dict(font="Garamond,Georgia,serif", accent='#222', band='border-bottom:1px solid #222;text-align:center'),
}


def esc(x): return str(x).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def kv(pairs): return '<div class="kvs">' + ''.join(f'<div class="kv"><span class="k">{esc(k)}:</span> <span class="v">{esc(v)}</span></div>' for k, v in pairs) + '</div>'


def table(headers, rows, num=(), cls=''):
    h = ''.join(f'<th class="{"n" if i in num else ""}">{esc(x)}</th>' for i, x in enumerate(headers))
    b = ''.join('<tr>' + ''.join(f'<td class="{"n" if i in num else ""}">{esc(x)}</td>' for i, x in enumerate(r)) + '</tr>' for r in rows)
    return f'<table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>'


def p(t): return f'<p>{esc(t)}</p>'
def h(t): return f'<h3>{esc(t)}</h3>'
def note(t): return f'<p class="note">{esc(t)}</p>'
def sign(name, title, org=''): return f'<div class="sign"><div class="line"></div><b>{esc(name)}</b><br>{esc(title)}<br>{esc(org)}</div>'
def brk(): return '<div style="page-break-after:always"></div>'


def doc(style, issuer, sub, title, blocks, footer=''):
    st = STYLES[style]
    css = f"""body{{font-family:{st['font']};font-size:10.5px;color:#111;margin:0}} .lh{{{st['band']};margin-bottom:12px;padding-bottom:6px}}
    .lh .i{{font-size:17px;font-weight:bold;color:{st['accent']}}} .lh .s{{font-size:8.5px;color:#444}} h2{{font-size:13.5px;margin:10px 0 8px;color:{st['accent']}}}
    h3{{font-size:11px;margin:12px 0 4px;color:{st['accent']}}} .kv{{margin:2px 0}} .k{{color:#333;font-weight:bold}} p{{margin:6px 0;line-height:1.45}}
    table{{border-collapse:collapse;width:100%;margin:6px 0}} th,td{{border:1px solid #777;padding:3px 5px;font-size:9.5px;vertical-align:top}}
    th{{background:#eee;text-align:left}} .n{{text-align:right;white-space:nowrap}} .note{{font-size:8.5px;color:#444;font-style:italic}}
    .sign{{margin-top:26px;width:260px}} .sign .line{{border-bottom:1px solid #000;height:26px;margin-bottom:3px}} .ft{{margin-top:14px;font-size:8px;color:#555;border-top:1px solid #aaa;padding-top:4px}}
    tr{{page-break-inside:avoid}} table.stmt td:first-child,table.stmt td:nth-child(2){{white-space:nowrap}} table.stmt td:nth-child(3){{font-size:8.5px}}"""
    return (f'<html><head><meta charset="utf-8"><title>{esc(title)}</title><style>{css}</style></head><body><div class="lh"><div class="i">{esc(issuer)}</div>'
            f'<div class="s">{esc(sub)}</div></div><h2>{esc(title)}</h2>{"".join(blocks)}<div class="ft">{esc(footer)}</div></body></html>')


def sha(path):
    hh = hashlib.sha256()
    with open(path, 'rb') as f: hh.update(f.read())
    return hh.hexdigest()
