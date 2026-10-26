"""Conservative, versioned eligibility rules. Unsupported semantics stay UNKNOWN."""
import calendar, re
from datetime import date, datetime, timezone
from .schemas import ProfileData, RequirementData

ENGINE_VERSION = '2.3.0'
# Only months that unambiguously belong to one term; boundary months (Apr, May, Aug, Dec) need an explicit term.
TERM_BY_MONTH = {1: 'spring', 2: 'spring', 3: 'spring', 6: 'summer', 7: 'summer', 9: 'fall', 10: 'fall', 11: 'fall'}

def normalize_term(value: str | None) -> str | None:
    m = re.fullmatch(r'\s*(spring|summer|fall|autumn)\s+(\d{4})\s*', (value or '').casefold())
    return f"{m.group(1).replace('autumn', 'fall')} {m.group(2)}" if m else None

def term_of(d: date | None) -> str | None:
    return f'{TERM_BY_MONTH[d.month]} {d.year}' if d and d.month in TERM_BY_MONTH else None

def standing_at(profile: ProfileData, start: date | None, term: str | None = None):
    """Student standing at the employer's internship start. Never uses the student's preferred date as a substitute."""
    if profile.standing_at_start:
        if start and profile.target_start == start: return profile.standing_at_start.lower()
        job_term = normalize_term(term) or term_of(start)
        student_term = normalize_term(profile.standing_term) or term_of(profile.target_start)
        if job_term and student_term and job_term == student_term: return profile.standing_at_start.lower()
    # Graduation alone never proves academic standing or completed credits.
    if start and profile.standing and profile.standing_as_of and start == profile.standing_as_of:
        return profile.standing.lower()
    # No progression inferred for nontraditional students.
    return None

def degree_level(value: str) -> str:
    """Map degree wording to one level only when exactly one level keyword is present."""
    levels = [lvl for lvl, pattern in (('associate', r'\bassociate'), ('bachelor', r'\bbachelor|\bundergraduate degree'), ('master', r'\bmaster|\bmba\b'), ('doctorate', r'\bph\.?d|\bdoctor'))
              if re.search(pattern, value)]
    return levels[0] if len(levels) == 1 else value

def graduation_result(grad: date, lo: date, hi: date):
    """Student graduation is month precision. A day-specific bound in the student's month stays unresolved."""
    g = (grad.year, grad.month)
    if g < (lo.year, lo.month) or g > (hi.year, hi.month): return False
    if g == (lo.year, lo.month) and lo.day != 1: return None
    if g == (hi.year, hi.month) and hi.day != calendar.monthrange(hi.year, hi.month)[1]: return None
    return True

