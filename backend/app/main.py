import base64, json, logging
from datetime import timedelta, timezone
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy import select, delete, text, func
from sqlalchemy.exc import IntegrityError
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from .config import settings
from .db import *
from .schemas import ProfileData, Credentials, ApplicationData, Preferences
from .security import get_db, current_user, new_session, clear_session_cookie, hasher, digest, encrypt, decrypt, rate_limit, cipher, COOKIE
from .services import profile_for, evaluate_job, match_job
from .documents import resume_text, MAX_BYTES
from .ai import ai_status
from . import tasks

# Same-origin deployment: the reverse proxy forwards /api/* unchanged, so no CORS is configured.
app=FastAPI(title='InternMatch AI',version='0.2.0',docs_url=None if settings.production else '/api/docs',redoc_url=None,openapi_url=None if settings.production else '/api/openapi.json')
api=APIRouter(prefix='/api')

@app.middleware('http')
async def guard(request,call_next):
    # CSRF defence: unsafe methods must come from a configured browser origin (plus SameSite=Lax cookies).
    if request.method in ('POST','PUT','DELETE','PATCH') and request.headers.get('origin') not in settings.origins:
        return JSONResponse({'detail':'A matching Origin header is required'},status_code=403)
    if request.url.path!='/api/health/live':
        try:
            # Client address comes from uvicorn, which honours X-Forwarded-For only from FORWARDED_ALLOW_IPS (the local proxy).
            rate_limit('http:'+str(request.client.host if request.client else 'unknown'),limit=180)
        except HTTPException as e: return JSONResponse({'detail':e.detail},status_code=e.status_code)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cache-Control']='no-store'
    return response

@app.exception_handler(Exception)
async def unexpected(request,exc):
    logging.getLogger('internmatch').error('Request failed: %s',type(exc).__name__)
    return JSONResponse({'detail':'Operation unavailable; consult server logs and configuration'},status_code=503)

def worker_status(db):
    row=db.get(Lease,'worker-heartbeat')
    if not row: return {'running':False,'last_heartbeat':None}
    age=(now()-aware(row.heartbeat_at)).total_seconds()
    return {'running':age<120,'last_heartbeat':row.heartbeat_at.isoformat(),'age_seconds':round(age)}

@api.get('/health/live')
def live(): return {'status':'ok'}

@api.get('/health')
def health(response:Response,db=Depends(get_db)):
    """Readiness: database and encryption key. Integration flags report configuration, not verified provider access."""
    db.execute(text('SELECT 1')); cipher()
    worker=worker_status(db)
    return {'status':'ok','worker':worker['running'],'integrations':{'ai_provider':settings.ai_provider,'discovery_sources':bool(settings.greenhouse_boards or settings.lever_sites),'email':bool(settings.smtp_host and settings.email_from)}}

@api.get('/status')
def status(user=Depends(current_user),db=Depends(get_db)):
    return {'ai':ai_status(),'worker':worker_status(db),'tasks':tasks.summary(db),'discovery_sources':{'greenhouse':[x for x in settings.greenhouse_boards.split(',') if x.strip()],'lever':[x for x in settings.lever_sites.split(',') if x.strip()]},'email':bool(settings.smtp_host and settings.email_from)}

@api.post('/auth/register')
def register(body:Credentials,response:Response,request:Request,db=Depends(get_db)):
    rate_limit('register:'+request.client.host,5,3600)
    cipher()
    user=User(email=body.email,password=hasher.hash(body.password)); db.add(user)
    try: db.flush()
    except IntegrityError: db.rollback(); raise HTTPException(409,'Account cannot be created with these details')
    new_session(db,user,response); db.add(Audit(user_id=user.id,action='account.created')); db.commit()
    return {'id':user.id,'email':user.email}

@api.post('/auth/login')
def login(body:Credentials,response:Response,request:Request,db=Depends(get_db)):
    rate_limit('login:'+request.client.host,10,900)
    user=db.scalar(select(User).where(User.email==body.email))
    try:
        # Hash on missing users too, reducing account enumeration timing differences.
        if not user:
            hasher.verify(hasher.hash('unavailable-account-password'),body.password)
            raise VerifyMismatchError()
        hasher.verify(user.password,body.password)
    except (VerifyMismatchError,VerificationError,InvalidHashError): raise HTTPException(401,'Invalid credentials')
    new_session(db,user,response); db.add(Audit(user_id=user.id,action='account.login')); db.commit()
    return {'id':user.id,'email':user.email}

