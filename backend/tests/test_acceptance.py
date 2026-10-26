"""Required acceptance cases A-F, end to end where the API is involved."""
from datetime import date, timedelta
from app.eligibility import evaluate, evaluate_requirement
from app.schemas import ProfileData, RequirementData
from app.db import Company, Job, Evidence, Requirement, MatchScore, now
from app.security import encrypt

def req(kind, values, operator='one_of', mandatory=True, quote='Controlled employer requirement.'):
    return RequirementData(kind=kind, values=values, operator=operator, mandatory=mandatory, quote=quote)

GRAD = req('graduation', ['2029-12-01', '2031-06-30'], 'between', quote='Must graduate between December 2029 and June 2031.')
STANDING = req('standing', ['rising junior', 'rising senior'], quote='Open to rising juniors and rising seniors.')
AUTH = req('work_authorization', ['true'], 'equals', quote='Must be authorized to work in the United States.')

def test_a_may_2030_inside_december_2029_to_june_2031():
    assert evaluate_requirement(GRAD, ProfileData(graduation=date(2030, 5, 1)))['result'] == 'PASS'

def test_a_month_precision_boundaries():
    assert evaluate_requirement(GRAD, ProfileData(graduation=date(2029, 12, 1)))['result'] == 'PASS'
    assert evaluate_requirement(GRAD, ProfileData(graduation=date(2031, 6, 1)))['result'] == 'PASS'
    assert evaluate_requirement(GRAD, ProfileData(graduation=date(2031, 7, 1)))['result'] == 'FAIL'
    day_bound = req('graduation', ['2029-12-01', '2031-06-15'], 'between')
    assert evaluate_requirement(day_bound, ProfileData(graduation=date(2031, 6, 1)))['result'] == 'UNKNOWN'

def test_b_confirmed_rising_sophomore_fails_rising_junior_senior_for_same_term():
    p = ProfileData(standing_at_start='rising sophomore', standing_term='Summer 2027')
    r = evaluate_requirement(STANDING, p, start=None, term='Summer 2027')
    assert r['result'] == 'FAIL'
    assert evaluate([STANDING, GRAD], p.model_copy(update={'graduation': date(2030, 5, 1)}), term='Summer 2027')['status'] == 'Ineligible'

def test_b_standing_tied_to_actual_internship_date_not_preference():
    p = ProfileData(standing_at_start='rising sophomore', target_start=date(2027, 6, 1))
    # Employer start unknown: the student's preferred date is never substituted.
    assert evaluate_requirement(STANDING, p, start=None, term=None)['result'] == 'UNKNOWN'
    # Different internship year: confirmed standing does not carry over.
    assert evaluate_requirement(STANDING, p, start=date(2028, 6, 1))['result'] == 'UNKNOWN'
    # Same unambiguous summer term from the employer's evidenced start date.
    assert evaluate_requirement(STANDING, p, start=date(2027, 6, 15))['result'] == 'FAIL'
    # Boundary month (May) is ambiguous between terms without an explicit term.
    assert evaluate_requirement(STANDING, p, start=date(2027, 5, 20))['result'] == 'UNKNOWN'

def test_b_graduation_year_never_implies_standing():
    p = ProfileData(graduation=date(2030, 5, 1))
    assert evaluate_requirement(STANDING, p, term='Summer 2027')['result'] == 'UNKNOWN'

def test_c_unknown_authorization_stays_unknown():
    r = evaluate([AUTH, GRAD], ProfileData(graduation=date(2030, 5, 1)))
    assert r['requirements'][0]['result'] == 'UNKNOWN' and r['status'] == 'Potentially Eligible'

def test_e_missing_academic_restriction_not_invented():
    r = evaluate([req('skills', ['Python'], quote='Python is required.')], ProfileData(skills=['Python']), academic_scope_explicit=False)
    assert r['status'] == 'Potentially Eligible' and len(r['requirements']) == 1
    assert any('not explicitly specified' in d for d in r['disclosures'])

