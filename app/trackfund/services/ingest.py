"""Ingestion: upload -> workspace -> pipeline -> persist books -> make current -> NAV draft -> audit."""
import os
import shutil
import logging
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from ..models import (Upload, IngestionRun, SourceFile, Journal, JournalLine, BankLine, TrialBalanceLine, CapitalAccount, RuleResult, NavVersion, Setting)
from ..catalog import CATALOG
from .. import access
from ..parsing.extract import ParseError, parse_opening, opening_schemes
from ..parsing.util import sha_file, quarter_end, qcode
from ..pipeline import layout_from_dir, run_layout, SCHEME_DIR
from ..engine.coa import GL
from .storage import safe_extract, build_workspace, run_dir, staging_dir, UploadError
from .workflow import audit, current_run, latest_nav, is_locked

logger = logging.getLogger('trackfund')


def get_profile(db):
    s = db.get(Setting, 'org_profile')
    return s.value if s else {}


def _scheme_files_digest(ws: Path):
    """{scheme_code: {rel: sha}} for lock comparisons"""
    out = {}
    if not ws or not ws.exists():
        return out
    for e in os.listdir(ws):
        m = SCHEME_DIR.match(e)
        if m:
            base = ws / e
            out[m.group(1)] = {str(p.relative_to(base)): sha_file(p) for p in base.rglob('*') if p.is_file()}
    return out


def ingest(db, user, uploads, mode=None, scheme_hint=None):
    """uploads: list of (original_name, local_path). Returns the IngestionRun (succeeded or failed)."""
    up = Upload(uploaded_by=user.full_name, original_names=[n for n, _ in uploads], mode=mode or 'auto', scheme_hint=scheme_hint)
    db.add(up)
    db.flush()
    stage = staging_dir(up.id)
    stage.mkdir(parents=True, exist_ok=True)
    total = 0
    count = 0
    recorded = {}
    try:
        for name, path in uploads:
            total += os.path.getsize(path)
            if name.lower().endswith('.zip'):
                if not zipfile.is_zipfile(path):
                    raise UploadError(f"{name} is not a valid zip archive")
                count += safe_extract(path, stage)
            else:
                safe = os.path.basename(name.replace('\\', '/'))
                if not safe or safe.startswith('.'):
                    continue
                shutil.copy2(path, stage / safe)
                count += 1
        up.file_count, up.bytes = count, total
        has_schemes = any(SCHEME_DIR.match(d) for _, ds, _ in os.walk(stage) for d in ds)
        if mode in (None, '', 'auto'):
            mode = 'replace' if has_schemes else 'merge'
        up.mode = mode
    except UploadError as e:
        run = IngestionRun(upload_id=up.id, created_by=user.full_name, status='failed', workspace='', error=str(e), log=[['r', str(e)]], finished_at=datetime.utcnow())
        db.add(run)
        db.commit()
        return run

    prev = current_run(db)
    run = IngestionRun(upload_id=up.id, created_by=user.full_name, status='running', workspace='')
    db.add(run)
    db.commit()          # the upload and the run are recorded even if processing fails below
    log = [['k', f"Upload {up.id}: {count} file(s), {total / 1048576:.1f} MB, mode {mode}" + (f", scheme {scheme_hint}" if scheme_hint else '')]]
    return _process(db, user, run, prev, log, scheme_hint,
                    lambda ws: build_workspace(stage, ws, mode, Path(prev.workspace) if prev and prev.workspace else None, scheme_hint))


class DeleteRefused(Exception):
    pass


DOC = {d.key: d for d in CATALOG}


def deletable(db, run):
    """every file of the current run with whether it can be deleted and what deleting it does"""
    files = list(run.files)
    out = []
    obligations = {s: v['obligations'] for s, v in (run.dashboard or {}).get('schemes', {}).items()}
    for f in files:
        d = DOC.get(f.doc_type)
        same = [g for g in files if g.scheme == f.scheme and g.doc_type == f.doc_type]
        reason = None
        if f.scheme == 'shared':
            reason = 'The locked opening balances are required for every scheme. Upload a replacement instead.'
        elif d and d.required and len(same) == 1:
            reason = f"Required: this is the scheme's only {d.label.lower()}. Upload a corrected file instead (it replaces this one)."
        evidence = [o['ref'] for o in obligations.get(f.scheme, []) if o.get('evidence') and (o['evidence'] == f.rel_path or f.rel_path.endswith(o['evidence']))]
        out.append(dict(scheme=f.scheme, file=f.rel_path, doc=f.doc_type, label=d.label if d else 'Unrecognised', required=bool(d and d.required), size=f.size,
                        parsed=bool(d and d.parsed),
                        sha=f.sha256, page=f.page, refused=reason, evidence_for=evidence))
    return out