@api.get('/auth/me')
def me(user=Depends(current_user)): return {'id':user.id,'email':user.email}

@api.post('/auth/logout')
def logout(request:Request,response:Response,db=Depends(get_db)):
    token=request.cookies.get(COOKIE,'')
    db.execute(delete(AuthSession).where(AuthSession.token_hash==digest(token))); db.commit()
    clear_session_cookie(response)
    return {'ok':True}

@api.get('/profile')
def get_profile(user=Depends(current_user),db=Depends(get_db)):
    _,p=profile_for(db,user.id); return p

@api.put('/profile')
def set_profile(body:ProfileData,user=Depends(current_user),db=Depends(get_db)):
    row=db.get(Profile,user.id)
    if row: row.encrypted_data=encrypt(body.model_dump(mode='json')); row.version+=1
    else: db.add(Profile(user_id=user.id,encrypted_data=encrypt(body.model_dump(mode='json'))))
    db.add(Audit(user_id=user.id,action='profile.confirmed'))
    tasks.enqueue(db,'refresh_user',{'user_id':user.id},dedupe_key='refresh:'+user.id)
    db.commit()
    return body

@api.post('/resumes')
def upload_resume(file:UploadFile=File(...),user=Depends(current_user),db=Depends(get_db)):
    rate_limit('resume:'+user.id,10,3600)
    raw=file.file.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES: raise HTTPException(413,'Resume exceeds 5 MB')
    name=(file.filename or '').split('/')[-1].split('\\')[-1][:255]
    try: resume_text(name,raw)
    except Exception as exc: raise HTTPException(422,'Cannot parse resume: '+str(exc)[:150])
    ai=ai_status()
    row=Resume(user_id=user.id,filename=name,encrypted_document=encrypt({'base64':base64.b64encode(raw).decode()}),encrypted_extraction=encrypt(ProfileData().model_dump(mode='json')))
    if ai.get('ready'):
        row.extraction_status='pending'
    else:
        # The document is kept; the student can enter details manually. No placeholder extraction is fabricated.
        row.extraction_status='failed'; row.extraction_error='AI extraction unavailable: '+str(ai.get('error') or 'provider not ready')[:250]
    db.add(row); db.add(Audit(user_id=user.id,action='resume.uploaded')); db.flush()
    if row.extraction_status=='pending': tasks.enqueue(db,'extract_resume',{'resume_id':row.id},dedupe_key='resume:'+row.id,max_attempts=2)
    db.commit()
    return resume_view(row)

def resume_view(x):
    extraction=decrypt(x.encrypted_extraction); provenance=extraction.pop('_provenance',None)
    return {'id':x.id,'filename':x.filename,'confirmed':x.confirmed,'created_at':x.created_at,'extraction_status':x.extraction_status,'extraction_error':x.extraction_error,'extraction':extraction,'provenance':provenance}

@api.get('/resumes')
def resumes(user=Depends(current_user),db=Depends(get_db)):
    return [resume_view(x) for x in db.scalars(select(Resume).where(Resume.user_id==user.id).order_by(Resume.created_at.desc()))]

@api.get('/resumes/{id}')
def get_resume(id:str,user=Depends(current_user),db=Depends(get_db)):
    return resume_view(owned_resume(db,id,user.id))

def owned_resume(db,id,user_id):
    row=db.get(Resume,id)
    if not row or row.user_id!=user_id: raise HTTPException(404,'Resume not found')
    return row

@api.get('/resumes/{id}/download')
def download_resume(id:str,user=Depends(current_user),db=Depends(get_db)):
    row=owned_resume(db,id,user.id)
    db.add(Audit(user_id=user.id,action='resume.downloaded')); db.commit()
    return Response(base64.b64decode(decrypt(row.encrypted_document)['base64']),media_type='application/octet-stream',headers={'Content-Disposition':'attachment; filename="resume'+('.pdf' if row.filename.lower().endswith('.pdf') else '.docx')+'"'})

