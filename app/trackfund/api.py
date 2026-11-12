"""HTTP API and static front end."""
import csv
import io
from decimal import Decimal
import os
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import __version__
from . import access
from .bootstrap import init_db
from .config import COOKIE_SECURE, SESSION_HOURS, MAX_UPLOAD_MB, UPLOAD_PROGRESS_SECONDS
from .db import get_db
from .models import User, IngestionRun, SourceFile, Journal, BankLine, TrialBalanceLine, CapitalAccount, Setting, ReportRun
from .security import verify_password, make_token, read_token, fingerprint, hash_password
from .services import workflow as wf
from .services import reports as rep
from .services.ingest import ingest, delete_files, delete_all, deletable, DeleteRefused

STATIC = Path(__file__).parent / 'static'
COOKIE = 'tf_session'

app = FastAPI(title='TrackFund fund operations', version=__version__, docs_url='/api/docs', openapi_url='/api/openapi.json')


@app.on_event('startup')
def _startup():
    init_db()


@app.middleware('http')
async def csrf_and_headers(request: Request, call_next):
    # state-changing API calls must carry a header that a cross-site form cannot set
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and request.url.path.startswith('/api/') and request.headers.get('x-requested-with') != 'trackfund':
        return JSONResponse({'detail': 'Missing request header'}, status_code=403)
    resp = await call_next(request)
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Referrer-Policy'] = 'same-origin'
    # nothing from the API (data, source files, report files) may be kept in a browser cache and shown to the next person who signs in
    if request.url.path == '/' or request.url.path.endswith('.html') or request.url.path.startswith('/api/'):
        resp.headers['Cache-Control'] = 'no-store'
    return resp


# ------------------------------------------------------------------ auth
def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    tok = request.cookies.get(COOKIE)
    t = read_token(tok) if tok else None
    if not t:
        raise HTTPException(401, 'Not signed in')
    u = db.get(User, t[0])
    if not u or not u.active or fingerprint(u.password_hash) != t[1]:
        raise HTTPException(401, 'Not signed in')
    return u


def admin_user(u: User = Depends(current_user)) -> User:
    if not u.is_admin:
        raise HTTPException(403, 'Administrator only')
    return u


def need_page(u: User, page: str):
    if not access.can_see(u, page):
        raise HTTPException(403, f"{wf.ROLE_LABELS.get(access.role_of(u), u.role)} has no access to {dict((k, l) for k, l, _ in access.PAGES).get(page, page)}.")


def _user_out(u: User, with_access=True):
    d = dict(id=u.id, username=u.username, full_name=u.full_name, role=access.role_of(u), role_label=wf.ROLE_LABELS.get(access.role_of(u), u.role),
             is_admin=u.is_admin, active=u.active, last_login_at=u.last_login_at.isoformat() if u.last_login_at else None)
    if with_access:
        d['access'] = access.access_info(u)
    return d


class LoginIn(BaseModel):
    username: str
    password: str


@app.post('/api/auth/login')
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    u = db.execute(select(User).where(User.username == body.username.strip().lower())).scalar_one_or_none()
    if not u or not u.active or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, 'Wrong username or password')
    u.last_login_at = datetime.utcnow()
    wf.audit(db, u.full_name, u.role, 'all', 'SIGN_IN', wf.ROLE_LABELS.get(u.role, u.role))
    db.commit()
    response.set_cookie(COOKIE, make_token(u.id, u.password_hash), httponly=True, samesite='lax', secure=COOKIE_SECURE, max_age=SESSION_HOURS * 3600)
    return _user_out(u)


@app.post('/api/auth/logout')
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {'ok': True}


@app.get('/api/auth/me')
def me(u: User = Depends(current_user)):
    return _user_out(u)


class PasswordIn(BaseModel):
    current: str
    new: str


@app.post('/api/auth/password')
def change_password(body: PasswordIn, response: Response, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current, u.password_hash):
        raise HTTPException(400, 'Current password is wrong')
    if len(body.new) < 10:
        raise HTTPException(400, 'Use at least 10 characters')
    u.password_hash = hash_password(body.new)
    wf.audit(db, u.full_name, u.role, 'all', 'PASSWORD_CHANGED', u.username)
    db.commit()
    response.set_cookie(COOKIE, make_token(u.id, u.password_hash), httponly=True, samesite='lax', secure=COOKIE_SECURE, max_age=SESSION_HOURS * 3600)
    return {'ok': True}


