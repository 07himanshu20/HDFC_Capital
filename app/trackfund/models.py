"""Database schema.

Three layers:
  1. intake      uploads, ingestion_runs, source_files      (what arrived, its hash, its document type)
  2. books       journals, journal_lines, bank_lines, trial_balance_lines, capital_accounts, rule_results
                 (normalised output of the books engine, one set per ingestion run; queryable and exportable)
  3. workflow    nav_versions, obligation_updates, str_cases, approvals, report_runs, audit_events, users, settings

The dashboard view model of each run is also stored (ingestion_runs.dashboard) so pages load in one read.
"""
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import String, Integer, Text, Date, DateTime, Boolean, ForeignKey, Numeric, JSON, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

AMT = Numeric(24, 8)


def now():
    return datetime.utcnow()


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(40))            # PO, CRO, FIN_MAKER, FIN_CHECKER, AML_PO, IR, INV_TEAM, TRUSTEE_RO, AUDITOR_RO
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Setting(Base):
    __tablename__ = 'settings'
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    updated_by: Mapped[str | None] = mapped_column(String(160), nullable=True)


# ------------------------------------------------------------------ intake
class Upload(Base):
    __tablename__ = 'uploads'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    uploaded_by: Mapped[str] = mapped_column(String(160))
    original_names: Mapped[list] = mapped_column(JSON)
    mode: Mapped[str] = mapped_column(String(20))          # replace | merge
    scheme_hint: Mapped[str | None] = mapped_column(String(10), nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    bytes: Mapped[int] = mapped_column(Integer, default=0)


class IngestionRun(Base):
    __tablename__ = 'ingestion_runs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upload_id: Mapped[int | None] = mapped_column(ForeignKey('uploads.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default='running')   # running | succeeded | failed | superseded
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    workspace: Mapped[str] = mapped_column(String(500))
    period_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    log: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dashboard: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    files: Mapped[list['SourceFile']] = relationship(back_populates='run', cascade='all, delete-orphan')


class SourceFile(Base):
    __tablename__ = 'source_files'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('ingestion_runs.id', ondelete='CASCADE'), index=True)
    scheme: Mapped[str] = mapped_column(String(10))
    rel_path: Mapped[str] = mapped_column(String(500))
    storage_path: Mapped[str] = mapped_column(String(800))
    doc_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    format: Mapped[str] = mapped_column(String(10))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    feeds: Mapped[list] = mapped_column(JSON, default=list)
    who: Mapped[str | None] = mapped_column(String(200), nullable=True)
    page: Mapped[str | None] = mapped_column(String(200), nullable=True)
    run: Mapped[IngestionRun] = relationship(back_populates='files')
    __table_args__ = (UniqueConstraint('run_id', 'scheme', 'rel_path'),)


# ------------------------------------------------------------------ books (one set per run and scheme)
class Journal(Base):
    __tablename__ = 'journals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('ingestion_runs.id', ondelete='CASCADE'), index=True)
    scheme: Mapped[str] = mapped_column(String(10))
    period_code: Mapped[str] = mapped_column(String(20))
    journal_no: Mapped[str] = mapped_column(String(40))
    date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(20))
    ref: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(300))
    bank_loc: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tally_voucher: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lines: Mapped[list['JournalLine']] = relationship(back_populates='journal', cascade='all, delete-orphan')
    __table_args__ = (Index('ix_journal_run_scheme', 'run_id', 'scheme'),)


class JournalLine(Base):
    __tablename__ = 'journal_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey('journals.id', ondelete='CASCADE'), index=True)
    gl: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(AMT)          # scheme unit (USD m / INR cr); debit positive
    investor: Mapped[str | None] = mapped_column(String(20), nullable=True)
    instrument: Mapped[str | None] = mapped_column(String(20), nullable=True)
    txn_ccy: Mapped[str | None] = mapped_column(String(3), nullable=True)
    txn_amount: Mapped[Decimal | None] = mapped_column(AMT, nullable=True)
    fx_rate: Mapped[Decimal | None] = mapped_column(AMT, nullable=True)
    journal: Mapped[Journal] = relationship(back_populates='lines')


class BankLine(Base):
    __tablename__ = 'bank_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('ingestion_runs.id', ondelete='CASCADE'), index=True)
    scheme: Mapped[str] = mapped_column(String(10))
    seq: Mapped[int] = mapped_column(Integer)
    date: Mapped[date] = mapped_column(Date)
    narration: Mapped[str] = mapped_column(Text)
    ref: Mapped[str] = mapped_column(String(80))
    amount: Mapped[Decimal] = mapped_column(AMT)          # statement currency, full units
    balance: Mapped[Decimal] = mapped_column(AMT)
    journal_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_loc: Mapped[str | None] = mapped_column(String(60), nullable=True)


