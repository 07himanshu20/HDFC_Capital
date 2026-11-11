"""Regulator report files.

The IFSCA quarterly report (GIFT IFSC scheme) and the SEBI quarterly activity report (onshore scheme) are generated as
.xlsx workbooks, only from a locked NAV.  Each file is stored with its SHA-256, read back with the parser that next
quarter's ingestion uses for the prior report, and tied to the closing trial balance.  The result drives rule R15.

    <STORAGE_DIR>/reports/<scheme>/<period>/<report run id>_<file name>
"""
import hashlib
import os
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from sqlalchemy import select

from ..config import STORAGE_DIR
from ..engine import regreport
from ..engine.coa import TYPE
from ..models import ReportRun, TrialBalanceLine
from ..parsing import util
from ..parsing.extract import parse_prior_report

REPORTS_DIR = STORAGE_DIR / 'reports'
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def is_regulator(sv, name):
    m = (sv or {}).get('reg_report')
    return bool(m) and name == m['title']


def closing_books(db, run_id, scheme, sv):
    tb = {t.gl: D(t.closing) for t in db.execute(select(TrialBalanceLine).where(TrialBalanceLine.run_id == run_id, TrialBalanceLine.scheme == scheme)).scalars()}
    g = lambda k: tb.get(k, D(0))
    return dict(nav=sum((v for k, v in tb.items() if TYPE.get(k) in ('a', 'l')), D(0)), drawn=-g(3100), cash=g(1100), investments=g(1200),
                committed=D(str(sv['meta']['committed'])))


def _parse(path):
    try:
        return parse_prior_report(str(path))
    finally:
        util._xl_cache.pop(str(path), None)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def generate(db, run, sv, scheme, nv, user_name):
    """write the workbook for the locked NAV version `nv`, read it back, record a ReportRun (caller commits)"""
    m = sv['reg_report']
    per = sv['meta']['period']['code']
    rr = ReportRun(scheme=scheme, name=m['title'], kind='regulator', nav_version_id=nv.id, nav_status=nv.status, by=user_name, run_id=run.id, period_code=per,
                   hash='')
    db.add(rr)
    db.flush()
    folder = REPORTS_DIR / scheme / per
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{rr.id:05d}_{m['file_name']}"
    prep = [['Prepared on', date.today().strftime('%d-%b-%Y')], ['Prepared by', user_name],
            ['NAV version', f"v{nv.version}, approved by {nv.approved_by} on {nv.approved_at:%d-%b-%Y}"],
            ['Books', f"ingestion run {run.id} of {run.created_at:%d-%b-%Y %H:%M} UTC"], ['Filed on', ''], ['Filed by', '']]
    try:
        regreport.write_workbook(m, prep, path)
        ok, checks = regreport.verify_workbook(path, closing_books(db, run.id, scheme, sv), _parse)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    rr.file_name, rr.file_path, rr.file_size = m['file_name'], str(path), os.path.getsize(path)
    rr.file_sha256 = rr.hash = sha256(path)
    rr.check_status, rr.check_detail = ('PASS' if ok else 'FAIL'), checks
    return rr


def stored_file(rr):
    """path of a generated file, only if it is inside the reports folder and unchanged since it was generated"""
    if not rr or not rr.file_path:
        return None, 'No file for this report'
    p = Path(rr.file_path).resolve()
    if not str(p).startswith(str(REPORTS_DIR.resolve()) + os.sep) or not p.is_file():
        return None, 'File not found'
    if sha256(p) != rr.file_sha256:
        return None, 'The stored file no longer matches the hash recorded when it was generated'
    return p, None


def preview(path):
    """cell text of every sheet, formatted as Excel shows it (for the on-screen view of the actual file)"""
    import openpyxl
    wb = openpyxl.load_workbook(path)
    out = []
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows():
            cells = []
            for c in r:
                v = c.value
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    dp = c.number_format.split('.')[1].count('0') if '.' in c.number_format else 0
                    v = f"{v:,.{dp}f}"
                cells.append(dict(v='' if v is None else str(v), b=bool(c.font and c.font.b), n=isinstance(c.value, (int, float))))
            rows.append(cells)
        out.append(dict(name=ws.title, rows=rows))
    return out


def r15_override(rule, rr, sv):
    """R15 after the regulator workbook has been generated from the locked NAV and read back"""
    checks = {c[0]: c for c in rr['checks']}
    nav, drawn = checks.get('Net asset value', ['', '', '']), checks.get('Cumulative drawn', ['', '', ''])
    P = sv['meta']['period']
    bad = [c for c in rr['checks'] if not c[3]]
    return dict(rule, status=rr['check'],
                title=f"Reports: {P['prev_label']} report as filed ties to the opening books; {P['label']} {rr['n']} generated from locked NAV v{rr['nav_v']} ties to the closing books",
                left=f"workbook NAV {nav[1]}, drawn {drawn[1]}", right=f"books NAV {nav[2]}, drawn {drawn[2]}",
                detail=(f"{rr['file']} (SHA-256 {rr['sha'][:16]}) read back with the prior-report parser: " +
                        ('all ' + str(len(rr['checks'])) + ' figures tie (NAV, drawn, cash, investments, commitments, Part C total, investor and instrument sheets).'
                         if not bad else 'differences: ' + '; '.join(f"{c[0]} {c[1]} vs {c[2]}" for c in bad)) +
                        f" Prior report: {rule['left']} = {rule['right']}."),
                src=f"{rule['src']}, {rr['file']}")