def delete_files(db, user, scheme, rels):
    """
    Remove files from the current quarter (administrator only). A new run is built from the current files minus these and the
    books are recomputed; it becomes current only if it succeeds. Earlier runs keep their own copies (history).
    """
    prev = current_run(db)
    if prev is None:
        raise DeleteRefused('No data loaded yet.')
    rels = sorted(set(rels))
    if not rels:
        raise DeleteRefused('Choose at least one file.')
    info = {(x['scheme'], x['file']): x for x in deletable(db, prev)}
    missing = [r for r in rels if (scheme, r) not in info]
    if missing:
        raise DeleteRefused(f"Not in the current files of scheme {scheme}: {', '.join(missing)}")
    refused = [f"{r}: {info[(scheme, r)]['refused']}" for r in rels if info[(scheme, r)]['refused']]
    if refused:
        raise DeleteRefused(' '.join(refused))
    per = next((v['meta']['period']['code'] for s, v in prev.dashboard['schemes'].items() if s == scheme), None)
    if per and is_locked(db, scheme, per):
        raise DeleteRefused(f"Scheme {scheme}: {per[:2]} {per[2:]} is locked (NAV approved). Files of a locked quarter cannot be deleted.")
    prev_root = Path(prev.workspace)
    paths = {f.rel_path: f for f in prev.files if f.scheme == scheme}
    up = Upload(uploaded_by=user.full_name, original_names=[f"delete {r}" for r in rels], mode='delete', scheme_hint=scheme, file_count=0, bytes=0)
    db.add(up)
    db.flush()
    run = IngestionRun(upload_id=up.id, created_by=user.full_name, status='running', workspace='')
    db.add(run)
    db.commit()
    log = [['k', f"Delete {len(rels)} file(s) from scheme {scheme} (requested by {user.full_name}); books recomputed without them"]]

    def build(ws):
        shutil.copytree(prev_root, ws, dirs_exist_ok=True)
        for r in rels:
            target = ws / os.path.relpath(paths[r].storage_path, prev_root)
            if not str(target.resolve()).startswith(str(ws.resolve()) + os.sep):
                raise UploadError(f"Bad path {r}")
            target.unlink()
            log.append(['w', f"Deleted {r} ({paths[r].doc_type or 'unrecognised'}, SHA-256 {paths[r].sha256[:16]})"])
            parent = target.parent
            while parent != ws and parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        m = ws / 'manifest.json'          # the manifest no longer describes the file set
        if m.exists():
            m.unlink()
        return []

    run = _process(db, user, run, prev, log, scheme, build)
    if run.status == 'failed':
        run.error = (f"Nothing was deleted: the books of scheme {scheme} cannot be computed without "
                     f"{'this file' if len(rels) == 1 else 'these files'} ({run.error}). Upload a corrected file instead.")
        db.commit()
    if run.status == 'succeeded':
        for r in rels:
            audit(db, user.full_name, access.role_of(user), scheme, 'FILE_DELETED', f"{r} · SHA-256 {paths[r].sha256[:16]} · run {run.id}")
        db.commit()
    return run


