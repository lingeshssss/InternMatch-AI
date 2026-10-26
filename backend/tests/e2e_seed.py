"""Seed controlled postings into a disposable end-to-end database (never the development catalogue).

Usage: DATABASE_URL=...internmatch_e2e ../.venv/bin/python -m tests.e2e_seed
"""
import hashlib, os, sys
from sqlalchemy import select, delete
from app.db import Session, Company, Job, Evidence, Requirement, now

if not os.environ.get('DATABASE_URL', '').rsplit('/', 1)[-1].startswith('internmatch_e2e'):
    sys.exit('Refusing to seed: DATABASE_URL must name an internmatch_e2e* database')

VALIDATED = {'provider': 'controlled-fixture', 'model': 'none', 'prompt_version': 'fixture', 'quality': {'validator_version': 'fixture'}}
POSTINGS = [
    ('e2e-verified', 'E2E Verified-Path Internship', 'ok', 'Summer 2027',
     [('graduation', ['2029-12-01', '2031-06-30'], 'between', 'Must graduate between December 2029 and June 2031.'),
      ('work_authorization', ['true'], 'equals', 'Must be authorized to work in the United States.')]),
    ('e2e-mismatch', 'E2E Academic Mismatch Internship', 'ok', 'Summer 2027',
     [('standing', ['rising junior', 'rising senior'], 'one_of', 'Open to rising juniors and rising seniors only.')]),
    ('e2e-inaccessible', 'E2E Inaccessible Source Internship', 'inaccessible', 'Summer 2027',
     [('graduation', ['2029-12-01', '2031-06-30'], 'between', 'Must graduate between December 2029 and June 2031.')]),
]

with Session() as db:
    company = db.scalar(select(Company).where(Company.name == 'Controlled Test Employer')) or Company(name='Controlled Test Employer')
    db.add(company); db.flush()
    for job_id, title, access, term, reqs in POSTINGS:
        db.execute(delete(Job).where(Job.id == job_id))
        text = f'{title} ({term}). Controlled end-to-end test fixture, not a real opening.\n' + '\n'.join(q for *_, q in reqs)
        digest = hashlib.sha256(text.encode()).hexdigest()
        job = Job(id=job_id, company_id=company.id, company=company.name, title=title, location='Test City', url=f'https://example.com/controlled/{job_id}',
                  source='controlled_test', source_key='e2e', text=text, content_hash=digest, access_status=access, extraction_complete=True, retrieved_at=now(),
                  details={'academic_scope_explicit': True, 'internship_term': term, 'opportunity_type': 'internship', 'extraction_status': 'ready', 'provenance': VALIDATED,
                           'metadata_evidence': {'internship_term': term}})
        db.add(job); db.flush()
        for kind, values, operator, quote in reqs:
            start = text.index(quote)
            e = Evidence(job_id=job_id, quote=quote, start=start, end=start + len(quote), content_hash=digest, source_url=job.url); db.add(e); db.flush()
            db.add(Requirement(job_id=job_id, evidence_id=e.id, data={'kind': kind, 'values': values, 'operator': operator, 'quote': quote, 'mandatory': True, 'origin': 'model', 'note': None}))
    db.commit()
print('Seeded', len(POSTINGS), 'controlled postings')
