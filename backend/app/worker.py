"""Background worker: durable task execution plus one elected scheduler (PostgreSQL lease)."""
import base64, logging, os, signal, smtplib, socket, ssl, threading, time, uuid
from datetime import timedelta, date, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from sqlalchemy import select, delete
from .config import settings
from .db import *
from .security import decrypt, encrypt
from .services import evaluate_job, match_job, notify
from .discovery import discover, extract_posting
from .ai import AIUnavailable, AIOutputInvalid, extract_resume
from . import tasks

log=logging.getLogger('internmatch.worker')
OWNER=f'{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}'
SCHEDULER_LEASE=120
REFRESH_INTERVAL=timedelta(hours=1)
stopping=threading.Event()

def acquire_lease(db,name,seconds):
    """Take or renew a named lease. Row lock makes concurrent workers agree on one holder."""
    current=now()
    row=db.scalar(select(Lease).where(Lease.name==name).with_for_update())
    if row is None:
        db.add(Lease(name=name,owner=OWNER,expires_at=current+timedelta(seconds=seconds),heartbeat_at=current))
    elif row.owner==OWNER or aware(row.expires_at)<current:
        row.owner,row.expires_at,row.heartbeat_at=OWNER,current+timedelta(seconds=seconds),current
    else:
        db.rollback(); return False
    try: db.commit(); return True
    except Exception: db.rollback(); return False

def heartbeat(db):
    row=db.get(Lease,'worker-heartbeat')
    if row: row.owner,row.heartbeat_at,row.expires_at=OWNER,now(),now()+timedelta(seconds=90)
    else: db.add(Lease(name='worker-heartbeat',owner=OWNER,heartbeat_at=now(),expires_at=now()+timedelta(seconds=90)))
    db.commit()

def refresh_user(db,user_id):
    """Re-evaluate one user's catalogue and create in-app notifications (and outbox digests)."""
    prefs=db.get(NotificationPreference,user_id)
    preferred={p.casefold() for p in (prefs.data if prefs else {}).get('preferred_companies',[])}
    saved={s.job_id:s for s in db.scalars(select(SavedJob).where(SavedJob.user_id==user_id,SavedJob.hidden==False))}
    for job in db.scalars(select(Job)):
        result=evaluate_job(db,user_id,job)
        if result['status']=='Verified Eligible':
            notify(db,user_id,'eligible:'+job.id+':'+job.content_hash,{'type':'eligible','job_id':job.id,'title':job.title,'company':job.company})
            try: match_job(db,user_id,job)
            except Exception as exc: log.warning('Matching unavailable: %s',type(exc).__name__)
        if job.company.casefold() in preferred and job.status=='open':
            notify(db,user_id,'company:'+job.id,{'type':'preferred_company','job_id':job.id,'title':job.title,'company':job.company})
        row=saved.get(job.id)
        if row:
            if job.status=='closed': notify(db,user_id,'closed:'+job.id+':'+job.content_hash,{'type':'closed','job_id':job.id,'title':job.title})
            if row.saved_content_hash is None: row.saved_content_hash=job.content_hash  # Legacy save: record baseline, no alert.
            elif row.saved_content_hash!=job.content_hash:
                notify(db,user_id,'version:'+job.id+':'+job.content_hash,{'type':'source_version','job_id':job.id,'title':job.title,'note':'The employer changed this posting after you saved it. Review the current source.'})
            deadline=job.details.get('deadline')
            if deadline and 0 <= (date.fromisoformat(deadline)-date.today()).days <= 7:
                notify(db,user_id,'deadline:'+job.id+':'+deadline,{'type':'deadline','job_id':job.id,'title':job.title,'deadline':deadline})
    for app in db.scalars(select(Application).where(Application.user_id==user_id)):
        follow=decrypt(app.encrypted_data).get('follow_up')
        if follow and date.fromisoformat(follow)<=date.today():
            notify(db,user_id,'followup:'+app.id+':'+follow,{'type':'follow_up','job_id':app.job_id,'date':follow})

