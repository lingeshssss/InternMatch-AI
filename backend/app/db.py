from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import create_engine, String, Text, JSON, DateTime, ForeignKey, UniqueConstraint, Index, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings

def now(): return datetime.now(timezone.utc)
def aware(value):
    """UTC-aware datetime. SQLite returns naive UTC; PostgreSQL returns aware values that must be converted, not relabelled."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
def uid(): return str(uuid4())
class Base(DeclarativeBase): pass
# Pin PostgreSQL sessions to UTC so timestamps and their ISO strings are identical on every host.
engine = create_engine(settings.database_url, pool_pre_ping=True, **({'connect_args': {'options': '-c timezone=UTC'}} if settings.database_url.startswith('postgresql') else {}))
Session = sessionmaker(engine, expire_on_commit=False)

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
class Profile(Base):
    __tablename__ = 'student_profiles'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    # Authenticated encryption protects profile attributes, including voluntary sensitive fields.
    encrypted_data: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1)
class Resume(Base):
    __tablename__ = 'resumes'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    encrypted_document: Mapped[str] = mapped_column(Text)
    encrypted_extraction: Mapped[str] = mapped_column(Text)
    confirmed: Mapped[bool] = mapped_column(default=False)
    # pending | ready | failed. Failed extraction never blocks manual profile entry.
    extraction_status: Mapped[str] = mapped_column(String(20), default='ready')
    extraction_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class Company(Base):
    __tablename__ = 'companies'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(255), unique=True)
class Job(Base):
    __tablename__ = 'job_postings'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey('companies.id'))
    company: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(512), index=True)
    location: Mapped[str | None] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(Text, unique=True)
    source: Mapped[str] = mapped_column(String(100))
    source_key: Mapped[str] = mapped_column(String(200), index=True)
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    extraction_complete: Mapped[bool] = mapped_column(default=False)
    extraction_error: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default='open', index=True)
    # ok | inaccessible. The most recent fetch of this posting's source failed; it cannot be verified.
    access_status: Mapped[str] = mapped_column(String(20), default='ok')
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class Evidence(Base):
    __tablename__ = 'source_evidence'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey('job_postings.id', ondelete='CASCADE'), index=True)
    quote: Mapped[str] = mapped_column(Text)
    start: Mapped[int]
    end: Mapped[int]
    content_hash: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class Requirement(Base):
    __tablename__ = 'job_requirements'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey('job_postings.id', ondelete='CASCADE'), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey('source_evidence.id', ondelete='CASCADE'))
    data: Mapped[dict] = mapped_column(JSON)
class JobSource(Base):
    __tablename__ = 'job_sources'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey('job_postings.id', ondelete='CASCADE'), index=True)
    source: Mapped[str] = mapped_column(String(100))
    source_key: Mapped[str] = mapped_column(String(200))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('job_id', 'source', 'source_key'),)
class Qualification(Base):
    __tablename__ = 'qualifications'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    resume_id: Mapped[str | None] = mapped_column(ForeignKey('resumes.id', ondelete='SET NULL'))
    encrypted_data: Mapped[str] = mapped_column(Text)
class Evaluation(Base):
    __tablename__ = 'eligibility_evaluations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('job_postings.id', ondelete='CASCADE'), index=True)
    profile_version: Mapped[int]
    content_hash: Mapped[str] = mapped_column(String(64))
    encrypted_result: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('user_id', 'job_id', 'profile_version', 'content_hash'),)
class MatchScore(Base):
    __tablename__ = 'match_scores'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('job_postings.id', ondelete='CASCADE'))
    profile_version: Mapped[int]
    content_hash: Mapped[str] = mapped_column(String(64))
    encrypted_data: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint('user_id', 'job_id', 'profile_version', 'content_hash'),)
class SavedJob(Base):
    __tablename__ = 'saved_jobs'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('job_postings.id', ondelete='CASCADE'), primary_key=True)
    hidden: Mapped[bool] = mapped_column(default=False)
    # Source version at save time; version alerts fire only for later changes.
    saved_content_hash: Mapped[str | None] = mapped_column(String(64))
class Application(Base):
    __tablename__ = 'applications'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('job_postings.id'))
    stage: Mapped[str] = mapped_column(String(30), default='Saved')
    encrypted_data: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint('user_id', 'job_id'),)
class DiscoveryRun(Base):
    __tablename__ = 'discovery_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default='running')
    details: Mapped[dict] = mapped_column(JSON, default=dict)
class Notification(Base):
    __tablename__ = 'notifications'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(255))
    data: Mapped[dict] = mapped_column(JSON)
    read: Mapped[bool] = mapped_column(default=False)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('user_id', 'dedupe_key'),)
class NotificationPreference(Base):
    __tablename__ = 'notification_preferences'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
class Audit(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), index=True)
    action: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class RateLimit(Base):
    __tablename__ = 'rate_limits'
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int] = mapped_column(Integer, default=0)
class Lease(Base):
    """Named lease (scheduler leadership) and worker heartbeat; replaces the Redis lock."""
    __tablename__ = 'leases'
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    owner: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class Task(Base):
    """Durable task queue row. Claimed with a renewable lease; exhausted tasks become dead letters."""
    __tablename__ = 'tasks'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(50), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # queued | running | done | dead
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    # Prevents duplicate queued/running work; cleared when the task finishes.
    dedupe_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
class EmailOutbox(Base):
    """Transactional outbox. Rows are written with their notifications and sent by the worker."""
    __tablename__ = 'email_outbox'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    # pending | sending | sent | uncertain | failed. 'uncertain' is never resent automatically.
    status: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    notification_ids: Mapped[list] = mapped_column(JSON, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
class EmbeddingCache(Base):
    """Vectors keyed by provider/model identity and text hash; a model change never reuses old vectors."""
    __tablename__ = 'embedding_cache'
    model_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    text_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    vector: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
Index('ix_jobs_company_status', Job.company, Job.status)