def evaluate_requirement(req: RequirementData, p: ProfileData, start: date | None = None, term: str | None = None):
    value = None
    passed = None
    reason = req.note or 'The available confirmed profile information cannot resolve this requirement.'
    vals = [v.casefold().strip() for v in req.values]
    try:
        if req.kind == 'graduation' and req.operator == 'between' and len(vals)==2:
            value = p.graduation
            if value: passed = graduation_result(value, date.fromisoformat(vals[0]), date.fromisoformat(vals[1]))
        elif req.kind == 'gpa' and req.operator == 'minimum' and len(vals)==1:
            value = p.gpa
            if value is not None: passed = value >= float(vals[0])
        elif req.kind in ('work_authorization','sponsorship') and req.operator == 'equals' and vals in (['true'],['false']):
            value = p.work_authorization if req.kind=='work_authorization' else p.sponsorship_required
            if value is not None: passed = value == (vals[0]=='true')
        elif req.kind in ('degree','major','citizenship','standing') and req.operator == 'one_of' and vals:
            value = standing_at(p,start,term) if req.kind=='standing' else getattr(p,req.kind)
            if req.kind == 'standing' and value is None and p.standing_at_start:
                reason = 'Your confirmed standing is for a different or unspecified term than this internship; it is not carried over.'
            if value is not None:
                normalized = str(value).casefold().strip()
                if req.kind == 'degree':
                    aliases = {"bs":"bachelor", "b.s.":"bachelor", "ba":"bachelor", "b.a.":"bachelor", "bachelor's":"bachelor", "bachelor of science":"bachelor", "bachelor of arts":"bachelor", "ms":"master", "m.s.":"master", "master's":"master", "master of science":"master", "phd":"doctorate", "ph.d.":"doctorate", "associate's":"associate"}
                    normalized = degree_level(aliases.get(normalized, normalized))
                    options = [degree_level(aliases.get(v,v)) for v in vals]
                    if normalized in options: passed = True
                    elif normalized in ('associate','bachelor','master','doctorate') and all(v in ('associate','bachelor','master','doctorate') for v in options): passed = False
                elif req.kind == 'standing':
                    labels = ('freshman','sophomore','junior','senior','rising sophomore','rising junior','rising senior')
                    if normalized in vals: passed = True
                    # "Sophomores" (often meaning at application) and "rising junior" (at internship start) can describe the
                    # same student, so a confident FAIL requires both sides to use the same frame (rising vs plain labels).
                    elif normalized in labels and all(v in labels for v in vals) and all(v.startswith('rising') == normalized.startswith('rising') for v in vals): passed = False
                    elif normalized in labels and all(v in labels for v in vals):
                        reason = 'The posting and your confirmed standing use different conventions (e.g. "sophomore" vs "rising junior"); this is not treated as a failure.'
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
        elif req.kind == 'graduation' and value:
            reason = 'The stated bound falls within your graduation month; the exact day cannot be resolved.'
    except (ValueError, TypeError, OverflowError):
        reason = 'The source rule could not be normalized safely; manual review is needed.'
    return {'kind':req.kind, 'mandatory':req.mandatory, 'quote':req.quote, 'origin':req.origin, 'student':str(value) if value is not None else 'Not provided', 'result':'PASS' if passed is True else 'FAIL' if passed is False else 'UNKNOWN', 'explanation':reason}

def evaluate(requirements, profile, *, accessible=True, complete=True, academic_scope_explicit=True, status='open', start=None, term=None, validated=True, source_complete=True, extracted=False, verified_at=None):
    """complete: the extractor believes it captured every condition. Its doubt leaves information unresolved
    (Potentially Eligible at best); it does not make the posting itself unreliable. Unverified is reserved for
    sources that are inaccessible, stale, closed, truncated, or not (successfully) extracted. extracted=True with no
    requirements means the posting states none: Potentially Eligible with a disclosure, never Verified."""
    results = [evaluate_requirement(r,profile,start,term) for r in requirements]
    mandatory = [r for r in results if r['mandatory']]
    reasons = []
    if not accessible or status != 'open' or (not requirements and not extracted) or not source_complete:
        category = 'Unverified'
        if not accessible: reasons.append('The employer source could not be retrieved or has not been refreshed recently.')
        if status != 'open': reasons.append('The posting is closed at its source.')
        if not source_complete: reasons.append('The retrieved posting text appears truncated or incomplete.')
        if not requirements and not extracted: reasons.append('No source-validated requirements are available.')
    elif any(r['result']=='FAIL' for r in mandatory): category = 'Ineligible'
    elif any(r['result']=='UNKNOWN' for r in mandatory) or not academic_scope_explicit or not mandatory or not validated or not complete:
        category = 'Potentially Eligible'
        if not academic_scope_explicit: reasons.append('Academic-year eligibility is not explicitly specified; no restriction has been invented.')
        if not mandatory: reasons.append('No explicit mandatory requirements were identified in the posting.')
        if not validated: reasons.append('This extraction predates deterministic source validation; it cannot be verified.')
        if not complete: reasons.append('The extraction reported that it may not have captured every condition; review the full posting.')
        unresolved = sum(1 for r in mandatory if r['result']=='UNKNOWN')
        if unresolved: reasons.append(f'{unresolved} mandatory condition(s) remain unresolved.')
    else: category = 'Verified Eligible'
    return {'status':category,'requirements':results,'disclosures':reasons,'engine_version':ENGINE_VERSION,'verified_at':verified_at or datetime.now(timezone.utc).isoformat()}