@api.post('/resumes/{id}/confirm')
def confirm_resume(id:str,body:ProfileData,user=Depends(current_user),db=Depends(get_db)):
    row=owned_resume(db,id,user.id)
    row.confirmed=True; row.extraction_status='ready' if row.extraction_status!='ready' else row.extraction_status
    row.encrypted_extraction=encrypt(body.model_dump(mode='json'))
    db.add(Qualification(user_id=user.id,resume_id=id,encrypted_data=encrypt(body.model_dump(mode='json'))))
    return set_profile(body,user,db)

@api.delete('/resumes/{id}')
def remove_resume(id:str,user=Depends(current_user),db=Depends(get_db)):
    row=owned_resume(db,id,user.id); db.delete(row); db.commit(); return {'ok':True}

@api.get('/jobs')
def jobs(mode:str='strict',q:str='',company:str='',location:str='',arrangement:str='',skill:str='',season:str='',sort:str='recent',offset:int=0,limit:int=30,user=Depends(current_user),db=Depends(get_db)):
    if mode not in ('strict','potential','explore'): raise HTTPException(422,'Invalid mode')
    if sort not in ('recent','company','fit','deadline'): raise HTTPException(422,'Invalid sort')
    if offset<0 or limit<1 or limit>100: raise HTTPException(422,'Invalid pagination')
    query=select(Job).where(Job.status=='open')
    for column,value in [(Job.title,q),(Job.company,company),(Job.location,location)]:
        if value: query=query.where(column.ilike('%'+value.replace('%','\\%').replace('_','\\_')+'%',escape='\\'))
    # Text matching is a discovery filter, never eligibility evidence.
    for value in (skill,season,arrangement):
        if value: query=query.where(Job.text.ilike('%'+value.replace('%','\\%').replace('_','\\_')+'%',escape='\\'))
    query=query.order_by(Job.company if sort=='company' else Job.first_seen_at.desc())
    hidden={x.job_id for x in db.scalars(select(SavedJob).where(SavedJob.user_id==user.id,SavedJob.hidden==True))}
    saved={x.job_id for x in db.scalars(select(SavedJob).where(SavedJob.user_id==user.id,SavedJob.hidden==False))}
    counts={x:0 for x in ['Verified Eligible','Potentially Eligible','Ineligible','Unverified']}; results=[]
    # Counts cover the filtered candidate set. Bounded catalogue scan reported explicitly.
    candidates=list(db.scalars(query.limit(1001))); truncated=len(candidates)>1000
    for job in candidates[:1000]:
        if job.id in hidden: continue
        result=evaluate_job(db,user.id,job); counts[result['status']]+=1
        if mode=='strict' and result['status']!='Verified Eligible': continue
        if mode=='potential' and result['status'] not in ('Verified Eligible','Potentially Eligible'): continue
        profile=db.get(Profile,user.id); version=profile.version if profile else 0
        match=db.scalar(select(MatchScore).where(MatchScore.user_id==user.id,MatchScore.job_id==job.id,MatchScore.profile_version==version,MatchScore.content_hash==job.content_hash))
        results.append(job_card(job,result,match,job.id in saved))
    if sort=='fit': results.sort(key=lambda x: (x['fit'] or {}).get('score') or -1,reverse=True)
    if sort=='deadline': results.sort(key=lambda x:x['details'].get('deadline') or '9999')
    db.commit()
    return {'items':results[offset:offset+limit],'counts':counts,'total':len(results),'truncated':truncated,'offset':offset,'limit':limit,'saved_total':len(saved)}

def job_card(job,result,match,saved):
    return {'id':job.id,'company':job.company,'title':job.title,'location':job.location,'url':job.url,'status':job.status,'details':job.details,'retrieved_at':job.retrieved_at,'first_seen_at':job.first_seen_at,'eligibility':result,'fit':decrypt(match.encrypted_data) if match else None,'saved':saved}

@api.get('/saved')
def saved_jobs(user=Depends(current_user),db=Depends(get_db)):
    """Every saved posting, including closed ones, independent of search filters and pagination."""
    profile=db.get(Profile,user.id); version=profile.version if profile else 0
    items=[]
    for row in db.scalars(select(SavedJob).where(SavedJob.user_id==user.id,SavedJob.hidden==False)):
        job=db.get(Job,row.job_id); result=evaluate_job(db,user.id,job)
        match=db.scalar(select(MatchScore).where(MatchScore.user_id==user.id,MatchScore.job_id==job.id,MatchScore.profile_version==version,MatchScore.content_hash==job.content_hash))
        items.append({**job_card(job,result,match,True),'changed_since_saved':bool(row.saved_content_hash and row.saved_content_hash!=job.content_hash)})
    db.commit()
    return {'items':items,'total':len(items)}