# ------------------------------------------------------------------ dashboard
def _directory(db):
    out = []
    for r in wf.ROLE_ORDER:
        u = db.execute(select(User).where(User.role == r, User.active == True).order_by(User.id)).scalars().first()  # noqa: E712
        out.append([r, u.full_name if u else '—', wf.ROLE_LABELS[r]])
    return out


def _view(db, run, u):
    """dashboard data and workflow state, cut down to what this user's pages read"""
    st = wf.state(db, run)
    data = wf.apply_overrides(run.dashboard, st) if run else None
    return access.filter_dashboard(data, u), access.filter_state(st, u)


@app.get('/api/dashboard')
def dashboard(u: User = Depends(current_user), db: Session = Depends(get_db)):
    run = wf.current_run(db)
    data, st = _view(db, run, u)
    prof = db.get(Setting, 'org_profile')
    show_run = access.can_see(u, 'ingestion')
    return dict(data=data, state=st, user=_user_out(u), directory=_directory(db), brand=(prof.value.get('brand') if prof else {}) or {},
                run=dict(id=run.id, created_at=run.created_at.isoformat(), created_by=run.created_by, period=run.period_code,
                         summary=run.summary if show_run else None) if run else None,
                can_ingest=access.can(u, 'upload'), can_delete=access.can(u, 'delete_files'), max_upload_mb=MAX_UPLOAD_MB,
                upload_progress_s=UPLOAD_PROGRESS_SECONDS)


