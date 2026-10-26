"""Same-origin security, PostgreSQL-backed primitives, task queue, email outbox and resume workflow."""
import smtplib
from datetime import timedelta
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app import tasks, worker
from app.db import Base, engine, Task, EmailOutbox, Notification, NotificationPreference, SavedJob, Resume, User, Lease, now
from app.security import encrypt

def register(client, email='platform@example.com'):
    r = client.post('/api/auth/register', json={'email': email, 'password': 'correct horse battery staple'}); assert r.status_code == 200, r.text
    return r.json()

def test_routes_live_under_api_prefix(client):
    assert client.get('/api/health/live').json() == {'status': 'ok'}
    assert client.get('/health').status_code == 404

def test_unsafe_methods_require_configured_origin(client):
    assert client.post('/api/auth/login', headers={'Origin': 'https://frontend-delta-puce-51.vercel.app'}, json={}).status_code == 403
    assert client.post('/api/auth/login', headers={'Origin': ''}, json={}).status_code == 403
    assert client.post('/api/auth/login', json={'email': 'nobody@example.com', 'password': 'x' * 12}).status_code == 401

def test_no_cors_headers_on_same_origin_api(client):
    r = client.options('/api/auth/login', headers={'Origin': 'https://attacker.example', 'Access-Control-Request-Method': 'POST'})
    assert 'access-control-allow-origin' not in r.headers

def test_session_cookie_attributes(client):
    r = client.post('/api/auth/register', json={'email': 'cookie@example.com', 'password': 'correct horse battery staple'})
    cookie = r.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=lax' in cookie and 'path=/' in cookie and 'domain=' not in cookie

def test_session_persists_and_logout_revokes(client):
    register(client)
    assert client.get('/api/auth/me').status_code == 200
    token = client.cookies.get('internmatch_session')
    client.post('/api/auth/logout')
    assert client.get('/api/auth/me').status_code == 401
    client.cookies.set('internmatch_session', token)
    assert client.get('/api/auth/me').status_code == 401  # Server-side revocation, not just cookie deletion.

def test_production_cookie_is_host_prefixed_and_secure(monkeypatch):
    import importlib, app.config, app.security
    monkeypatch.setenv('APP_ENV', 'production'); monkeypatch.setenv('APP_ORIGINS', 'https://app.example.com')
    importlib.reload(app.config); sec = importlib.reload(app.security)
    try:
        from fastapi import Response
        resp = Response(); sec.set_session_cookie(resp, 'token')
        header = resp.headers['set-cookie']
        assert header.startswith('__Host-internmatch_session=') and 'Secure' in header and 'Domain' not in header
        assert app.config.settings.origins == ['https://app.example.com']
    finally:
        monkeypatch.setenv('APP_ENV', 'development'); monkeypatch.setenv('APP_ORIGINS', 'http://localhost:8080')
        importlib.reload(app.config); importlib.reload(app.security)

def test_production_has_no_default_origins(monkeypatch):
    from app.config import Settings
    assert Settings(app_env='production', app_origins='', frontend_origin='').origins == []
    assert Settings(app_env='production', app_origins='', frontend_origin='https://legacy.example.com/').origins == ['https://legacy.example.com']

def test_postgres_style_rate_limiter():
    from app.security import rate_limit
    Base.metadata.create_all(engine)
    rate_limit('unit:test', limit=2, seconds=60); rate_limit('unit:test', limit=2, seconds=60)
    with pytest.raises(HTTPException) as e: rate_limit('unit:test', limit=2, seconds=60)
    assert e.value.status_code == 429

def test_task_queue_lease_retry_dead_letter(db):
    t = tasks.enqueue(db, 'extract_job', {'job_id': 'x'}, dedupe_key='extract:x', max_attempts=2); db.commit()
    assert tasks.enqueue(db, 'extract_job', {'job_id': 'x'}, dedupe_key='extract:x') is None
    claimed = tasks.claim(db, 'w1'); assert claimed.id == t.id and claimed.attempts == 1
    assert tasks.claim(db, 'w2') is None
    assert tasks.renew(db, t.id, 'w1') and not tasks.renew(db, t.id, 'w2')
    tasks.fail(db, claimed, 'AIUnavailable'); db.commit()
    assert claimed.status == 'queued' and claimed.run_after > now() and claimed.lease_owner is None
    claimed.run_after = now() - timedelta(seconds=1); db.commit()
    again = tasks.claim(db, 'w1'); assert again.attempts == 2
    tasks.fail(db, again, 'AIUnavailable'); db.commit()
    assert again.status == 'dead' and again.dedupe_key is None and again.last_error == 'AIUnavailable'