def delete_all(db, user):
    """
    Remove every source file of the current quarter, for all schemes (administrator only). Nothing is loaded afterwards: the
    dashboard is empty until the next upload, which then builds the books from scratch. Earlier runs keep their own copies
    (history), the NAV draft or submission of each scheme is replaced by a new draft on that upload, and a locked quarter
    cannot be cleared.
    """
    prev = current_run(db)
    if prev is None:
        raise DeleteRefused('No data loaded yet.')
    schemes = {s: v['meta']['period']['code'] for s, v in (prev.dashboard or {}).get('schemes', {}).items()}
    locked = [f"{s} ({p[:2]} {p[2:]})" for s, p in schemes.items() if is_locked(db, s, p)]
    if locked:
        raise DeleteRefused(f"Scheme {', '.join(locked)} is locked (NAV approved). Files of a locked quarter cannot be deleted.")
    files = list(prev.files)
    counts = {s: sum(1 for f in files if f.scheme == s) for s in sorted({f.scheme for f in files})}
    up = Upload(uploaded_by=user.full_name, original_names=['delete all files'], mode='delete-all', file_count=0, bytes=0)
    db.add(up)
    db.flush()
    now = datetime.utcnow()
    note = (f"All {len(files)} source files deleted ({', '.join(f'{s} {n}' for s, n in counts.items())}) by {user.full_name}. "
            f"Nothing is loaded until the next upload; run {prev.id} keeps its copies.")
    run = IngestionRun(upload_id=up.id, created_by=user.full_name, status='succeeded', workspace='', period_code=prev.period_code,
                       log=[['w', note]], finished_at=now)
    db.add(run)
    prev.is_current = False
    db.flush()
    for s in schemes:
        audit(db, user.full_name, access.role_of(user), s, 'ALL_FILES_DELETED',
              f"{counts.get(s, 0)} files of scheme {s} and {counts.get('shared', 0)} shared · run {run.id} (was run {prev.id})")
    db.commit()
    return run


def _process(db, user, run, prev, log, scheme_hint, build):
    """build the run workspace, run the pipeline, persist, make current.  Any failure leaves the current books untouched."""
    ws = run_dir(run.id)
    recorded = {}
    try:
        build(ws)
        run.workspace = str(ws)
        layout = layout_from_dir(ws)
        # files carried over from the previous run must still match the hashes recorded for them then
        if prev and prev.workspace:
            prev_root = Path(prev.workspace)
            for f in prev.files:
                rel_root = os.path.relpath(f.storage_path, prev_root)
                if os.path.exists(ws / rel_root):
                    recorded[rel_root.replace(os.sep, '/')] = f.sha256
        layout['recorded_sha'] = recorded
        # a locked quarter cannot be changed
        old = _scheme_files_digest(Path(prev.workspace)) if prev and prev.workspace else {}
        new = _scheme_files_digest(ws)
        if layout.get('opening'):
            for sid in opening_schemes(layout['opening']):
                if sid not in layout['schemes']:
                    continue
                per = qcode(_q_end_after(layout['opening'], sid))
                if is_locked(db, sid, per) and old.get(sid) != new.get(sid):
                    raise ParseError(f"Scheme {sid}: {per[:2]} {per[2:]} is locked (NAV approved). Files for a locked quarter cannot be changed; "
                                     f"post corrections as dated adjustments in the next quarter.")
        res = run_layout(layout, get_profile(db), log)
    except Exception as e:  # any parsing problem must leave the current books untouched and tell the user why
        msg = str(e) if isinstance(e, (ParseError, UploadError)) else f"Could not process the files: {type(e).__name__}: {e}"
        if not isinstance(e, (ParseError, UploadError)):
            logger.exception('ingestion run %s failed', run.id)
        return _fail(db, run, user, scheme_hint, log, msg)

    try:
        _persist(db, run, res, ws)
    except Exception as e:
        logger.exception('persisting run %s failed', run.id)
        db.rollback()
        run = db.get(IngestionRun, run.id)
        return _fail(db, run, user, scheme_hint, log, f"Could not save the results: {type(e).__name__}: {e}")
    data = res['data']
    first = next(iter(data['schemes'].values()))
    run.period_code = first['meta']['period']['code']
    run.dashboard = data
    run.summary = {s: dict(nav=v['nav_close'], journals=len(v['journals']), files=len(v['files']), rules=len(v['rules']),
                           passed=sum(1 for r in v['rules'] if r['status'] == 'PASS'), failed=sum(1 for r in v['rules'] if r['status'] == 'FAIL'),
                           period=v['meta']['period']['code']) for s, v in data['schemes'].items()}
    run.log = [list(x) for x in log]
    run.status, run.finished_at = 'succeeded', datetime.utcnow()
    if prev:
        prev.is_current = False
    run.is_current = True
    for s, v in data['schemes'].items():
        per = v['meta']['period']['code']
        nv = latest_nav(db, s, per)
        changed = not prev or (old.get(s) != new.get(s))
        if nv is None:
            db.add(NavVersion(scheme=s, period_code=per, version=1, run_id=run.id, nav=D(str(v['nav_close'])), status='draft'))
        elif nv.status in ('draft', 'submitted') and changed:
            nv.status = 'superseded'
            db.add(NavVersion(scheme=s, period_code=per, version=nv.version + 1, run_id=run.id, nav=D(str(v['nav_close'])), status='draft'))
        audit(db, user.full_name, access.role_of(user), s, 'INGEST', f"{len(v['files'])} files parsed; reconciliation re-run (run {run.id})")
    db.commit()
    return run


