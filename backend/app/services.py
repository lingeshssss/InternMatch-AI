from datetime import date, timedelta
from sqlalchemy import select
from .db import Profile, Requirement, Evaluation, Notification, MatchScore, NotificationPreference, now
from .security import decrypt, encrypt
from .schemas import ProfileData, RequirementData
from .eligibility import evaluate
from .matching import fit

def profile_for(db,user_id):
    profile=db.get(Profile,user_id)
    return profile,ProfileData.model_validate(decrypt(profile.encrypted_data)) if profile else ProfileData()

def evaluate_job(db,user_id,job):
    profile,p=profile_for(db,user_id); version=profile.version if profile else 0
    stale=job.retrieved_at.replace(tzinfo=now().tzinfo) < now()-timedelta(days=2)
    cached=db.scalar(select(Evaluation).where(Evaluation.user_id==user_id,Evaluation.job_id==job.id,Evaluation.profile_version==version,Evaluation.content_hash==job.content_hash))
    if cached and job.status=='open' and not stale:
        cached_result=decrypt(cached.encrypted_result)
        if cached_result.get('verified_at')==job.retrieved_at.isoformat(): return cached_result
    requirements=[RequirementData.model_validate(x.data) for x in db.scalars(select(Requirement).where(Requirement.job_id==job.id))]
    start=date.fromisoformat(job.details['internship_start']) if job.details.get('internship_start') else None
    result=evaluate(requirements,p,complete=job.extraction_complete,accessible=not stale,academic_scope_explicit=job.details.get('academic_scope_explicit',False),status=job.status,start=start,verified_at=job.retrieved_at.isoformat())
    for item in result['requirements']:
        item['source_url']=job.url; item['verified_at']=job.retrieved_at.isoformat()
    if stale: result['disclosures'].append('Source has not been refreshed within 48 hours.')
    if cached: cached.encrypted_result=encrypt(result)
    else: db.add(Evaluation(user_id=user_id,job_id=job.id,profile_version=version,content_hash=job.content_hash,encrypted_result=encrypt(result)))
    return result

def match_job(db,user_id,job):
    profile,p=profile_for(db,user_id); version=profile.version if profile else 0
    cached=db.scalar(select(MatchScore).where(MatchScore.user_id==user_id,MatchScore.job_id==job.id,MatchScore.profile_version==version,MatchScore.content_hash==job.content_hash))
    if cached: return decrypt(cached.encrypted_data)
    result=fit(p,job.text)
    db.add(MatchScore(user_id=user_id,job_id=job.id,profile_version=version,content_hash=job.content_hash,encrypted_data=encrypt(result)))
    return result

def notify(db,user_id,key,data):
    prefs=db.get(NotificationPreference,user_id)
    if prefs and not prefs.data.get('in_app',True) and not prefs.data.get('email',False): return False
    if db.scalar(select(Notification.id).where(Notification.user_id==user_id,Notification.dedupe_key==key)): return False
    db.add(Notification(user_id=user_id,dedupe_key=key,data=data)); db.flush()
    return True