def test_expired_lease_is_reclaimed(db):
    t = tasks.enqueue(db, 'discover', {}, max_attempts=3); db.commit()
    tasks.claim(db, 'crashed-worker')
    t.lease_expires_at = now() - timedelta(seconds=1); db.commit()
    reclaimed = tasks.claim(db, 'w2')
    assert reclaimed.id == t.id and reclaimed.lease_owner == 'w2' and reclaimed.attempts == 2

class FakeSMTP:
    sent = []; fail_on_send = None; fail_on_connect = False
    def __init__(self, *a, **k):
        if FakeSMTP.fail_on_connect: raise ConnectionRefusedError()
    def starttls(self, context=None): pass
    def login(self, u, p): pass
    def send_message(self, m):
        if FakeSMTP.fail_on_send: raise FakeSMTP.fail_on_send
        FakeSMTP.sent.append(m)
    def __enter__(self): return self
    def __exit__(self, *a): pass

@pytest.fixture
def mail(db, monkeypatch):
    monkeypatch.setattr(worker.smtplib, 'SMTP', FakeSMTP)
    monkeypatch.setattr(worker.settings, 'smtp_host', 'smtp.example.com'); monkeypatch.setattr(worker.settings, 'email_from', 'alerts@example.com')
    FakeSMTP.sent, FakeSMTP.fail_on_send, FakeSMTP.fail_on_connect = [], None, False
    u = User(email='digest@example.com', password='x'); db.add(u); db.flush()
    db.add(NotificationPreference(user_id=u.id, data={'email': True, 'digest': 'daily'}))
    db.add(Notification(user_id=u.id, dedupe_key='k', data={'type': 'eligible', 'title': 'Intern'})); db.commit()
    return u

def test_digest_written_to_outbox_transactionally_then_sent_once(db, mail):
    worker.compose_digests(db)
    row = db.scalar(select(EmailOutbox)); assert row.status == 'pending'
    assert db.scalar(select(Notification)).emailed_at is not None
    assert db.scalar(select(Task).where(Task.kind == 'send_email'))
    assert worker.send_email(db, row.id) == 'sent' and len(FakeSMTP.sent) == 1
    assert worker.send_email(db, row.id) == 'skipped' and len(FakeSMTP.sent) == 1
    worker.compose_digests(db); assert len(list(db.scalars(select(EmailOutbox)))) == 1

def test_interrupted_send_is_uncertain_not_resent(db, mail):
    worker.compose_digests(db); row = db.scalar(select(EmailOutbox))
    FakeSMTP.fail_on_send = smtplib.SMTPServerDisconnected('lost')
    assert worker.send_email(db, row.id) == 'uncertain'
    FakeSMTP.fail_on_send = None
    assert worker.send_email(db, row.id) == 'skipped' and FakeSMTP.sent == []

def test_connection_failure_is_retryable(db, mail):
    worker.compose_digests(db); row = db.scalar(select(EmailOutbox))
    FakeSMTP.fail_on_connect = True
    with pytest.raises(worker.AIUnavailable): worker.send_email(db, row.id)
    assert row.status == 'pending' and row.attempts == 1

def seed_job(db, content_hash='v1'):
    from app.db import Company, Job
    c = Company(name='Version Co'); db.add(c); db.flush()
    job = Job(id='ver-job', company_id=c.id, company=c.name, title='Intern', location=None, url='https://example.com/ver', source='t', source_key='t', text='x', content_hash=content_hash, details={}, extraction_complete=False)
    db.add(job); db.commit(); return job

def test_source_version_alert_not_fired_for_initial_save(client, db):
    u = register(client); job = seed_job(db)
    client.put('/api/jobs/ver-job/saved')
    worker.refresh_user(db, u['id']); db.commit()
    assert not [n for n in db.scalars(select(Notification)) if n.data['type'] == 'source_version']
    job.content_hash = 'v2'; db.commit()
    worker.refresh_user(db, u['id']); db.commit()
    assert [n for n in db.scalars(select(Notification)) if n.data['type'] == 'source_version']
    saved = client.get('/api/saved').json()
    assert saved['total'] == 1 and saved['items'][0]['changed_since_saved'] is True

