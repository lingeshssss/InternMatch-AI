"""Single elected scheduler. Redis lock prevents duplicate discovery across workers."""
import logging, smtplib, ssl, time
from datetime import timedelta, date, timezone
from email.message import EmailMessage
from sqlalchemy import select, delete
from .config import settings
from .db import *
from .security import redis
from .services import evaluate_job, match_job, notify
from .discovery import discover

log=logging.getLogger('internmatch.worker')

def refresh(db):
    for user in db.scalars(select(User)):
        prefs=db.get(NotificationPreference,user.id)
        preferred=(prefs.data if prefs else {}).get('preferred_companies',[])
        saved={s.job_id for s in db.scalars(select(SavedJob).where(SavedJob.user_id==user.id,SavedJob.hidden==False))}
        for job in db.scalars(select(Job)):
            result=evaluate_job(db,user.id,job)
            if result['status']=='Verified Eligible':
                notify(db,user.id,'eligible:'+job.id+':'+job.content_hash,{'type':'eligible','job_id':job.id,'title':job.title,'company':job.company})
                try: match_job(db,user.id,job)
                except Exception as exc: log.warning('Matching unavailable: %s',type(exc).__name__)
            if job.company.casefold() in {p.casefold() for p in preferred} and job.status=='open':
                notify(db,user.id,'company:'+job.id,{'type':'preferred_company','job_id':job.id,'title':job.title,'company':job.company})
            if job.id in saved:
                if job.status=='closed': notify(db,user.id,'closed:'+job.id+':'+job.content_hash,{'type':'closed','job_id':job.id,'title':job.title})
                notify(db,user.id,'version:'+job.id+':'+job.content_hash,{'type':'source_version','job_id':job.id,'title':job.title,'note':'Current source version is available for review.'})
                deadline=job.details.get('deadline')
                if deadline and 0 <= (date.fromisoformat(deadline)-date.today()).days <= 7:
                    notify(db,user.id,'deadline:'+job.id+':'+deadline,{'type':'deadline','job_id':job.id,'title':job.title,'deadline':deadline})
        for app in db.scalars(select(Application).where(Application.user_id==user.id)):
            from .security import decrypt
            follow=decrypt(app.encrypted_data).get('follow_up')
            if follow and date.fromisoformat(follow)<=date.today():
                notify(db,user.id,'followup:'+app.id+':'+follow,{'type':'follow_up','job_id':app.job_id,'date':follow})
        db.commit()
        redis.delete('refresh:'+user.id)

def email_digests(db):
    if not settings.smtp_host or not settings.email_from: return
    for pref in db.scalars(select(NotificationPreference)):
        if not pref.data.get('email'): continue
        interval=timedelta(days=7 if pref.data.get('digest')=='weekly' else 1)
        last=db.scalar(select(Notification.emailed_at).where(Notification.user_id==pref.user_id,Notification.emailed_at.is_not(None)).order_by(Notification.emailed_at.desc()).limit(1))
        if last and last.replace(tzinfo=timezone.utc)>now()-interval: continue
        pending=list(db.scalars(select(Notification).where(Notification.user_id==pref.user_id,Notification.emailed_at.is_(None)).limit(100)))
        if not pending: continue
        user=db.get(User,pref.user_id)
        message=EmailMessage(); message['From']=settings.email_from; message['To']=user.email; message['Subject']='Your InternMatch AI opportunity digest'
        message['Message-ID']='<'+pending[0].id+'@internmatch.local>'
        message.set_content('\n\n'.join(n.data.get('type','Update')+': '+n.data.get('title','Application reminder') for n in pending)+'\n\nSign in to inspect original employer evidence. Manage alerts in notification settings.')
        with smtplib.SMTP(settings.smtp_host,settings.smtp_port,timeout=30) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username: smtp.login(settings.smtp_username,settings.smtp_password)
            smtp.send_message(message)
        for row in pending: row.emailed_at=now()
        db.commit()

def tick():
    lock=redis.lock('scheduler:lock',timeout=3600,blocking_timeout=0)
    if not lock.acquire(blocking=False): return
    try:
        with Session() as db:
            last=db.scalar(select(DiscoveryRun).where(DiscoveryRun.status=='complete').order_by(DiscoveryRun.started_at.desc()).limit(1))
            due=not last or last.started_at.replace(tzinfo=timezone.utc)<now()-timedelta(seconds=max(settings.discovery_interval_seconds,900))
            requested=redis.getdel('discovery:requested')
            if (due or requested) and (settings.greenhouse_boards or settings.lever_sites): discover(db)
            refresh(db)
            email_digests(db)
            db.execute(delete(AuthSession).where(AuthSession.expires_at<now()))
            db.execute(delete(Audit).where(Audit.created_at<now()-timedelta(days=90)))
            db.execute(delete(Notification).where(Notification.created_at<now()-timedelta(days=90)))
            db.commit()
    finally:
        if lock.owned(): lock.release()

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    while True:
        try: tick()
        except Exception as exc: log.error('Scheduler tick failed: %s',type(exc).__name__)
        time.sleep(30)
