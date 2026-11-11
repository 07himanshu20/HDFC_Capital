from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import DATABASE_URL

_kw = {}
if DATABASE_URL.startswith('sqlite'):
    _kw['connect_args'] = {'check_same_thread': False}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, **_kw)

if DATABASE_URL.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def _fk_on(conn, _):
        cur = conn.cursor()
        cur.execute('PRAGMA foreign_keys=ON')
        cur.execute('PRAGMA journal_mode=WAL')
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
