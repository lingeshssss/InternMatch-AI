from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import create_engine, String, Text, JSON, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings

def now(): return datetime.now(timezone.utc)
def uid(): return str(uuid4())
class Base(DeclarativeBase): pass
engine = create_engine(settings.database_url, pool_pre_ping=True)
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
Index('ix_jobs_company_status', Job.company, Job.status)
