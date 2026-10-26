import pytest
from sqlalchemy import select
from app import discovery
from app.ai import AIOutputInvalid, AIUnavailable
from app.schemas import Extraction
from app.db import Job,Requirement,Task

def parsed():return Extraction(requirements=[{'kind':'skills','mandatory':True,'quote':'Python is required.','operator':'one_of','values':['Python']}],complete=True,academic_scope_explicit=False,opportunity_type='internship',metadata_evidence={})
PROVENANCE={'provider':'test','model':'test','prompt_version':'t','hosted':False}

def test_fabricated_evidence_rejected(monkeypatch):
    monkeypatch.setattr('app.ai.structured',lambda *a:(parsed(),PROVENANCE))
    from app.ai import extract_job
    with pytest.raises(AIOutputInvalid,match='verbatim'):extract_job('No programming requirement provided.')

def test_metadata_without_exact_evidence_is_dropped(monkeypatch):
    p=parsed();p.compensation='$50/hour';monkeypatch.setattr('app.ai.structured',lambda *a:(p,PROVENANCE))
    from app.ai import extract_job
    result,provenance=extract_job('Python is required.')
    assert result.compensation is None and provenance['quality']['metadata_dropped']==['compensation']

def seed(db,monkeypatch):
    monkeypatch.setattr(discovery,'extract_job',lambda text,title=None:(parsed(),{**PROVENANCE,'quality':{'validator_version':'test'}}))
    record={'company':'Controlled Test','title':'Intern','location':None,'url':'https://example.com/test','text':'Python is required.'}
    job=discovery.persist(db,record,'greenhouse','test');db.commit()
    assert discovery.extract_posting(db,job.id,job.content_hash)=='ok';db.commit()
    return record

def test_persist_enqueues_extraction_once(db,monkeypatch):
    record={'company':'Controlled Test','title':'Intern','location':None,'url':'https://example.com/test','text':'Python is required.'}
    discovery.persist(db,record,'greenhouse','test');discovery.persist(db,record,'greenhouse','test');db.commit()
    assert [t.kind for t in db.scalars(select(Task))]==['extract_job']
    assert db.scalar(select(Job)).details['extraction_status']=='pending'

def test_deduplication(db,monkeypatch):
    record=seed(db,monkeypatch);discovery.persist(db,record,'greenhouse','test');db.commit()
    assert len(list(db.scalars(select(Job))))==1 and len(list(db.scalars(select(Requirement))))==1

def test_ai_outage_is_retryable_and_leaves_posting_unextracted(db,monkeypatch):
    record={'company':'Controlled Test','title':'Intern','location':None,'url':'https://example.com/test','text':'Python is required.'}
    job=discovery.persist(db,record,'greenhouse','test');db.commit()
    def down(text,title=None):raise AIUnavailable('Local AI runtime is not reachable')
    monkeypatch.setattr(discovery,'extract_job',down)
    with pytest.raises(AIUnavailable):discovery.extract_posting(db,job.id,job.content_hash)
    assert job.extraction_complete is False

def test_invalid_model_output_recorded_not_stored(db,monkeypatch):
    record={'company':'Controlled Test','title':'Intern','location':None,'url':'https://example.com/test','text':'Python is required.'}
    job=discovery.persist(db,record,'greenhouse','test');db.commit()
    def bad(text,title=None):raise AIOutputInvalid('schema validation failed')
    monkeypatch.setattr(discovery,'extract_job',bad)
    assert discovery.extract_posting(db,job.id,job.content_hash)=='invalid'
    assert job.extraction_complete is False and 'unverified' in job.extraction_error and not list(db.scalars(select(Requirement)))

@pytest.mark.parametrize('failure,expected,access',[(True,'open','inaccessible'),(False,'closed','ok')])
def test_closure_requires_successful_complete_feed(db,monkeypatch,failure,expected,access):
    seed(db,monkeypatch);monkeypatch.setattr(discovery.settings,'greenhouse_boards','test');monkeypatch.setattr(discovery.settings,'lever_sites','')
    def records(*a):
        if failure:raise ConnectionError('offline')
        return []
    monkeypatch.setattr(discovery,'records',records);monkeypatch.setattr(discovery.time,'sleep',lambda *a:None)
    discovery.discover(db);job=db.scalar(select(Job))
    assert job.status==expected and job.access_status==access

@pytest.mark.parametrize('url',['http://127.0.0.1/','file:///etc/passwd','https://user:password@example.com','https://example.com:8080'])
def test_unsafe_urls_rejected(url):assert not discovery.valid_url(url)

def test_identifier_url_injection():
    with pytest.raises(ValueError):discovery.identifiers('../metadata?url=localhost')
