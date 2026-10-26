from datetime import date
import pytest
from app.eligibility import evaluate,evaluate_requirement,standing_at
from app.schemas import ProfileData,RequirementData

def req(kind,values,operator='one_of',mandatory=True):return RequirementData(kind=kind,values=values,operator=operator,mandatory=mandatory,quote='Controlled employer requirement.')
@pytest.mark.parametrize('graduation,expected',[('2030-05-01','PASS'),('2029-12-01','PASS'),('2031-06-30','PASS'),('2029-11-30','FAIL'),('2031-07-01','FAIL')])
def test_graduation_window(graduation,expected):
    assert evaluate_requirement(req('graduation',['2029-12-01','2031-06-30'],'between'),ProfileData(graduation=date.fromisoformat(graduation)))['result']==expected

def test_rising_sophomore_fails_junior_only():
    p=ProfileData(standing_at_start='rising sophomore',target_start=date(2027,6,1),skills=['Java','Python'])
    result=evaluate([req('standing',['rising junior','rising senior']),req('skills',['Java'])],p,start=p.target_start)
    assert result['status']=='Ineligible'

def test_freshman_explicit():
    p=ProfileData(standing='freshman',standing_as_of=date(2026,10,1))
    assert evaluate_requirement(req('standing',['freshman','sophomore']),p,p.standing_as_of)['result']=='PASS'

def test_graduation_does_not_prove_standing():assert standing_at(ProfileData(graduation=date(2030,5,1)),date(2027,6,1)) is None

def test_override_date_scope():
    assert standing_at(ProfileData(standing_at_start='rising sophomore',target_start=date(2027,6,1)),date(2028,6,1)) is None

@pytest.mark.parametrize('value,expected',[(None,'UNKNOWN'),(True,'PASS'),(False,'FAIL')])
def test_authorization(value,expected):assert evaluate_requirement(req('work_authorization',['true'],'equals'),ProfileData(work_authorization=value))['result']==expected

@pytest.mark.parametrize('gpa,expected',[(3.0,'PASS'),(2.99,'FAIL'),(0,'FAIL'),(None,'UNKNOWN')])
def test_gpa(gpa,expected):assert evaluate_requirement(req('gpa',['3.0'],'minimum'),ProfileData(gpa=gpa))['result']==expected

def test_missing_academic_restriction_not_invented():
    result=evaluate([req('skills',['Python'])],ProfileData(skills=['Python']),academic_scope_explicit=False)
    assert result['status']=='Potentially Eligible' and len(result['requirements'])==1 and result['disclosures']

@pytest.mark.parametrize('flag',[{'accessible':False},{'source_complete':False},{'status':'closed'}])
def test_unreliable_or_closed_source(flag):assert evaluate([req('skills',['Python'])],ProfileData(skills=['Python']),**flag)['status']=='Unverified'

def test_extractor_doubt_is_unresolved_not_unverified():
    p=ProfileData(gpa=3.5)
    assert evaluate([req('gpa',['3.0'],'minimum')],p,complete=False)['status']=='Potentially Eligible'
    # A confirmed mandatory failure is still a confirmed failure.
    assert evaluate([req('gpa',['3.8'],'minimum')],p,complete=False)['status']=='Ineligible'

@pytest.mark.parametrize('degree,options,expected',[("Bachelor's degree",["bachelor's degree"],'PASS'),('B.S. in Computer Science',["master's degree"],'UNKNOWN'),('Bachelor of Science',["Master's or PhD"],'UNKNOWN'),('Bachelor of Science',["master's",'phd'],'FAIL')])
def test_degree_wording_normalized_by_level(degree,options,expected):
    assert evaluate_requirement(req('degree',options),ProfileData(degree=degree))['result']==expected

def test_no_requirements_not_vacuously_verified():assert evaluate([],ProfileData())['status']=='Unverified'

def test_unsupported_semantics_unknown():assert evaluate_requirement(req('other',['Prior experience'],'unspecified'),ProfileData(experience=['Worked']))['result']=='UNKNOWN'

def test_missing_skill_is_not_known_failure():assert evaluate_requirement(req('skills',['C++']),ProfileData(skills=['Python']))['result']=='UNKNOWN'

@pytest.mark.parametrize('degree,expected',[(None,'UNKNOWN'),("bachelor's",'PASS'),("associate's",'FAIL')])
def test_degree(degree,expected):assert evaluate_requirement(req('degree',["bachelor's"]),ProfileData(degree=degree))['result']==expected

def test_preference_does_not_disqualify():assert evaluate([req('gpa',['3.0'],'minimum'),req('degree',["master's"],mandatory=False)],ProfileData(gpa=3.5,degree="bachelor's"))['status']=='Verified Eligible'

def test_contradictory_mandatory_rules():assert evaluate([req('gpa',['3'],'minimum'),req('graduation',['2028-01-01','2029-01-01'],'between')],ProfileData(gpa=4,graduation=date(2030,5,1)))['status']=='Ineligible'

def test_degree_alias_is_not_false_disqualification():
    assert evaluate_requirement(req('degree',["bachelor's"]),ProfileData(degree='Bachelor of Science'))['result']=='PASS'

def test_unknown_degree_wording_stays_unknown():
    assert evaluate_requirement(req('degree',['equivalent qualification']),ProfileData(degree='Bachelor of Science'))['result']=='UNKNOWN'

def test_major_alias_not_false_failure():
    assert evaluate_requirement(req('major',['computer science']),ProfileData(major='CS'))['result']=='UNKNOWN'