class TrialBalanceLine(Base):
    __tablename__ = 'trial_balance_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('ingestion_runs.id', ondelete='CASCADE'), index=True)
    scheme: Mapped[str] = mapped_column(String(10))
    gl: Mapped[int] = mapped_column(Integer)
    account: Mapped[str] = mapped_column(String(120))
    opening: Mapped[Decimal] = mapped_column(AMT)
    movement: Mapped[Decimal] = mapped_column(AMT)
    closing: Mapped[Decimal] = mapped_column(AMT)


class CapitalAccount(Base):
    __tablename__ = 'capital_accounts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('ingestion_runs.id', ondelete='CASCADE'), index=True)
    scheme: Mapped[str] = mapped_column(String(10))
    investor: Mapped[str] = mapped_column(String(20))
    unit_class: Mapped[str] = mapped_column(String(5))
    opening: Mapped[Decimal] = mapped_column(AMT)
    contributions: Mapped[Decimal] = mapped_column(AMT)
    distributions: Mapped[Decimal] = mapped_column(AMT)
    income: Mapped[Decimal] = mapped_column(AMT)
    fee: Mapped[Decimal] = mapped_column(AMT)
    expense: Mapped[Decimal] = mapped_column(AMT)
    fair_value: Mapped[Decimal] = mapped_column(AMT)
    fx: Mapped[Decimal] = mapped_column(AMT)
    closing: Mapped[Decimal] = mapped_column(AMT)
    units: Mapped[int] = mapped_column(Integer)
    nav_per_unit: Mapped[Decimal] = mapped_column(AMT)


class RuleResult(Base):
    __tablename__ = 'rule_results'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('ingestion_runs.id', ondelete='CASCADE'), index=True)
    scheme: Mapped[str] = mapped_column(String(10))
    rule: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10))
    left: Mapped[str] = mapped_column(Text)
    right: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    src: Mapped[str] = mapped_column(Text)


# ------------------------------------------------------------------ workflow
class NavVersion(Base):
    __tablename__ = 'nav_versions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme: Mapped[str] = mapped_column(String(10))
    period_code: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[int] = mapped_column(ForeignKey('ingestion_runs.id'))
    nav: Mapped[Decimal] = mapped_column(AMT)
    status: Mapped[str] = mapped_column(String(20), default='draft')    # draft | submitted | locked | superseded
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    submitted_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint('scheme', 'period_code', 'version'),)


class ObligationUpdate(Base):
    __tablename__ = 'obligation_updates'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme: Mapped[str] = mapped_column(String(10))
    ref: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    done: Mapped[date | None] = mapped_column(Date, nullable=True)
    by: Mapped[str] = mapped_column(String(160))
    at: Mapped[datetime] = mapped_column(DateTime, default=now)


class StrCase(Base):
    __tablename__ = 'str_cases'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ref: Mapped[str] = mapped_column(String(40), unique=True)
    scheme: Mapped[str] = mapped_column(String(10))
    stage: Mapped[str] = mapped_column(String(20))      # Created | Under review | Closed
    created_by: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Approval(Base):
    """Generic sign-offs: kind in {bank_detail, valuation, mapping, breach_notice, exception_ack}."""
    __tablename__ = 'approvals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    scheme: Mapped[str] = mapped_column(String(10))
    key: Mapped[str] = mapped_column(String(300))
    by: Mapped[str] = mapped_column(String(160))
    at: Mapped[datetime] = mapped_column(DateTime, default=now)
    value: Mapped[bool] = mapped_column(Boolean, default=True)


class ReportRun(Base):
    """One generation of a report.  Regulator reports are written to a file (file_*) and read back against the closing books (check_*)."""
    __tablename__ = 'report_runs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(200))
    nav_version_id: Mapped[int | None] = mapped_column(ForeignKey('nav_versions.id'), nullable=True)
    nav_status: Mapped[str] = mapped_column(String(20))
    by: Mapped[str] = mapped_column(String(160))
    at: Mapped[datetime] = mapped_column(DateTime, default=now)
    hash: Mapped[str] = mapped_column(String(64))
    # added with regulator report files; nullable so existing databases are extended in place (bootstrap.add_missing_columns)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(20), nullable=True)            # 'regulator' (file) or 'preview'
    file_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    check_status: Mapped[str | None] = mapped_column(String(10), nullable=True)    # PASS / FAIL
    check_detail: Mapped[list | None] = mapped_column(JSON, nullable=True)


class AuditEvent(Base):
    """Append-only, hash-chained: hash = sha256(prev_hash | ts | user | role | scheme | action | obj)."""
    __tablename__ = 'audit_events'
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now)
    user: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(40))
    scheme: Mapped[str] = mapped_column(String(10))
    action: Mapped[str] = mapped_column(String(60))
    obj: Mapped[str] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