def _fail(db, run, user, scheme_hint, log, msg):
    log.append(['r', msg])
    run.status, run.error, run.log, run.finished_at = 'failed', msg, log, datetime.utcnow()
    audit(db, user.full_name, access.role_of(user), scheme_hint or 'all', 'INGEST_FAILED', msg[:300])
    db.commit()
    return run


def _q_end_after(opening_path, sid):
    return quarter_end(parse_opening(opening_path, sid)['as_at'] + timedelta(days=1))


def _persist(db, run, res, ws):
    seen_shared = set()
    for s, X in res['bundles'].items():
        Bk = res['books'][s]
        per = X['period']['qcode']
        for r in X['register']:
            if r.get('shared'):
                if r['rel'] in seen_shared:
                    continue
                seen_shared.add(r['rel'])
            db.add(SourceFile(run_id=run.id, scheme=s if not r.get('shared') else 'shared', rel_path=r['rel'], storage_path=r['path'], doc_type=r['doc'], format=r['format'],
                              sha256=r['sha256'], size=os.path.getsize(r['path']), feeds=r.get('feeds', []), who=r.get('who'), page=r.get('page')))
        bank_jv = {}
        for j in Bk['journals']:
            jr = Journal(run_id=run.id, scheme=s, period_code=per, journal_no=j['no'], date=j['date'], kind=j['kind'], ref=j['ref'], description=j['desc'], source=j['src'],
                         bank_loc=Bk['bank'][j['bank']]['loc'] if j['bank'] is not None else None, tally_voucher=j.get('tally'))
            if j['bank'] is not None:
                bank_jv[j['bank']] = j['no']
            for l in j['lines']:
                jr.lines.append(JournalLine(gl=l['gl'], amount=l['amt'], investor=l.get('investor'), instrument=l.get('instrument'), txn_ccy=l.get('txn_ccy'),
                                            txn_amount=l.get('txn_amt'), fx_rate=l.get('rate')))
            db.add(jr)
        for i, b in enumerate(Bk['bank']):
            db.add(BankLine(run_id=run.id, scheme=s, seq=i + 1, date=b['date'], narration=b.get('narr_full', b['narr']), ref=b['ref'], amount=b['amt'], balance=b['bal'],
                            journal_no=bank_jv.get(i), source_loc=b.get('loc')))
        for g in sorted(set(Bk['open_tb']) | set(Bk['close_tb'])):
            db.add(TrialBalanceLine(run_id=run.id, scheme=s, gl=g, account=GL.get(g, (str(g),))[0], opening=Bk['open_tb'].get(g, D(0)),
                                    movement=Bk['close_tb'].get(g, D(0)) - Bk['open_tb'].get(g, D(0)), closing=Bk['close_tb'].get(g, D(0))))
        for k, c in Bk['capital'].items():
            db.add(CapitalAccount(run_id=run.id, scheme=s, investor=k, unit_class=c['cls'], opening=c['opening'], contributions=c['contributions'],
                                  distributions=c['distributions_income'] + c['distributions_roc'], income=c['income_alloc'], fee=c['fee_alloc'], expense=c['expense_alloc'],
                                  fair_value=c['fv_alloc'], fx=c['fx_alloc'], closing=c['closing'], units=c['units'], nav_per_unit=c['nav_per_unit']))
        for r in res['data']['schemes'][s]['rules']:
            db.add(RuleResult(run_id=run.id, scheme=r['scheme'] if r['scheme'] != 'all' else s, rule=r['rule'], title=r['title'], status=r['status'], left=r['left'],
                              right=r['right'], detail=r['detail'], src=r['src']))
    db.flush()