def seed_job(db, *, access='ok', requirements=(GRAD,), scope=True):
    c = Company(name='Acceptance Employer'); db.add(c); db.flush()
    text = ' '.join(r.quote for r in requirements)
    job = Job(id='acc-job', company_id=c.id, company=c.name, title='Software Internship', location=None, url='https://example.com/acc', source='controlled_test', source_key='t',
              text=text, content_hash='acc', details={'academic_scope_explicit': scope, 'provenance': {'quality': {'validator_version': 'test'}}}, extraction_complete=True, access_status=access)
    db.add(job); db.flush()
    for r in requirements:
        e = Evidence(job_id=job.id, quote=r.quote, start=text.index(r.quote), end=text.index(r.quote) + len(r.quote), content_hash='acc', source_url=job.url); db.add(e); db.flush()
        db.add(Requirement(job_id=job.id, evidence_id=e.id, data=r.model_dump()))
    db.commit(); return job

def register(client):
    r = client.post('/api/auth/register', json={'email': 'acceptance@example.com', 'password': 'correct horse battery staple'}); assert r.status_code == 200
    return r.json()

def test_d_strong_fit_never_overrides_academic_failure(client, db):
    u = register(client); job = seed_job(db)
    client.put('/api/profile', json={'graduation': '2032-05-01', 'skills': ['Python']})
    from app.db import Profile
    db.add(MatchScore(user_id=u['id'], job_id=job.id, profile_version=db.get(Profile, u['id']).version, content_hash=job.content_hash, encrypted_data=encrypt({'score': 99.0})))
    db.commit()
    detail = client.get('/api/jobs/acc-job').json()
    assert detail['eligibility']['status'] == 'Ineligible'
    assert client.get('/api/jobs?mode=strict&sort=fit').json()['items'] == []
    assert client.get('/api/jobs?mode=potential&sort=fit').json()['items'] == []
    explore = client.get('/api/jobs?mode=explore&sort=fit').json()['items']
    assert explore[0]['fit']['score'] == 99.0 and explore[0]['eligibility']['status'] == 'Ineligible'

def test_f_inaccessible_posting_is_unverified(client, db):
    register(client); seed_job(db, access='inaccessible')
    client.put('/api/profile', json={'graduation': '2030-05-01'})
    r = client.get('/api/jobs/acc-job').json()['eligibility']
    assert r['status'] == 'Unverified' and any('could not be retrieved' in d for d in r['disclosures'])

def test_unvalidated_extraction_cannot_be_verified(client, db):
    register(client); job = seed_job(db); job.details = {'academic_scope_explicit': True}; db.commit()
    client.put('/api/profile', json={'graduation': '2030-05-01'})
    r = client.get('/api/jobs/acc-job').json()['eligibility']
    assert r['status'] == 'Potentially Eligible' and any('predates deterministic source validation' in d for d in r['disclosures'])

def test_verified_requires_fresh_open_validated_complete_source(client, db):
    register(client); job = seed_job(db)
    client.put('/api/profile', json={'graduation': '2030-05-01'})
    assert client.get('/api/jobs/acc-job').json()['eligibility']['status'] == 'Verified Eligible'
    job.retrieved_at = now() - timedelta(days=3); db.commit()
    assert client.get('/api/jobs/acc-job').json()['eligibility']['status'] == 'Unverified'

def test_mixed_standing_conventions_are_not_a_confident_failure():
    plain = req('standing', ['sophomore'], quote='Open to current sophomores.')
    p = ProfileData(standing_at_start='rising junior', standing_term='Summer 2027')
    assert evaluate_requirement(plain, p, term='Summer 2027')['result'] == 'UNKNOWN'
    assert evaluate_requirement(req('standing', ['junior', 'senior']), ProfileData(standing_at_start='sophomore', standing_term='Summer 2027'), term='Summer 2027')['result'] == 'FAIL'