def get_job(db,id):
    job=db.get(Job,id)
    if not job: raise HTTPException(404,'Posting not found')
    return job

@api.get('/jobs/{id}')
def job_detail(id:str,user=Depends(current_user),db=Depends(get_db)):
    job=get_job(db,id); result=evaluate_job(db,user.id,job); db.commit()
    saved=db.get(SavedJob,(user.id,job.id))
    return {'id':job.id,'title':job.title,'company':job.company,'url':job.url,'text':job.text,'content_hash':job.content_hash,'status':job.status,'access_status':job.access_status,'retrieved_at':job.retrieved_at,'first_seen_at':job.first_seen_at,'details':job.details,'eligibility':result,'extraction_error':job.extraction_error,'saved':bool(saved and not saved.hidden),'evidence':[{'id':e.id,'quote':e.quote,'start':e.start,'end':e.end,'content_hash':e.content_hash,'source_url':e.source_url,'retrieved_at':e.retrieved_at} for e in db.scalars(select(Evidence).where(Evidence.job_id==job.id).order_by(Evidence.start))]}

@api.post('/jobs/{id}/match')
def match(id:str,user=Depends(current_user),db=Depends(get_db)):
    rate_limit('match:'+user.id,20,3600)
    job=get_job(db,id); result=match_job(db,user.id,job); db.commit(); return result

@api.put('/jobs/{id}/saved')
def save(id:str,hidden:bool=False,user=Depends(current_user),db=Depends(get_db)):
    job=get_job(db,id); row=db.get(SavedJob,(user.id,id))
    if row: row.hidden=hidden
    else: db.add(SavedJob(user_id=user.id,job_id=id,hidden=hidden,saved_content_hash=job.content_hash))
    db.commit(); return {'ok':True}

@api.delete('/jobs/{id}/saved')
def unsave(id:str,user=Depends(current_user),db=Depends(get_db)):
    db.execute(delete(SavedJob).where(SavedJob.user_id==user.id,SavedJob.job_id==id)); db.commit(); return {'ok':True}

@api.get('/applications')
def applications(user=Depends(current_user),db=Depends(get_db)):
    return [{'id':x.id,'job_id':x.job_id,'company':db.get(Job,x.job_id).company,'title':db.get(Job,x.job_id).title,'url':db.get(Job,x.job_id).url,**decrypt(x.encrypted_data),'stage':x.stage} for x in db.scalars(select(Application).where(Application.user_id==user.id))]

@api.put('/applications/{job_id}')
def application(job_id:str,body:ApplicationData,user=Depends(current_user),db=Depends(get_db)):
    get_job(db,job_id)
    if body.resume_id: owned_resume(db,body.resume_id,user.id)
    row=db.scalar(select(Application).where(Application.user_id==user.id,Application.job_id==job_id))
    if row: row.stage=body.stage; row.encrypted_data=encrypt(body.model_dump(mode='json'))
    else: db.add(Application(user_id=user.id,job_id=job_id,stage=body.stage,encrypted_data=encrypt(body.model_dump(mode='json'))))
    db.commit(); return {'ok':True}

@api.get('/notifications')
def notifications(user=Depends(current_user),db=Depends(get_db)):
    return [{'id':x.id,'data':x.data,'read':x.read,'created_at':x.created_at} for x in db.scalars(select(Notification).where(Notification.user_id==user.id).order_by(Notification.created_at.desc()).limit(100))]

@api.put('/notifications/{id}/read')
def mark_read(id:str,user=Depends(current_user),db=Depends(get_db)):
    row=db.get(Notification,id)
    if not row or row.user_id!=user.id: raise HTTPException(404,'Notification not found')
    row.read=True; db.commit(); return {'ok':True}

@api.get('/notification-preferences')
def preferences(user=Depends(current_user),db=Depends(get_db)):
    row=db.get(NotificationPreference,user.id); return row.data if row else Preferences().model_dump()

