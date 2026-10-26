from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

class ProfileData(BaseModel):
    full_name: str | None = Field(None, max_length=150)
    university: str | None = Field(None, max_length=255)
    degree: str | None = Field(None, max_length=100)
    major: str | None = Field(None, max_length=100)
    minor: str | None = Field(None, max_length=100)
    graduation: date | None = None
    standing: str | None = Field(None, max_length=80)
    standing_at_start: str | None = Field(None, max_length=80)
    standing_as_of: date | None = None
    target_start: date | None = None
    # Term (e.g. "Summer 2027") for which standing_at_start is confirmed.
    standing_term: str | None = Field(None, max_length=40)
    season: str | None = Field(None, max_length=100)
    gpa: float | None = Field(None, ge=0, le=4)
    skills: list[str] | None = None
    certifications: list[str] | None = None
    experience: list[str] | None = None
    projects: list[str] | None = None
    research: list[str] | None = None
    industries: list[str] | None = None
    titles: list[str] | None = None
    locations: list[str] | None = None
    arrangements: list[str] | None = None
    compensation_min: float | None = Field(None, ge=0)
    work_authorization: bool | None = None
    sponsorship_required: bool | None = None
    citizenship: str | None = Field(None, max_length=100)
    weights: dict[str, float] = Field(default_factory=lambda: {'skills': .30, 'projects': .20, 'experience': .20, 'academic': .15, 'certifications': .10, 'preferences': .05})
    @field_validator('weights')
    @classmethod
    def weights_valid(cls, v):
        if set(v) != {'skills','projects','experience','academic','certifications','preferences'} or any(x < 0 for x in v.values()) or abs(sum(v.values())-1) > .001:
            raise ValueError('Six nonnegative weights must sum to 1')
        return v
    @model_validator(mode='after')
    def bound_lists(self):
        for value in self.model_dump().values():
            if isinstance(value, list) and (len(value) > 100 or any(len(x)>2000 for x in value)):
                raise ValueError('Profile lists are limited to 100 entries of 2000 characters')
        return self

class RequirementData(BaseModel):
    kind: Literal['graduation','standing','degree','major','gpa','skills','work_authorization','sponsorship','citizenship','experience','other']
    mandatory: bool
    quote: str = Field(min_length=1)
    operator: Literal['between','one_of','all_of','minimum','equals','unspecified']
    values: list[str] = Field(default_factory=list)
    # Set by deterministic validation, never trusted from model output.
    origin: Literal['model','scanner','manual'] = 'model'
    note: str | None = None

class Extraction(BaseModel):
    requirements: list[RequirementData]
    complete: bool
    academic_scope_explicit: bool
    compensation: str | None = None
    deadline: date | None = None
    internship_start: date | None = None
    internship_end: date | None = None
    work_arrangement: str | None = None
    posting_date: date | None = None
    internship_term: str | None = None
    opportunity_type: Literal['internship','research','fellowship','event','mentorship','other']
    metadata_evidence: dict[str, str]

class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    @field_validator('email')
    @classmethod
    def email_valid(cls,v):
        import re
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',v): raise ValueError('Invalid email')
        return v.lower()
class ApplicationData(BaseModel):
    stage: Literal['Discovered','Saved','Applied','Assessment','Interview','Offer','Rejected']
    application_date: date | None = None
    resume_id: str | None = None
    notes: str = Field('',max_length=10000)
    interview_dates: list[datetime] = Field(default_factory=list)
    follow_up: date | None = None
    contacts: str = Field('',max_length=2000)
class Preferences(BaseModel):
    in_app: bool = True
    email: bool = False
    digest: Literal['daily','weekly'] = 'daily'
    preferred_companies: list[str] = Field(default_factory=list, max_length=100)