def test_saved_view_not_page_bounded(client, db):
    from app.db import Company, Job
    register(client); c = Company(name='Many Co'); db.add(c); db.flush()
    for i in range(40):
        db.add(Job(id=f'm{i}', company_id=c.id, company=c.name, title='Intern', location=None, url=f'https://example.com/m{i}', source='t', source_key='t', text='x', content_hash='h', details={}, extraction_complete=False))
    db.commit()
    for i in range(40): client.put(f'/api/jobs/m{i}/saved')
    assert client.get('/api/saved').json()['total'] == 40
    assert client.get('/api/jobs?mode=explore').json()['saved_total'] == 40

def make_docx():
    import io
    from docx import Document
    d = Document(); d.add_paragraph('Jordan Lee. B.S. Computer Science. Skills: Python.'); buf = io.BytesIO(); d.save(buf); return buf.getvalue()

def test_resume_upload_with_ai_unavailable_keeps_document_and_allows_manual_entry(client, db):
    register(client)
    r = client.post('/api/resumes', files={'file': ('resume.docx', make_docx(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['extraction_status'] == 'failed' and 'AI extraction unavailable' in body['extraction_error']
    assert body['extraction']['skills'] is None  # Nothing fabricated.
    assert not list(db.scalars(select(Task).where(Task.kind == 'extract_resume')))
    assert client.get('/api/resumes/' + body['id'] + '/download').status_code == 200
    confirm = client.post('/api/resumes/' + body['id'] + '/confirm', json={'skills': ['Python']})
    assert confirm.status_code == 200 and client.get('/api/profile').json()['skills'] == ['Python']

def test_resume_upload_with_ai_ready_queues_extraction(client, db, monkeypatch):
    monkeypatch.setattr('app.main.ai_status', lambda: {'ready': True})
    register(client)
    body = client.post('/api/resumes', files={'file': ('resume.docx', make_docx(), 'application/octet-stream')}).json()
    assert body['extraction_status'] == 'pending'
    assert db.scalar(select(Task).where(Task.kind == 'extract_resume')).payload == {'resume_id': body['id']}

def test_dead_resume_task_surfaces_failure(db):
    u = User(email='dead@example.com', password='x'); db.add(u); db.flush()
    r = Resume(user_id=u.id, filename='a.pdf', encrypted_document=encrypt({'base64': ''}), encrypted_extraction=encrypt({}), extraction_status='pending'); db.add(r); db.flush()
    t = Task(kind='extract_resume', payload={'resume_id': r.id}, status='dead', last_error='Local AI runtime is not reachable'); db.add(t)
    worker.on_dead(db, t)
    assert r.extraction_status == 'failed' and 'not reachable' in r.extraction_error

def test_health_reports_worker_heartbeat(client, db):
    assert client.get('/api/health').json()['worker'] is False
    db.add(Lease(name='worker-heartbeat', owner='w', heartbeat_at=now(), expires_at=now())); db.commit()
    assert client.get('/api/health').json()['worker'] is True

def test_scheduler_lease_single_holder(db, monkeypatch):
    assert worker.acquire_lease(db, 'scheduler', 60)
    monkeypatch.setattr(worker, 'OWNER', 'other-worker')
    assert worker.acquire_lease(db, 'scheduler', 60) is False

def test_aware_converts_offset_timestamps_instead_of_relabelling():
    # Regression: PostgreSQL on a non-UTC host returns e.g. 22:40-04:00; relabelling as UTC shifted values by 4 hours.
    from datetime import datetime, timezone as tz
    from app.db import aware
    local = datetime(2026, 10, 25, 22, 40, tzinfo=tz(timedelta(hours=-4)))
    assert aware(local) == datetime(2026, 10, 26, 2, 40, tzinfo=tz.utc)
    assert aware(datetime(2026, 10, 26, 2, 40)) == datetime(2026, 10, 26, 2, 40, tzinfo=tz.utc)

@pytest.mark.parametrize('url', ['postgres://u:p@h:5432/d', 'postgresql://u:p@h:5432/d', 'postgresql+psycopg://u:p@h:5432/d'])
def test_managed_database_urls_use_psycopg_driver(url):
    from app.config import Settings
    assert Settings(database_url=url).database_url == 'postgresql+psycopg://u:p@h:5432/d'