@api.put('/notification-preferences')
def preferences_put(body:Preferences,user=Depends(current_user),db=Depends(get_db)):
    row=db.get(NotificationPreference,user.id)
    if row: row.data=body.model_dump()
    else: db.add(NotificationPreference(user_id=user.id,data=body.model_dump()))
    db.commit(); return body

@api.get('/discovery')
def discovery_status(user=Depends(current_user),db=Depends(get_db)):
    return [{'id':r.id,'status':r.status,'started_at':r.started_at,'finished_at':r.finished_at,'details':r.details} for r in db.scalars(select(DiscoveryRun).order_by(DiscoveryRun.started_at.desc()).limit(10))]

@api.post('/discovery')
def request_discovery(user=Depends(current_user),db=Depends(get_db)):
    if not(settings.greenhouse_boards or settings.lever_sites): raise HTTPException(503,'Configure GREENHOUSE_BOARDS or LEVER_SITES before discovering postings')
    rate_limit('discovery:global',1,300)
    tasks.enqueue(db,'discover',{},dedupe_key='discover',max_attempts=1); db.commit()
    return {'status':'queued'}

@api.get('/search-queries')
def search_queries(user=Depends(current_user),db=Depends(get_db)):
    _,p=profile_for(db,user.id)
    # Dynamic deterministic baseline, no invented profile details or open-position claims.
    fields=p.titles or p.skills or ['internship']
    return {'queries':[' '.join(str(v) for v in (field,'internship',p.season,p.graduation.year if p.graduation else None,p.standing_at_start, ' '.join(p.locations or [])) if v) for field in fields[:12]],'executed':False,'note':'Search-engine discovery is not configured. These are query suggestions, not discovered openings.'}

class AnalystQuery(__import__('pydantic').BaseModel):
    query: str = __import__('pydantic').Field(min_length=1,max_length=1000)

@api.post('/analyst')
def analyst(body:AnalystQuery,user=Depends(current_user),db=Depends(get_db)):
    # Extractive retrieval keeps every conclusion tied to a stored original posting.
    words=[w for w in body.query.split() if len(w)>3][:8]
    query=select(Job).where(Job.status=='open')
    from sqlalchemy import or_
    if words: query=query.where(or_(*[Job.text.ilike('%'+w.replace('%','').replace('_','')+'%') for w in words]))
    answers=[]
    for job in db.scalars(query.order_by(Job.retrieved_at.desc()).limit(8)):
        answers.append({'job_id':job.id,'company':job.company,'title':job.title,'url':job.url,'eligibility':evaluate_job(db,user.id,job)})
    db.commit()
    return {'answer':'Source-grounded results from the stored catalogue. Inspect each requirement before applying.' if answers else 'No stored postings match this query. This does not prove there are no openings.','citations':answers,'method':'extractive keyword retrieval; conversational reasoning is not yet implemented'}

@api.get('/account/export')
def export_account(user=Depends(current_user),db=Depends(get_db)):
    _,profile=profile_for(db,user.id)
    db.add(Audit(user_id=user.id,action='account.exported')); db.commit()
    return {'email':user.email,'profile':profile.model_dump(mode='json'),'resumes':[{'id':x.id,'filename':x.filename,'confirmed':x.confirmed,'document':decrypt(x.encrypted_document),'extraction':decrypt(x.encrypted_extraction),'extraction_status':x.extraction_status} for x in db.scalars(select(Resume).where(Resume.user_id==user.id))],'applications':applications(user,db),'notifications':notifications(user,db),'notification_preferences':preferences(user,db),'saved_jobs':[{'job_id':x.job_id,'hidden':x.hidden} for x in db.scalars(select(SavedJob).where(SavedJob.user_id==user.id))]}

@api.delete('/account')
def delete_account(response:Response,user=Depends(current_user),db=Depends(get_db)):
    # Explicit deletion is portable to SQLite tests as well as PostgreSQL CASCADE.
    for model in (AuthSession,Profile,Qualification,Resume,Evaluation,MatchScore,SavedJob,Application,Notification,NotificationPreference,EmailOutbox):
        db.execute(delete(model).where(model.user_id==user.id))
    db.execute(delete(Audit).where(Audit.user_id==user.id)); db.delete(db.get(User,user.id)); db.commit()
    clear_session_cookie(response); return {'ok':True}

app.include_router(api)