def compose_digests(db):
    """Move due notifications into the outbox in the same transaction that marks them emailed."""
    if not settings.smtp_host or not settings.email_from: return
    for pref in db.scalars(select(NotificationPreference)):
        if not pref.data.get('email'): continue
        interval=timedelta(days=7 if pref.data.get('digest')=='weekly' else 1)
        last=db.scalar(select(EmailOutbox.created_at).where(EmailOutbox.user_id==pref.user_id).order_by(EmailOutbox.created_at.desc()).limit(1))
        if last and aware(last)>now()-interval: continue
        pending=list(db.scalars(select(Notification).where(Notification.user_id==pref.user_id,Notification.emailed_at.is_(None)).limit(100)))
        if not pending: continue
        body='\n\n'.join(n.data.get('type','Update').replace('_',' ')+': '+n.data.get('title','Application reminder') for n in pending)
        body+='\n\nSign in to inspect original employer evidence. Manage alerts in notification settings.'
        outbox=EmailOutbox(user_id=pref.user_id,subject='Your InternMatch AI opportunity digest',body=body,notification_ids=[n.id for n in pending])
        db.add(outbox)
        for n in pending: n.emailed_at=now()
        db.flush(); tasks.enqueue(db,'send_email',{'outbox_id':outbox.id},dedupe_key='email:'+outbox.id,max_attempts=3)
        db.commit()

def send_email(db,outbox_id):
    """At-most-once: a crash after SMTP acceptance leaves 'sending', later marked 'uncertain', never resent."""
    row=db.get(EmailOutbox,outbox_id)
    if not row or row.status not in ('pending',): return 'skipped'
    user=db.get(User,row.user_id)
    message=EmailMessage(); message['From']=settings.email_from; message['To']=user.email; message['Subject']=row.subject
    message['Message-ID']=make_msgid(idstring=row.id.replace('-',''),domain=settings.email_from.split('@')[-1])
    message.set_content(row.body)
    try:
        smtp=smtplib.SMTP(settings.smtp_host,settings.smtp_port,timeout=30)
        smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_username: smtp.login(settings.smtp_username,settings.smtp_password)
    except Exception as exc:
        row.attempts+=1; row.last_error=type(exc).__name__; db.commit()
        raise AIUnavailable('SMTP connection failed')  # Retryable: nothing was handed to the server.
    row.status='sending'; row.attempts+=1; db.commit()
    try:
        with smtp: smtp.send_message(message)
    except (smtplib.SMTPRecipientsRefused,smtplib.SMTPSenderRefused) as exc:
        row.status='failed'; row.last_error=type(exc).__name__; db.commit(); return 'failed'
    except Exception as exc:
        row.status='uncertain'; row.last_error=type(exc).__name__; db.commit(); return 'uncertain'
    row.status='sent'; row.sent_at=now(); db.commit(); return 'sent'

def extract_resume_task(db,resume_id):
    from .documents import resume_text
    row=db.get(Resume,resume_id)
    if not row or row.extraction_status!='pending': return 'skipped'
    raw=base64.b64decode(decrypt(row.encrypted_document)['base64'])
    try: extraction,provenance=extract_resume(resume_text(row.filename,raw))
    except AIOutputInvalid:
        row.extraction_status='failed'; row.extraction_error='The AI model returned output that failed validation. Enter your details manually, or retry later.'
        return 'invalid'
    row.encrypted_extraction=encrypt({**extraction.model_dump(mode='json'),'_provenance':provenance})
    row.extraction_status='ready'; row.extraction_error=None
    return 'ok'

def run_task(task):
    with Session() as db:
        p=task.payload
        if task.kind=='discover': return discover(db).status
        if task.kind=='extract_job':
            result=extract_posting(db,p['job_id'],p['content_hash']); db.commit()
            if result=='ok': enqueue_refresh_all(db); db.commit()
            return result
        if task.kind=='extract_resume':
            result=extract_resume_task(db,p['resume_id']); db.commit(); return result
        if task.kind=='refresh_user':
            refresh_user(db,p['user_id']); db.commit(); return 'ok'
        if task.kind=='send_email': return send_email(db,p['outbox_id'])
        raise ValueError('Unknown task kind')

