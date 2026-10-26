"""Public ATS APIs only. No arbitrary-URL fetching, redirects, or access-control bypass."""
import hashlib, html, re, time, ipaddress
from html.parser import HTMLParser
from urllib.parse import urlsplit
import httpx
from sqlalchemy import select, delete
from .db import Company, Job, Requirement, Evidence, DiscoveryRun, JobSource, now
from .ai import extract_job
from .config import settings

class TextParser(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]; self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'): self.skip+=1
        if tag in ('p','br','li','div','h1','h2','h3'): self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'): self.skip=max(0,self.skip-1)
        if tag in ('p','li','div'): self.parts.append('\n')
    def handle_data(self,data):
        if not self.skip: self.parts.append(data)
def clean_html(value):
    parser=TextParser(); parser.feed(html.unescape(value))
    return '\n'.join(x.strip() for x in ''.join(parser.parts).splitlines() if x.strip())
def valid_url(url):
    try:
        p=urlsplit(url)
        if not (p.scheme=='https' and p.hostname and not p.username and not p.password and not p.fragment and p.port in (None,443)): return False
        host=p.hostname.lower()
        if host in ('localhost','metadata.google.internal') or host.endswith(('.localhost','.local','.internal')): return False
        try:
            if not ipaddress.ip_address(host).is_global: return False
        except ValueError: pass
        return True
    except ValueError: return False
def identifiers(value):
    result=[x.strip() for x in value.split(',') if x.strip()]
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',x) for x in result): raise ValueError('Invalid ATS identifier')
    return result

def fetch(client,url):
    # Call sites construct host and path exclusively from validated operator settings.
    for attempt in range(3):
        r=client.get(url)
        if r.status_code in (429,500,502,503,504) and attempt<2:
            time.sleep(min(2**attempt,4)); continue
        r.raise_for_status()
        if len(r.content)>15_000_000: raise ValueError('Feed too large')
        return r.json()

def records(client,kind,key):
    if kind=='greenhouse':
        data=fetch(client,f'https://boards-api.greenhouse.io/v1/boards/{key}/jobs?content=true')
        return [{'external_id':str(x['id']),'title':x['title'],'company':key,'location':x.get('location',{}).get('name'),'url':x['absolute_url'],'text':clean_html(x.get('content',''))} for x in data['jobs']]
    data=fetch(client,f'https://api.lever.co/v0/postings/{key}?mode=json')
    return [{'external_id':x['id'],'title':x['text'],'company':key,'location':x.get('categories',{}).get('location'),'url':x['hostedUrl'],'text':clean_html(x.get('description','')+'\n'+'\n'.join(y.get('text','')+'\n'+y.get('content','') for y in x.get('lists',[]))+'\n'+x.get('additional',''))} for x in data]

def persist(db,record,kind,key):
    if not valid_url(record['url']): raise ValueError('Unsafe application URL')
    url=record['url'].split('?')[0].rstrip('/')
    job=db.scalar(select(Job).where(Job.url==url))
    content_hash=hashlib.sha256(record['text'].encode()).hexdigest()
    changed=job is None or job.content_hash!=content_hash
    if job is None:
        company=db.scalar(select(Company).where(Company.name==record['company']))
        if not company:
            company=Company(name=record['company']); db.add(company); db.flush()
        job=Job(id=hashlib.sha256(url.encode()).hexdigest(),company_id=company.id,company=record['company'],title=record['title'],location=record['location'],url=url,source=kind,source_key=key,text=record['text'],content_hash=content_hash,details={})
        db.add(job); db.flush()
    job.retrieved_at=now(); job.status='open'
    source=db.scalar(select(JobSource).where(JobSource.job_id==job.id,JobSource.source==kind,JobSource.source_key==key))
    if not source: db.add(JobSource(job_id=job.id,source=kind,source_key=key))
    else: source.last_seen_at=now()
    if changed or not job.extraction_complete:
        job.title=record['title']; job.location=record['location']; job.text=record['text']; job.content_hash=content_hash
        db.execute(delete(Requirement).where(Requirement.job_id==job.id))
        db.execute(delete(Evidence).where(Evidence.job_id==job.id))
        job.extraction_complete=False; job.details={}
        try:
            extracted=extract_job(job.text)
            job.details=extracted.model_dump(mode='json',exclude={'requirements'})
            for req in extracted.requirements:
                start=job.text.index(req.quote)
                evidence=Evidence(job_id=job.id,quote=req.quote,start=start,end=start+len(req.quote),content_hash=content_hash,source_url=url)
                db.add(evidence); db.flush()
                db.add(Requirement(job_id=job.id,evidence_id=evidence.id,data=req.model_dump()))
            job.extraction_complete=extracted.complete
            job.extraction_error=None
        except Exception as exc:
            # Do not store provider error bodies, which may contain document or credential data.
            job.extraction_error=type(exc).__name__+': requirement extraction unavailable; posting remains unverified'
    return job

def discover(db):
    run=DiscoveryRun(details={}); db.add(run); db.commit()
    outcomes=[]
    for kind,keys in [('greenhouse',identifiers(settings.greenhouse_boards)),('lever',identifiers(settings.lever_sites))]:
        for key in keys:
            try:
                with httpx.Client(timeout=30,follow_redirects=False,headers={'User-Agent':'InternMatchAI/1.0 (public ATS feed reader)'}) as client:
                    items=records(client,kind,key)
                seen=set(); count=0
                for record in items:
                    # Keep original source available; source refresh also identifies closed positions.
                    if not re.search(r'\bintern(ship)?\b|undergraduate research|fellowship',record['title'],re.I): continue
                    job=persist(db,record,kind,key); seen.add(job.id); count+=1
                # Absence is closure evidence only after a complete successful feed response.
                for job in db.scalars(select(Job).where(Job.source==kind,Job.source_key==key)):
                    if job.id not in seen: job.status='closed'; job.retrieved_at=now()
                db.commit(); outcomes.append({'source':kind,'key':key,'status':'ok','postings':count})
            except Exception as exc:
                db.rollback(); outcomes.append({'source':kind,'key':key,'status':'failed','error_type':type(exc).__name__})
            time.sleep(1)
    run=db.get(DiscoveryRun,run.id); run.finished_at=now(); run.status='failed' if any(x['status']=='failed' for x in outcomes) else 'complete'
    run.details={'sources':outcomes,'configured':bool(outcomes)}; db.commit()
    return run
