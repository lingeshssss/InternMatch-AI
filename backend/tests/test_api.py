from sqlalchemy import select
from app.db import Company,Job,Requirement,Evidence,Profile,Resume
from app.security import encrypt,decrypt
from app.services import notify

def register(client,email='student@example.com'):
    r=client.post('/api/auth/register',json={'email':email,'password':'correct horse battery staple'})
    assert r.status_code==200,r.text
    return r.json()

def seed(db):
    c=Company(name='Controlled Test Employer');db.add(c);db.flush()
    job=Job(id='test-job',company_id=c.id,company=c.name,title='Summer Software Internship',location='New Brunswick',url='https://example.com/controlled-test',source='controlled_test',source_key='tests',text='Must graduate between December 2029 and June 2031.',content_hash='testhash',details={'academic_scope_explicit':True,'provenance':{'quality':{'validator_version':'test'}}},extraction_complete=True)
    db.add(job);db.flush()
    e=Evidence(job_id=job.id,quote=job.text,start=0,end=len(job.text),content_hash='testhash',source_url=job.url);db.add(e);db.flush()
    db.add(Requirement(job_id=job.id,evidence_id=e.id,data={'kind':'graduation','values':['2029-12-01','2031-06-30'],'operator':'between','mandatory':True,'quote':job.text}));db.commit();return job

def test_auth_csrf_and_logout(client):
    assert client.get('/api/profile').status_code==401
    assert client.post('/api/auth/register',headers={'Origin':'https://attacker.example'},json={}).status_code==403
    register(client);assert client.get('/api/auth/me').status_code==200
    client.post('/api/auth/logout');assert client.get('/api/profile').status_code==401
    assert client.post('/api/auth/login',json={'email':'student@example.com','password':'correct horse battery staple'}).status_code==200

def test_profile_encryption_unknowns(client,db):
    u=register(client);assert client.put('/api/profile',json={'university':'Rutgers','graduation':'2030-05-01'}).status_code==200
    p=client.get('/api/profile').json();assert p['degree'] is None and p['work_authorization'] is None
    ciphertext=db.get(Profile,u['id']).encrypted_data;assert 'Rutgers' not in ciphertext and decrypt(ciphertext)['university']=='Rutgers'

def test_strict_search_filters_evidence(client,db):
    register(client);seed(db)
    assert client.get('/api/jobs').json()['items']==[]
    assert client.get('/api/jobs?mode=potential').json()['items'][0]['eligibility']['status']=='Potentially Eligible'
    client.put('/api/profile',json={'graduation':'2030-05-01'})
    data=client.get('/api/jobs').json();assert len(data['items'])==1 and data['counts']['Verified Eligible']==1
    assert client.get('/api/jobs?company=other').json()['items']==[]
    assert client.get('/api/jobs?mode=invalid').status_code==422
    detail=client.get('/api/jobs/test-job').json();assert detail['text']==detail['eligibility']['requirements'][0]['quote']

def test_application_and_saved_job_isolation(client,db):
    register(client);seed(db)
    assert client.put('/api/applications/test-job',json={'stage':'Applied','notes':'private note'}).status_code==200
    client.put('/api/jobs/test-job/saved');client.post('/api/auth/logout');register(client,'bob@example.com')
    assert client.get('/api/applications').json()==[] and client.get('/api/account/export').json()['applications']==[]
    assert client.get('/api/jobs?mode=explore').json()['items'][0]['saved'] is False

def test_resume_owner_and_confirmation(client,db):
    u=register(client)
    r=Resume(user_id=u['id'],filename='controlled.pdf',encrypted_document=encrypt({'base64':'dGVzdA=='}),encrypted_extraction=encrypt({'skills':['Python']}));db.add(r);db.commit()
    assert client.get('/api/profile').json()['skills'] is None
    client.post('/api/auth/logout');register(client,'bob@example.com')
    assert client.post('/api/resumes/'+r.id+'/confirm',json={'skills':['Python']}).status_code==404
    assert client.get('/api/resumes/'+r.id+'/download').status_code==404
    client.post('/api/auth/logout');client.post('/api/auth/login',json={'email':'student@example.com','password':'correct horse battery staple'})
    assert client.post('/api/resumes/'+r.id+'/confirm',json={'skills':['Python']}).status_code==200
    assert client.get('/api/profile').json()['skills']==['Python']

def test_notification_dedup_and_ownership(client,db):
    u=register(client);assert notify(db,u['id'],'unique',{'type':'eligible'}) is True
    assert notify(db,u['id'],'unique',{'type':'eligible'}) is False
    db.commit();notice=client.get('/api/notifications').json()[0]
    client.post('/api/auth/logout');register(client,'bob@example.com')
    assert client.get('/api/notifications').json()==[] and client.put('/api/notifications/'+notice['id']+'/read').status_code==404

def test_account_deletion(client,db):
    register(client);seed(db);client.put('/api/profile',json={'university':'Rutgers'});client.put('/api/applications/test-job',json={'stage':'Saved'})
    assert client.delete('/api/account').status_code==200 and client.get('/api/auth/me').status_code==401
    assert client.post('/api/auth/login',json={'email':'student@example.com','password':'correct horse battery staple'}).status_code==401

def test_mislabeled_upload_rejected(client):
    register(client);assert client.post('/api/resumes',files={'file':('bad.pdf',b'<script>bad</script>','application/pdf')}).status_code==422

def test_invalid_weights_rejected(client):
    register(client);assert client.put('/api/profile',json={'weights':{'skills':1}}).status_code==422

def test_closure_and_reopening_refresh_cached_decision(client,db):
    from datetime import timedelta
    from app.db import now
    register(client);job=seed(db);client.put('/api/profile',json={'graduation':'2030-05-01'})
    assert client.get('/api/jobs/test-job').json()['eligibility']['status']=='Verified Eligible'
    job.status='closed';db.commit()
    assert client.get('/api/jobs/test-job').json()['eligibility']['status']=='Unverified'
    job.status='open';job.retrieved_at=now()+timedelta(seconds=1);db.commit()
    assert client.get('/api/jobs/test-job').json()['eligibility']['status']=='Verified Eligible'

def test_stale_posting_cannot_remain_verified(client,db):
    from datetime import timedelta
    from app.db import now
    register(client);job=seed(db);client.put('/api/profile',json={'graduation':'2030-05-01'})
    assert client.get('/api/jobs/test-job').json()['eligibility']['status']=='Verified Eligible'
    job.retrieved_at=now()-timedelta(days=3);db.commit()
    assert client.get('/api/jobs/test-job').json()['eligibility']['status']=='Unverified'
