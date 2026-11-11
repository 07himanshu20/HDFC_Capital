"""First-start setup: tables, organisation profile, initial users."""
import os
import json
import secrets
import logging

from sqlalchemy import select, func, inspect, text

from .db import Base, engine, session_scope
from .models import User, Setting
from .security import hash_password
from .config import SEED_PROFILE, DATA_DIR, BASE_DIR

log = logging.getLogger('trackfund')


def add_missing_columns():
    """Columns added to an existing table in a later version are created in place (all such columns are nullable)."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for t in Base.metadata.sorted_tables:
            if not insp.has_table(t.name):
                continue
            have = {c['name'] for c in insp.get_columns(t.name)}
            for c in t.columns:
                if c.name not in have and c.nullable:
                    conn.execute(text(f'ALTER TABLE {t.name} ADD COLUMN {c.name} {c.type.compile(dialect=engine.dialect)}'))
                    log.warning('Added column %s.%s', t.name, c.name)


def admin_is_a_role(db):
    """administrator is a role of its own (it sees and does everything); keep role and flag in step for older databases"""
    for u in db.execute(select(User)).scalars():
        if u.is_admin and u.role != 'ADMIN':
            log.warning('User %s: role %s -> ADMIN (administrator)', u.username, u.role)
            u.role = 'ADMIN'
        elif u.role == 'ADMIN' and not u.is_admin:
            u.is_admin = True


def init_db():
    Base.metadata.create_all(engine)
    add_missing_columns()
    with session_scope() as db:
        admin_is_a_role(db)
    with session_scope() as db:
        if db.get(Setting, 'org_profile') is None:
            prof = json.load(open(SEED_PROFILE)) if SEED_PROFILE.exists() else {}
            prof.pop('_comment', None)
            db.add(Setting(key='org_profile', value=prof, updated_by='seed'))
        if db.execute(select(func.count()).select_from(User)).scalar() == 0:
            seed = json.load(open(BASE_DIR / 'seed' / 'users.json'))['users']
            pw = os.environ.get('TRACKFUND_INITIAL_PASSWORD')
            generated = not pw
            pw = pw or secrets.token_urlsafe(12)
            for u in seed:
                db.add(User(username=u['username'], full_name=u['full_name'], role=u['role'], is_admin=bool(u.get('is_admin')) or u['role'] == 'ADMIN', password_hash=hash_password(pw)))
            if generated:
                p = DATA_DIR / 'initial_credentials.txt'
                p.write_text('Initial password for every seeded user (change it after first sign-in):\n' + pw + '\n\nUsers: ' +
                             ', '.join(f"{u['username']} ({u['role']})" for u in seed) + '\n')
                p.chmod(0o600)
                log.warning('Created %d users. Initial password written to %s', len(seed), p)
