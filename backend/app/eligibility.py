"""Conservative, versioned eligibility rules. Unsupported semantics stay UNKNOWN."""
from datetime import date, datetime, timezone
from .schemas import ProfileData, RequirementData

ENGINE_VERSION = '1.0.0'

def standing_at(profile: ProfileData, start: date | None):
    if profile.standing_at_start and start and profile.target_start == start:
        return profile.standing_at_start.lower()
    # Graduation alone never proves academic standing or completed credits.
    if not start or not profile.standing or not profile.standing_as_of:
        return None
    if start == profile.standing_as_of:
        return profile.standing.lower()
    # No progression inferred for nontraditional students. Explicit target override required.
    return None

def evaluate_requirement(req: RequirementData, p: ProfileData, start: date | None = None):
    value = None
    passed = None
    reason = 'The available confirmed profile information cannot resolve this requirement.'
    vals = [v.casefold().strip() for v in req.values]
    try:
        if req.kind == 'graduation' and req.operator == 'between' and len(vals)==2:
            value = p.graduation
            if value: passed = date.fromisoformat(vals[0]) <= value <= date.fromisoformat(vals[1])
        elif req.kind == 'gpa' and req.operator == 'minimum' and len(vals)==1:
            value = p.gpa
            if value is not None: passed = value >= float(vals[0])
        elif req.kind in ('work_authorization','sponsorship') and req.operator == 'equals' and vals in (['true'],['false']):
            value = p.work_authorization if req.kind=='work_authorization' else p.sponsorship_required
            if value is not None: passed = value == (vals[0]=='true')
        elif req.kind in ('degree','major','citizenship','standing') and req.operator == 'one_of' and vals:
            value = standing_at(p,start) if req.kind=='standing' else getattr(p,req.kind)
            if value is not None:
                normalized = str(value).casefold().strip()
                if req.kind == 'degree':
                    aliases = {"bs":"bachelor", "b.s.":"bachelor", "ba":"bachelor", "b.a.":"bachelor", "bachelor's":"bachelor", "bachelor of science":"bachelor", "bachelor of arts":"bachelor", "ms":"master", "m.s.":"master", "master's":"master", "master of science":"master", "phd":"doctorate", "ph.d.":"doctorate", "associate's":"associate"}
                    normalized = aliases.get(normalized, normalized)
                    options = [aliases.get(v,v) for v in vals]
                    if normalized in options: passed = True
                    elif normalized in ('associate','bachelor','master','doctorate') and all(v in ('associate','bachelor','master','doctorate') for v in options): passed = False
                elif req.kind == 'standing':
                    if normalized in vals: passed = True
                    elif normalized in ('freshman','sophomore','junior','senior','rising sophomore','rising junior','rising senior') and all(v in ('freshman','sophomore','junior','senior','rising sophomore','rising junior','rising senior') for v in vals): passed = False
                elif normalized in vals: passed = True
                # Free-text differences in major/citizenship may be aliases, not a contradiction.

        elif req.kind == 'skills' and req.operator in ('one_of','all_of') and vals:
            value = p.skills
            if value is not None:
                known = {x.casefold().strip() for x in value}
                found = [v in known for v in vals]
                if (any(found) if req.operator=='one_of' else all(found)): passed = True
                # Missing skills in a non-exhaustive profile are UNKNOWN, never a contradiction.
        if passed is not None:
            reason = 'Confirmed profile data satisfies the stated rule.' if passed else 'Confirmed profile data contradicts the stated rule.'
    except (ValueError, TypeError, OverflowError):
        reason = 'The source rule could not be normalized safely; manual review is needed.'
    return {'kind':req.kind, 'mandatory':req.mandatory, 'quote':req.quote, 'student':str(value) if value is not None else 'Not provided', 'result':'PASS' if passed is True else 'FAIL' if passed is False else 'UNKNOWN', 'explanation':reason}

def evaluate(requirements, profile, *, accessible=True, complete=True, academic_scope_explicit=True, status='open', start=None, verified_at=None):
    results = [evaluate_requirement(r,profile,start) for r in requirements]
    mandatory = [r for r in results if r['mandatory']]
    reasons = []
    if not accessible or not complete or status != 'open' or not requirements:
        category = 'Unverified'
        reasons.append('Posting is closed, inaccessible, incomplete, or has no validated requirements.')
    elif any(r['result']=='FAIL' for r in mandatory): category = 'Ineligible'
    elif any(r['result']=='UNKNOWN' for r in mandatory) or not academic_scope_explicit or not mandatory:
        category = 'Potentially Eligible'
        if not academic_scope_explicit: reasons.append('Academic-year eligibility is not explicitly specified; no restriction has been invented.')
        if not mandatory: reasons.append('No explicit mandatory requirements were identified.')
    else: category = 'Verified Eligible'
    return {'status':category,'requirements':results,'disclosures':reasons,'engine_version':ENGINE_VERSION,'verified_at':verified_at or datetime.now(timezone.utc).isoformat()}
