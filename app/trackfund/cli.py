"""Operator commands.

    python -m trackfund.cli init                          create tables, profile and users
    python -m trackfund.cli load <zip or folder> [--as pallav] [--mode replace|merge] [--scheme A]
    python -m trackfund.cli set-password <username>       prompts for a new password
    python -m trackfund.cli runs                          list ingestion runs
"""
import os
import sys
import shutil
import getpass
import argparse
import tempfile

from sqlalchemy import select

from .bootstrap import init_db
from .db import session_scope
from .models import User, IngestionRun
from .security import hash_password
from .services.ingest import ingest


def main(argv=None):
    p = argparse.ArgumentParser(prog='trackfund')
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('init')
    l = sub.add_parser('load')
    l.add_argument('path')
    l.add_argument('--as', dest='user', default='pallav')
    l.add_argument('--mode', default='auto')
    l.add_argument('--scheme', default=None)
    s = sub.add_parser('set-password')
    s.add_argument('username')
    sub.add_parser('runs')
    a = p.parse_args(argv)
    init_db()
    if a.cmd == 'init':
        print('Database ready.')
    elif a.cmd == 'load':
        with session_scope() as db:
            u = db.execute(select(User).where(User.username == a.user)).scalar_one()
            path = os.path.abspath(a.path)
            if os.path.isdir(path):
                tmp = tempfile.mkdtemp()
                z = shutil.make_archive(os.path.join(tmp, 'upload'), 'zip', path)
                uploads = [('upload.zip', z)]
            else:
                uploads = [(os.path.basename(path), path)]
            run = ingest(db, u, uploads, mode=a.mode, scheme_hint=a.scheme)
            for kind, line in run.log or []:
                print(f"  [{kind}] {line}")
            print(f"run {run.id}: {run.status}" + (f" - {run.error}" if run.error else ''))
            if run.status != 'succeeded':
                sys.exit(1)
    elif a.cmd == 'set-password':
        pw = getpass.getpass('New password: ')
        if len(pw) < 10:
            sys.exit('Use at least 10 characters')
        with session_scope() as db:
            u = db.execute(select(User).where(User.username == a.username)).scalar_one()
            u.password_hash = hash_password(pw)
        print('Password changed.')
    elif a.cmd == 'runs':
        with session_scope() as db:
            for r in db.execute(select(IngestionRun).order_by(IngestionRun.id)).scalars():
                print(r.id, r.created_at, r.status, 'current' if r.is_current else '', r.period_code or '', r.error or '')


if __name__ == '__main__':
    main()
