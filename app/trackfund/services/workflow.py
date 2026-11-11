"""Workflow actions (maker-checker NAV, period lock, approvals, obligations, STR, reports) and the audit chain.

Every action checks the user's role on the server and writes one append-only, hash-chained audit event.
"""
import hashlib
import threading
from datetime import datetime, date

from sqlalchemy import select, func, text

from ..models import (AuditEvent, NavVersion, ObligationUpdate, StrCase, Approval, ReportRun, IngestionRun, User)
from .. import access
from . import reports

ROLE_LABELS = access.ROLE_LABELS
ROLE_ORDER = [r for r in ROLE_LABELS if r != 'ADMIN'] + ['ADMIN']


class Forbidden(Exception):
    pass


class Conflict(Exception):
    pass


_lock = threading.Lock()


def _hash(prev, ts, user, role, scheme, action, obj):
    return hashlib.sha256(f"{prev}|{ts.isoformat()}|{user}|{role}|{scheme}|{action}|{obj}".encode()).hexdigest()


def audit(db, user_name, role, scheme, action, obj):
    with _lock:
        if db.bind.dialect.name == 'postgresql':
            db.execute(text('SELECT pg_advisory_xact_lock(424242)'))
        last = db.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()
        prev = last.hash if last else '0' * 64
        ts = datetime.utcnow().replace(microsecond=0)
        e = AuditEvent(ts=ts, user=user_name, role=role, scheme=scheme, action=action, obj=obj, prev_hash=prev, hash=_hash(prev, ts, user_name, role, scheme, action, obj))
        db.add(e)
        db.flush()
        return e


def verify_chain(db):
    prev = '0' * 64
    n = 0
    for e in db.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars():
        if e.prev_hash != prev or e.hash != _hash(e.prev_hash, e.ts, e.user, e.role, e.scheme, e.action, e.obj):
            return False, n, e.seq
        prev = e.hash
        n += 1
    return True, n, None


def current_run(db):
    return db.execute(select(IngestionRun).where(IngestionRun.is_current == True)).scalar_one_or_none()  # noqa: E712


def latest_nav(db, scheme, period):
    return db.execute(select(NavVersion).where(NavVersion.scheme == scheme, NavVersion.period_code == period, NavVersion.status != 'superseded')
                      .order_by(NavVersion.version.desc()).limit(1)).scalar_one_or_none()


def is_locked(db, scheme, period):
    return db.execute(select(func.count()).select_from(NavVersion).where(NavVersion.scheme == scheme, NavVersion.period_code == period,
                                                                      NavVersion.status == 'locked')).scalar() > 0


def state(db, run):
    """workflow state in the shape the dashboard keeps in `st`"""
    data = run.dashboard if run else None
    schemes = list((data or {}).get('schemes', {}).keys())
    st = dict(nav={}, navv={}, reports=[], str=[], appr={}, mapOk={}, valOk={}, notice={}, obl={}, audit=[], regrep={})
    locked = {}
    for s in schemes:
        per = data['schemes'][s]['meta']['period']['code']
        nv = latest_nav(db, s, per)
        if nv and nv.status == 'locked':
            locked[s] = (per, nv)
        st['nav'][s] = nv.status if nv else 'draft'
        st['navv'][s] = dict(version=nv.version if nv else 1, submitted_by=nv.submitted_by if nv else None, approved_by=nv.approved_by if nv else None,
                             approved_at=nv.approved_at.isoformat() if nv and nv.approved_at else None)
        st['appr'][s] = {}
        st['valOk'][s] = False
    for a in db.execute(select(Approval).order_by(Approval.id)).scalars():
        if a.kind == 'bank_detail':
            st['appr'].setdefault(a.scheme, {})['bank'] = a.value
        elif a.kind == 'valuation':
            st['valOk'][a.scheme] = a.value
        elif a.kind == 'mapping':
            st['mapOk'][a.key] = a.by
        elif a.kind == 'breach_notice':
            st['notice'][a.key] = True
    navv = {n.id: n.version for n in db.execute(select(NavVersion)).scalars()}
    for r in db.execute(select(ReportRun).order_by(ReportRun.id)).scalars():
        st['reports'] = [x for x in st['reports'] if not (x['n'] == r.name and x['s'] == r.scheme)]
        x = dict(id=r.id, n=r.name, s=r.scheme, by=r.by, h=r.hash[:16], nav=r.nav_status, at=r.at.isoformat(), kind=r.kind or 'preview', per=r.period_code,
                 nav_v=navv.get(r.nav_version_id), file=r.file_name, sha=r.file_sha256, size=r.file_size, check=r.check_status, checks=r.check_detail)
        st['reports'].append(x)
        lk = locked.get(r.scheme)
        if r.kind == 'regulator' and r.file_name and lk and r.period_code == lk[0] and r.nav_version_id == lk[1].id:
            st['regrep'][r.scheme] = x                      # latest workbook generated from the locked NAV of the current period
    for c in db.execute(select(StrCase).order_by(StrCase.id)).scalars():
        st['str'].append(dict(id=c.id, ref=c.ref, by=c.created_by, stage=c.stage, s=c.scheme))
    for o in db.execute(select(ObligationUpdate).order_by(ObligationUpdate.id)).scalars():
        st['obl'][f"{o.scheme}|{o.ref}"] = dict(status=o.status, done=o.done.isoformat() if o.done else None, by=o.by)
    for e in db.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars():
        st['audit'].append(dict(seq=e.seq, ts=e.ts.strftime('%Y-%m-%d %H:%M'), user=e.user, role=e.role, sch=e.scheme, action=e.action, obj=e.obj, p=e.prev_hash[:16], h=e.hash[:16]))
    return st