@app.get('/api/state')
def get_state(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return _view(db, wf.current_run(db), u)[1]


class ActionIn(BaseModel):
    scheme: str | None = None
    arg: str | None = None
    clock: str | None = None


@app.post('/api/actions/{action}')
def do_action(action: str, body: ActionIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        msg = wf.act(db, u, action, body.scheme, body.arg, body.clock)
        db.commit()
    except wf.Forbidden as e:
        db.rollback()
        raise HTTPException(403, str(e))
    except wf.Conflict as e:
        db.rollback()
        raise HTTPException(409, str(e))
    run = wf.current_run(db)
    data, st = _view(db, run, u)
    return dict(message=msg, state=st, data=data if action in ('obl', 'gen') else None)


# ------------------------------------------------------------------ ingestion
@app.post('/api/uploads')
async def upload(files: list[UploadFile] = File(...), mode: str = Form('auto'), scheme: str = Form(''), u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not access.can(u, 'upload'):
        raise HTTPException(403, 'Only the finance maker, the finance checker or an administrator can upload files.')
    if mode not in ('auto', 'replace', 'merge'):
        raise HTTPException(400, 'mode must be auto, replace or merge')
    tmp = tempfile.mkdtemp(prefix='tf_up_')
    saved = []
    total = 0
    try:
        for f in files:
            name = os.path.basename((f.filename or 'upload').replace('\\', '/'))
            p = os.path.join(tmp, f"{len(saved):04d}_{name}")
            with open(p, 'wb') as out:
                while chunk := await f.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_UPLOAD_MB * 1024 * 1024:
                        raise HTTPException(413, f"Upload exceeds {MAX_UPLOAD_MB} MB")
                    out.write(chunk)
            saved.append((name, p))
        run = ingest(db, u, saved, mode=mode, scheme_hint=scheme.strip().upper() or None)
    finally:
        for _, p in saved:
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass
    return _run_out(run, full=True)


def _run_out(r: IngestionRun, full=False):
    d = dict(id=r.id, created_at=r.created_at.isoformat(), finished_at=r.finished_at.isoformat() if r.finished_at else None, created_by=r.created_by, status=r.status,
             is_current=r.is_current, period=r.period_code, error=r.error, summary=r.summary,
             note=r.log[-1][1] if r.status == 'succeeded' and not r.summary and r.log else None)
    if full:
        d['log'] = r.log
    return d


@app.get('/api/runs')
def runs(u: User = Depends(current_user), db: Session = Depends(get_db)):
    need_page(u, 'ingestion')
    return [_run_out(r) for r in db.execute(select(IngestionRun).order_by(IngestionRun.id.desc()).limit(100)).scalars()]


@app.get('/api/runs/{run_id}')
def run_detail(run_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    need_page(u, 'ingestion')
    r = db.get(IngestionRun, run_id)
    if not r:
        raise HTTPException(404)
    return _run_out(r, full=True)


@app.get('/api/files/{scheme}/{path:path}')
def source_file(scheme: str, path: str, download: int = 0, u: User = Depends(current_user), db: Session = Depends(get_db)):
    run = wf.current_run(db)
    if not run:
        raise HTTPException(404)
    q = select(SourceFile).where(SourceFile.run_id == run.id, SourceFile.rel_path == path)
    q = q.where(SourceFile.scheme.in_([scheme, 'shared']))
    f = db.execute(q).scalars().first()
    if f and not access.can_open_file(u, f.page):
        raise HTTPException(403, 'This file is not used on any page your role can open.')
    if not f or not os.path.isfile(f.storage_path) or not str(Path(f.storage_path).resolve()).startswith(str(Path(run.workspace).resolve())):
        raise HTTPException(404, 'File not found in the current run')
    media = {'pdf': 'application/pdf', 'csv': 'text/csv', 'xml': 'application/xml', 'json': 'application/json', 'mt940': 'text/plain',
             'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'xls': 'application/vnd.ms-excel'}.get(f.format, 'application/octet-stream')
    disp = 'attachment' if download or f.format not in ('pdf', 'csv', 'mt940', 'xml') else 'inline'
    return FileResponse(f.storage_path, media_type=media, filename=os.path.basename(f.rel_path), content_disposition_type=disp)


# ------------------------------------------------------------------ generated reports
def _report_run(rid, db, u):
    need_page(u, 'reports')
    rr = db.get(ReportRun, rid)
    if not rr or rr.kind != 'regulator':
        raise HTTPException(404, 'Report not found')
    p, err = rep.stored_file(rr)
    if not p:
        raise HTTPException(409 if 'hash' in err else 404, err)
    return rr, p


@app.get('/api/reports/{rid}/file')
def report_file(rid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    rr, p = _report_run(rid, db, u)
    wf.audit(db, u.full_name, u.role, rr.scheme, 'REPORT_DOWNLOADED', f"{rr.file_name} · SHA-256 {rr.file_sha256[:16]}")
    db.commit()
    return FileResponse(p, media_type=rep.XLSX, filename=rr.file_name, content_disposition_type='attachment')


@app.get('/api/reports/{rid}/preview')
def report_preview(rid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    rr, p = _report_run(rid, db, u)
    return dict(id=rr.id, file=rr.file_name, sha=rr.file_sha256, size=rr.file_size, check=rr.check_status, checks=rr.check_detail, sheets=rep.preview(p))


# ------------------------------------------------------------------ exports
class _NumWriter:
    """writes Decimals in plain notation without trailing zeros (0E-8 -> 0, 54.95310000 -> 54.9531)"""
    def __init__(self, w):
        self.w = w

    def writerow(self, row):
        self.w.writerow([(format(v.normalize(), 'f') if isinstance(v, Decimal) else v) for v in row])


@app.get('/api/export/{scheme}/{kind}.csv')
def export_csv(scheme: str, kind: str, u: User = Depends(current_user), db: Session = Depends(get_db)):
    need_page(u, {'journals': 'ledger', 'trial-balance': 'ledger', 'capital-accounts': 'capital', 'bank': 'bank', 'rules': 'ingestion'}.get(kind, 'admin'))
    run = wf.current_run(db)
    if not run:
        raise HTTPException(404)
    buf = io.StringIO()
    w = _NumWriter(csv.writer(buf))
    if kind == 'journals':
        w.writerow(['journal_no', 'date', 'kind', 'ref', 'description', 'gl', 'amount', 'investor', 'instrument', 'txn_ccy', 'txn_amount', 'fx_rate', 'source', 'bank_line', 'tally_voucher'])
        for j in db.execute(select(Journal).where(Journal.run_id == run.id, Journal.scheme == scheme).order_by(Journal.id)).scalars():
            for l in j.lines:
                w.writerow([j.journal_no, j.date, j.kind, j.ref, j.description, l.gl, l.amount, l.investor or '', l.instrument or '', l.txn_ccy or '', l.txn_amount or '', l.fx_rate or '',
                            j.source, j.bank_loc or '', j.tally_voucher or ''])
    elif kind == 'trial-balance':
        w.writerow(['gl', 'account', 'opening', 'movement', 'closing'])
        for t in db.execute(select(TrialBalanceLine).where(TrialBalanceLine.run_id == run.id, TrialBalanceLine.scheme == scheme).order_by(TrialBalanceLine.gl)).scalars():
            w.writerow([t.gl, t.account, t.opening, t.movement, t.closing])
    elif kind == 'capital-accounts':
        w.writerow(['investor', 'class', 'opening', 'contributions', 'distributions', 'income', 'fee', 'expense', 'fair_value', 'fx', 'closing', 'units', 'nav_per_unit'])
        for c in db.execute(select(CapitalAccount).where(CapitalAccount.run_id == run.id, CapitalAccount.scheme == scheme).order_by(CapitalAccount.investor)).scalars():
            w.writerow([c.investor, c.unit_class, c.opening, c.contributions, c.distributions, c.income, c.fee, c.expense, c.fair_value, c.fx, c.closing, c.units, c.nav_per_unit])
    elif kind == 'bank':
        w.writerow(['seq', 'date', 'narration', 'ref', 'amount', 'balance', 'journal_no', 'source'])
        for b in db.execute(select(BankLine).where(BankLine.run_id == run.id, BankLine.scheme == scheme).order_by(BankLine.seq)).scalars():
            w.writerow([b.seq, b.date, b.narration, b.ref, b.amount, b.balance, b.journal_no or '', b.source_loc or ''])
    elif kind == 'rules':
        # as shown on screen: the ingestion result plus workflow results (R15 after the regulator workbook is generated)
        w.writerow(['rule', 'status', 'title', 'left', 'right', 'detail', 'src'])
        sv = wf.apply_overrides(run.dashboard, wf.state(db, run))['schemes'].get(scheme)
        if not sv:
            raise HTTPException(404, 'Unknown scheme')
        for r in sv['rules']:
            w.writerow([r['rule'], r['status'], r['title'], r['left'], r['right'], r['detail'], r['src']])
    else:
        raise HTTPException(404, 'Unknown export')
    name = f"{scheme}_{run.period_code}_{kind}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type='text/csv', headers={'Content-Disposition': f'attachment; filename="{name}"'})


# ------------------------------------------------------------------ admin
class UserIn(BaseModel):
    username: str
    full_name: str
    role: str
    password: str
    is_admin: bool = False          # kept for older clients: true means role ADMIN


class UserPatch(BaseModel):
    full_name: str | None = None
    role: str | None = None
    active: bool | None = None
    is_admin: bool | None = None
    password: str | None = None


@app.get('/api/admin/users')
def list_users(a: User = Depends(admin_user), db: Session = Depends(get_db)):
    return [_user_out(u, with_access=False) for u in db.execute(select(User).order_by(User.id)).scalars()]


@app.get('/api/admin/access')
def access_matrix(a: User = Depends(admin_user)):
    return access.matrix()


def _active_admins(db):
    return db.execute(select(User).where(User.is_admin == True, User.active == True)).scalars().all()  # noqa: E712


@app.post('/api/admin/users')
def create_user(body: UserIn, a: User = Depends(admin_user), db: Session = Depends(get_db)):
    role = 'ADMIN' if body.is_admin else body.role
    if role not in wf.ROLE_LABELS:
        raise HTTPException(400, f"role must be one of {list(wf.ROLE_LABELS)}")
    name = body.username.strip().lower()
    if not name or not name.replace('.', '').replace('-', '').replace('_', '').isalnum():
        raise HTTPException(400, 'Username: letters, digits, dot, dash or underscore')
    if not body.full_name.strip():
        raise HTTPException(400, 'Full name is required')
    if len(body.password) < 10:
        raise HTTPException(400, 'Use at least 10 characters')
    if db.execute(select(User).where(User.username == name)).scalar_one_or_none():
        raise HTTPException(409, 'Username exists')
    u = User(username=name, full_name=body.full_name.strip(), role=role, is_admin=role == 'ADMIN', password_hash=hash_password(body.password))
    db.add(u)
    wf.audit(db, a.full_name, 'ADMIN', 'all', 'USER_CREATED', f"{u.username} ({wf.ROLE_LABELS[role]})")
    db.commit()
    return _user_out(u, with_access=False)


@app.patch('/api/admin/users/{uid}')
def patch_user(uid: int, body: UserPatch, a: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    role = 'ADMIN' if body.is_admin else body.role
    if body.is_admin is False and body.role is None and u.is_admin:
        raise HTTPException(400, 'Choose the role this user gets instead of Administrator')
    changes = []
    if role is not None and role != u.role:
        if role not in wf.ROLE_LABELS:
            raise HTTPException(400, 'unknown role')
        if u.is_admin and role != 'ADMIN' and len([x for x in _active_admins(db) if x.id != u.id]) == 0:
            raise HTTPException(409, 'This is the last active administrator. Make someone else an administrator first.')
        changes.append(f"role {wf.ROLE_LABELS.get(u.role, u.role)} -> {wf.ROLE_LABELS[role]}")
        u.role, u.is_admin = role, role == 'ADMIN'
    if body.active is not None and body.active != u.active:
        if not body.active and u.id == a.id:
            raise HTTPException(409, 'You cannot deactivate your own account.')
        if not body.active and u.is_admin and len([x for x in _active_admins(db) if x.id != u.id]) == 0:
            raise HTTPException(409, 'This is the last active administrator.')
        u.active = body.active
        changes.append('activated' if body.active else 'deactivated')
    if body.full_name is not None and body.full_name.strip() and body.full_name.strip() != u.full_name:
        u.full_name = body.full_name.strip()
        changes.append('name changed')
    if body.password:
        if len(body.password) < 10:
            raise HTTPException(400, 'Use at least 10 characters')
        u.password_hash = hash_password(body.password)          # also signs the user out everywhere (the session carries a password fingerprint)
        changes.append('password reset')
    if changes:
        wf.audit(db, a.full_name, 'ADMIN', 'all', 'USER_UPDATED', f"{u.username}: {', '.join(changes)}")
    db.commit()
    return _user_out(u, with_access=False)


class DeleteIn(BaseModel):
    scheme: str
    files: list[str]


@app.get('/api/admin/files')
def admin_files(a: User = Depends(admin_user), db: Session = Depends(get_db)):
    """the current quarter's files with whether each can be deleted"""
    run = wf.current_run(db)
    if not run:
        return []
    locked = {s: wf.is_locked(db, s, v['meta']['period']['code']) for s, v in (run.dashboard or {}).get('schemes', {}).items()}
    out = deletable(db, run)
    for x in out:
        x['locked'] = bool(locked.get(x['scheme']))
        if not x['refused'] and locked.get(x['scheme']):
            x['refused'] = 'The quarter is locked (NAV approved).'
    return out


@app.post('/api/admin/files/delete')
def admin_delete_files(body: DeleteIn, a: User = Depends(admin_user), db: Session = Depends(get_db)):
    try:
        run = delete_files(db, a, body.scheme.strip().upper(), body.files)
    except DeleteRefused as e:
        raise HTTPException(409, str(e))
    return _run_out(run, full=True)


class DeleteAllIn(BaseModel):
    confirm: str


@app.post('/api/admin/files/delete-all')
def admin_delete_all(body: DeleteAllIn, a: User = Depends(admin_user), db: Session = Depends(get_db)):
    """every source file of the current quarter, all schemes: nothing is loaded until the next upload"""
    if body.confirm != 'DELETE ALL':
        raise HTTPException(400, 'Send confirm: "DELETE ALL" to delete every file.')
    try:
        run = delete_all(db, a)
    except DeleteRefused as e:
        raise HTTPException(409, str(e))
    return _run_out(run, full=True)


@app.get('/api/admin/profile')
def get_profile(a: User = Depends(admin_user), db: Session = Depends(get_db)):
    s = db.get(Setting, 'org_profile')
    return s.value if s else {}


@app.put('/api/admin/profile')
def put_profile(body: dict, a: User = Depends(admin_user), db: Session = Depends(get_db)):
    s = db.get(Setting, 'org_profile') or Setting(key='org_profile', value={})
    s.value, s.updated_by = body, a.full_name
    db.add(s)
    wf.audit(db, a.full_name, 'ADMIN', 'all', 'PROFILE_UPDATED', 'organisation profile (applies from the next ingestion)')
    db.commit()
    return s.value


@app.get('/api/health')
def health(db: Session = Depends(get_db)):
    run = wf.current_run(db)
    return {'ok': True, 'version': __version__, 'current_run': run.id if run else None}


# ------------------------------------------------------------------ front end
@app.get('/', response_class=HTMLResponse)
def index():
    return FileResponse(STATIC / 'index.html', media_type='text/html')