def on_dead(db,task):
    """Surface dead resume extractions to the user instead of leaving them pending."""
    if task.kind=='extract_resume':
        row=db.get(Resume,task.payload.get('resume_id'))
        if row and row.extraction_status=='pending':
            row.extraction_status='failed'; row.extraction_error=(task.last_error or 'AI extraction unavailable')[:300]

def enqueue_refresh_all(db):
    for user_id in db.scalars(select(User.id)): tasks.enqueue(db,'refresh_user',{'user_id':user_id},dedupe_key='refresh:'+user_id,delay_seconds=30)

def execute_one():
    with Session() as db:
        task=tasks.claim(db,OWNER)
        if not task: return False
        task_id=task.id
    done=threading.Event()
    def keep_alive():
        while not done.wait(60):
            with Session() as db:
                if not tasks.renew(db,task_id,OWNER): log.warning('Lost lease for task %s',task_id); return
    renewer=threading.Thread(target=keep_alive,daemon=True); renewer.start()
    try:
        outcome=run_task(task); error=None
    except AIUnavailable as exc: outcome,error=None,str(exc)
    except Exception as exc: outcome,error=None,type(exc).__name__
    finally: done.set()
    with Session() as db:
        row=db.get(Task,task_id)
        if row.lease_owner!=OWNER: return True  # Another worker reclaimed it after our lease expired.
        if error is None: tasks.complete(db,row)
        else:
            tasks.fail(db,row,error)
            if row.status=='dead': on_dead(db,row); log.error('Task %s (%s) moved to dead letters: %s',task_id,row.kind,error)
        db.commit()
    log.info('Task %s %s: %s',task.kind,task_id,outcome or 'retry/dead')
    return True

def schedule(db):
    """Leader-only periodic work. Enqueues tasks; never performs slow work inline."""
    last=db.scalar(select(DiscoveryRun).where(DiscoveryRun.status=='complete').order_by(DiscoveryRun.started_at.desc()).limit(1))
    due=not last or aware(last.started_at)<now()-timedelta(seconds=max(settings.discovery_interval_seconds,900))
    if due and (settings.greenhouse_boards or settings.lever_sites): tasks.enqueue(db,'discover',{},dedupe_key='discover',max_attempts=1)
    marker=db.get(Lease,'refresh-all')
    if not marker or aware(marker.heartbeat_at)<now()-REFRESH_INTERVAL:
        enqueue_refresh_all(db)
        if marker: marker.heartbeat_at=now()
        else: db.add(Lease(name='refresh-all',owner=OWNER,heartbeat_at=now(),expires_at=now()))
    db.commit()
    compose_digests(db)
    # Outbox rows stuck in 'sending' were interrupted after possible SMTP acceptance; never resend automatically.
    for row in db.scalars(select(EmailOutbox).where(EmailOutbox.status=='sending',EmailOutbox.created_at<now()-timedelta(minutes=15))):
        row.status='uncertain'; log.error('Email %s delivery uncertain after interruption; not resent',row.id)
    db.execute(delete(AuthSession).where(AuthSession.expires_at<now()))
    db.execute(delete(Audit).where(Audit.created_at<now()-timedelta(days=90)))
    db.execute(delete(Notification).where(Notification.created_at<now()-timedelta(days=90)))
    db.execute(delete(Task).where(Task.status=='done',Task.finished_at<now()-timedelta(days=14)))
    db.execute(delete(RateLimit).where(RateLimit.window_start<now()-timedelta(days=1)))
    db.commit()

def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,lambda *_: stopping.set())
    log.info('Worker %s started (AI provider: %s)',OWNER,settings.ai_provider)
    last_schedule=0.0
    while not stopping.is_set():
        try:
            if time.monotonic()-last_schedule>=30:
                with Session() as db:
                    heartbeat(db)
                    if acquire_lease(db,'scheduler',SCHEDULER_LEASE): schedule(db)
                last_schedule=time.monotonic()
            if execute_one(): continue
        except Exception as exc:
            log.error('Worker loop error: %s',type(exc).__name__)
        stopping.wait(2)
    log.info('Worker %s stopped',OWNER)

if __name__=='__main__': main()