def apply_overrides(data, st):
    """
    Workflow results applied on top of the stored ingestion output (which is never modified):
    obligation status changes recorded in the app, and rule R15 once the regulator workbook is generated and read back.
    """
    if not data:
        return data
    out = dict(data, schemes={})
    for s, v in data.get('schemes', {}).items():
        v = dict(v)
        obl = []
        for b in v['obligations']:
            o = st['obl'].get(f"{s}|{b['ref']}")
            obl.append(dict(b, status=o['status'], done=o['done']) if o else b)
        v['obligations'] = obl
        rr = st.get('regrep', {}).get(s)
        if rr:
            v['rules'] = [reports.r15_override(r, rr, v) if r['rule'] == 'R15' and r['status'] == 'PARTIAL' else r for r in v['rules']]
        out['schemes'][s] = v
    return out


def act(db, user: User, action: str, scheme: str, arg: str | None, clock: str | None):
    """Run one action. Returns a message for the user. Raises Forbidden / Conflict."""
    if action not in access.ACTIONS or action in ('gen_regulator', 'upload', 'delete_files', 'manage_users'):
        raise Conflict(f"Unknown action {action}")
    if not access.can(user, action):
        raise Forbidden(f"{ROLE_LABELS.get(access.role_of(user), user.role)} cannot do this. Allowed: " + ', '.join(access.who_can(action)) + '.')
    run = current_run(db)
    if run is None and action not in ('verify',):
        raise Conflict('No data loaded yet. Upload a quarter first.')
    data = run.dashboard if run else {}
    if scheme and scheme not in data.get('schemes', {}) and action != 'verify':
        raise Conflict(f"Unknown scheme {scheme}")
    sv = data['schemes'][scheme] if scheme in data.get('schemes', {}) else None
    per = sv['meta']['period']['code'] if sv else ''
    plabel = sv['meta']['period']['label'] if sv else ''
    who = user.full_name
    A = lambda a, o: audit(db, who, access.role_of(user), scheme or 'all', a, o)

    if action == 'navsubmit':
        nv = latest_nav(db, scheme, per)
        if nv is None or nv.status != 'draft':
            raise Conflict(f"NAV is {nv.status if nv else 'missing'}; only a draft can be submitted.")
        fails = [r for r in sv['rules'] if r['status'] == 'FAIL']
        if fails:
            raise Conflict(f"{len(fails)} reconciliation check(s) fail; fix the source files and re-run ingestion before submitting.")
        nv.status, nv.submitted_by, nv.submitted_at = 'submitted', who, datetime.utcnow()
        A('NAV_SUBMITTED', f"NAV v{nv.version} {plabel} {sv['nav_close']:.4f}")
        return f"NAV v{nv.version} submitted. Sign in as the finance checker to approve."
    if action == 'navlock':
        nv = latest_nav(db, scheme, per)
        if nv is None or nv.status != 'submitted':
            raise Conflict('Only a submitted NAV can be approved.')
        if nv.submitted_by == who:
            raise Forbidden('The person who submitted the NAV cannot approve it.')
        nv.status, nv.approved_by, nv.approved_at = 'locked', who, datetime.utcnow()
        A('NAV_APPROVED_PERIOD_LOCKED', plabel)
        return f"NAV v{nv.version} approved. {plabel} is locked."
    if action == 'valok':
        db.add(Approval(kind='valuation', scheme=scheme, key=sv['meta']['val_dates']['report'] or per, by=who))
        A('VALUATION_APPROVED', f"{sv['meta']['period']['end']} cycle")
        return 'Valuation approved.'
    if action == 'trypost':
        if is_locked(db, scheme, per):
            A('POST_REFUSED', f"Back-dated journal into {plabel}")
            return f"Refused. {plabel} is locked. Post this as a dated adjustment in the next quarter."
        return f"Allowed, because {plabel} is still open. Lock the NAV and try again."
    if action == 'apprbank':
        inv = sv['investors'][1]['id'] if len(sv['investors']) > 1 else sv['investors'][0]['id']
        db.add(Approval(kind='bank_detail', scheme=scheme, key=inv, by=who))
        A('BANK_DETAIL_APPROVED', f"{inv} · 48-hour hold")
        return 'Approved. Payments to the new account are held for 48 hours.'
    if action == 'gen':
        nv = latest_nav(db, scheme, per)
        if reports.is_regulator(sv, arg):
            if not access.can(user, 'gen_regulator'):
                raise Forbidden(f"{ROLE_LABELS.get(access.role_of(user), user.role)} cannot generate a regulator filing. Allowed: "
                                + ', '.join(access.who_can('gen_regulator')) + '.')
            if nv is None or nv.status != 'locked':
                raise Conflict(f"The {arg} is generated only from a locked NAV. NAV v{nv.version if nv else 1} is {nv.status if nv else 'draft'}: "
                               "submit it and have the checker approve it first.")
            rr = reports.generate(db, run, sv, scheme, nv, who)
            A('REPORT_GENERATED', f"{arg} · {rr.file_name} · SHA-256 {rr.file_sha256[:16]} · from NAV v{nv.version} · read-back {rr.check_status}")
            if rr.check_status != 'PASS':
                bad = [c[0] for c in rr.check_detail if not c[3]]
                return f"{rr.file_name} generated, but the read-back does not tie to the books: {', '.join(bad)}. Do not file it."
            return f"{rr.file_name} generated from NAV v{nv.version} and read back: every figure ties to the closing books."
        h = hashlib.sha256(f"{arg}|{scheme}|{per}|{nv.version if nv else 0}|{nv.status if nv else 'draft'}|{run.id}".encode()).hexdigest()
        db.add(ReportRun(scheme=scheme, name=arg, nav_version_id=nv.id if nv else None, nav_status=nv.status if nv else 'draft', by=who, hash=h,
                         kind='preview', run_id=run.id, period_code=per))
        A('REPORT_GENERATED', arg)
        return f"{arg} generated from NAV v{nv.version if nv else 1} and logged."
    if action == 'notice':
        db.add(Approval(kind='breach_notice', scheme=scheme, key=arg, by=who))
        A('BREACH_NOTICE_GENERATED', arg)
        return 'Breach notice generated.'
    if action == 'obl':
        ob = next((b for b in sv['obligations'] if b['ref'] == arg), None)
        if not ob:
            raise Conflict(f"Unknown obligation {arg}")
        owner = access.OWNER_ROLE.get(ob.get('owner'), ob.get('owner'))
        if not user.is_admin and user.role != 'PO' and user.role != owner:
            raise Forbidden(f"{arg} is owned by {ROLE_LABELS.get(owner, owner)}. Only the owner, the Principal Officer or an administrator can mark it filed.")
        d = date.fromisoformat(clock) if clock else date.today()
        db.add(ObligationUpdate(scheme=scheme, ref=arg, status='Filed', done=d, by=who))
        A('OBLIGATION_FILED', f"{arg} {ob['title']}")
        return 'Marked as filed.'
    if action == 'ack':
        db.add(Approval(kind='exception_ack', scheme=scheme, key=arg or '', by=who))
        A('EXCEPTION_ACKNOWLEDGED', arg or '')
        return 'Acknowledged and assigned. Logged in the audit trail.'
    if action == 'str':
        n = db.execute(select(func.count()).select_from(StrCase)).scalar() + 1
        ref = f"STR-{date.today().year}-{n:03d}"
        db.add(StrCase(ref=ref, scheme=scheme, stage='Created', created_by=who))
        A('STR_CREATED', ref)
        return f"{ref} created."
    if action == 'strnext':
        c = db.get(StrCase, int(arg))
        if not c:
            raise Conflict('Unknown STR')
        nxt = {'Created': 'Under review', 'Under review': 'Closed'}.get(c.stage)
        if not nxt:
            raise Conflict('This STR is already closed.')
        c.stage = nxt
        A('STR_' + nxt.upper().replace(' ', '_'), c.ref)
        return f"{c.ref}: {nxt}."
    if action == 'mapok':
        db.add(Approval(kind='mapping', scheme=scheme, key=arg, by=who))
        A('MAPPING_ACCEPTED', arg)
        return 'Mapping accepted and remembered for this sender.'
    if action == 'verify':
        ok, n, bad = verify_chain(db)
        return f"Chain verified: {n} events, no breaks." if ok else f"Chain broken at event {bad}."
    raise Conflict(f"Unhandled action {action}")
