import pytest
from sqlalchemy import select
from app import discovery
from app.schemas import Extraction
from app.db import Job,Requirement

def parsed():return Extraction(requirements=[{'kind':'skills','mandatory':True,'quote':'Python is required.','operator':'one_of','values':['Python']}],complete=True,academic_scope_explicit=False,opportunity_type='internship',metadata_evidence={})

def test_fabricated_evidence_rejected(monkeypatch):
    monkeypatch.setattr('app.ai.structured',lambda *a:parsed())
    from app.ai import extract_job
    with pytest.raises(ValueError,match='verbatim'):extract_job('No programming requirement provided.')

def test_metadata_requires_exact_evidence(monkeypatch):
    p=parsed();p.compensation='$50/hour';monkeypatch.setattr('app.ai.structured',lambda *a:p)
    from app.ai import extract_job
    with pytest.raises(ValueError,match='Metadata'):extract_job('Python is required.')

def seed(db,monkeypatch):
    monkeypatch.setattr(discovery,'extract_job',lambda text:parsed())
    record={'company':'Controlled Test','title':'Intern','location':None,'url':'https://example.com/test','text':'Python is required.'}
    discovery.persist(db,record,'greenhouse','test');db.commit();return record

def test_deduplication(db,monkeypatch):
    record=seed(db,monkeypatch);discovery.persist(db,record,'greenhouse','test');db.commit()
    assert len(list(db.scalars(select(Job))))==1 and len(list(db.scalars(select(Requirement))))==1

@pytest.mark.parametrize('failure,expected',[(True,'open'),(False,'closed')])
def test_closure_requires_successful_complete_feed(db,monkeypatch,failure,expected):
    seed(db,monkeypatch);monkeypatch.setattr(discovery.settings,'greenhouse_boards','test');monkeypatch.setattr(discovery.settings,'lever_sites','')
    def records(*a):
        if failure:raise ConnectionError('offline')
        return []
    monkeypatch.setattr(discovery,'records',records);monkeypatch.setattr(discovery.time,'sleep',lambda *a:None)
    discovery.discover(db);assert db.scalar(select(Job)).status==expected

@pytest.mark.parametrize('url',['http://127.0.0.1/','file:///etc/passwd','https://user:password@example.com','https://example.com:8080'])
def test_unsafe_urls_rejected(url):assert not discovery.valid_url(url)

def test_identifier_url_injection():
    with pytest.raises(ValueError):discovery.identifiers('../metadata?url=localhost')
