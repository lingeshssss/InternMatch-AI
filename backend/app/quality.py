"""Deterministic validation of model extractions against the source text.

A model can return well-formed JSON that misreads, omits or invents conditions. These checks
convert anything not supported by the exact source wording into UNKNOWN (kind other /
operator unspecified) rather than PASS or FAIL, and add unreviewed eligibility-signal
sentences as unresolved mandatory conditions. They make verification more conservative;
they cannot prove an extraction correct.
"""
import re
from datetime import date
from .schemas import Extraction, ProfileData, RequirementData

VALIDATOR_VERSION = '1.0.0'
MONTHS = ['january','february','march','april','may','june','july','august','september','october','november','december']
STANDINGS = {'freshman','rising sophomore','sophomore','rising junior','junior','rising senior','senior'}
# Wording that introduces alternatives, exceptions or discretion the rules engine cannot represent.
NESTED = re.compile(r'\b(unless|except|exception|equivalent|waive[ds]?|waiver|case[- ]by[- ]case|may be considered|considered on|or other|in lieu|alternatively|depending on)\b', re.I)
PREFERENCE = re.compile(r'\b(prefer(red|ably)?|nice to have|a plus|bonus|ideal(ly)?|desired|desirable|helpful|advantage)\b', re.I)
MANDATORY = re.compile(r'\b(must|required|requirement|mandatory|only (open|available|eligible)|eligible|need to|have to)\b', re.I)
# Hard eligibility gates. A sentence with one of these that no extracted requirement covers is unresolved.
SIGNALS = {
    'academic': re.compile(r'\b(graduat\w*|class of|rising|freshm[ae]n|sophomores?|juniors?|seniors?|first[- ]year|second[- ]year|undergraduates?|graduate students?|enrolled|enrollment|currently pursuing|degree[- ]seeking|credits?|academic year)\b', re.I),
    'gpa': re.compile(r'\b(gpa|grade point)\b', re.I),
    'work_authorization': re.compile(r'\b(authori[sz]ed to work|eligible to work|work authori[sz]ation|legally (authori[sz]ed|permitted|able) to work|right to work)\b', re.I),
    'sponsorship': re.compile(r'\bsponsor\w*', re.I),
    'citizenship': re.compile(r'\b(citizens?(hip)?|permanent residents?|green card|u\.?s\.? persons?|itar|export control\w*)\b', re.I),
    'clearance': re.compile(r'\b(security clearance|clearance)\b', re.I),
    'age': re.compile(r'\b(\d{2}|eighteen) years (of age|old)\b', re.I),
}
GROUNDING = {
    'work_authorization': SIGNALS['work_authorization'],
    'sponsorship': SIGNALS['sponsorship'],
    'citizenship': SIGNALS['citizenship'],
    'degree': re.compile(r"\b(bachelor\w*|master\w*|degree|b\.?s\.?|b\.?a\.?|m\.?s\.?|ph\.?d\.?|doctora\w*|associate\w*|mba)\b", re.I),
}

def _norm(s: str) -> str: return re.sub(r'\s+', ' ', s).strip()

def locate(text: str, quote: str):
    """Exact span of quote in text, tolerating whitespace differences only. Returns the source substring."""
    if not quote.strip(): return None
    if quote in text:
        i = text.index(quote); return i, i + len(quote)
    pattern = r'\s+'.join(re.escape(w) for w in quote.split())
    m = re.search(pattern, text)
    return (m.start(), m.end()) if m else None

def _unknown(req: RequirementData, note: str, mandatory=True) -> RequirementData:
    return req.model_copy(update={'kind': 'other', 'operator': 'unspecified', 'values': [], 'mandatory': mandatory, 'note': note})

STANDING_ALIASES = {'freshmen': 'freshman', 'first-year': 'freshman', 'first year': 'freshman', 'sophomores': 'sophomore', 'second-year': 'sophomore',
                    'second year': 'sophomore', 'juniors': 'junior', 'seniors': 'senior', 'rising sophomores': 'rising sophomore', 'rising juniors': 'rising junior',
                    'rising seniors': 'rising senior'}
NEGATION = re.compile(r"\b(not|no|unable|cannot|can't|won't|will not|without|neither|nor)\b", re.I)
TERM = re.compile(r'\b(spring|summer|fall|autumn)\s+(?:of\s+)?(20\d{2})\b', re.I)
TERM_CONTEXT = re.compile(r'\b(intern\w*|co-?op|program|placement|start\w*|begin\w*|runs?)\b', re.I)
# Equal-opportunity statements list protected characteristics ("regardless of ... citizenship"); they are not conditions.
BOILERPLATE = re.compile(r'\b(equal (employment )?opportunity|regardless of|without regard to|discriminat\w*|reasonable accommodation\w*|e-?verify)\b', re.I)
GRADUATE_PROGRAM = re.compile(r"\b(ph\.?d|doctoral|graduate students?|master'?s|mba|postdoc\w*)\b", re.I)
GRADUATION_CONTEXT = re.compile(r'\b(graduat\w*|class of|degree|complet\w*|commencement)\b', re.I)

def normalize(req: RequirementData) -> RequirementData:
    """Canonical operator/value shapes. Only rewrites representation; never changes which students satisfy a rule."""
    vals = [v.strip() for v in req.values if v and v.strip()]
    op = req.operator
    if req.kind in ('degree', 'citizenship', 'standing', 'major', 'skills') and op == 'equals': op = 'one_of'
    if req.kind == 'standing': vals = [STANDING_ALIASES.get(v.casefold(), v.casefold()) for v in vals]
    if req.kind == 'graduation' and vals and all(re.fullmatch(r'20\d{2}', v) for v in vals):
        years = sorted(int(v) for v in vals)
        # "Graduating in 2028 or 2029": consecutive whole years form one window; gaps stay unsupported.
        if years == list(range(years[0], years[-1] + 1)): vals, op = [f'{years[0]}-01-01', f'{years[-1]}-12-31'], 'between'
    if req.kind == 'gpa':
        vals = [m.group() for v in vals for m in [re.match(r'\d(?:\.\d{1,2})?', v)] if m][:1]
    if req.kind == 'work_authorization' and [v.casefold() for v in vals] in ([], ['yes'], ['required'], ['authorized']) \
            and MANDATORY.search(req.quote) and not NEGATION.search(req.quote):
        vals, op = ['true'], 'equals'
    if req.kind == 'sponsorship' and [v.casefold() for v in vals] in ([], ['no'], ['none'], ['not available'], ['not required']) and NEGATION.search(req.quote):
        vals, op = ['false'], 'equals'
    if req.kind in ('work_authorization', 'sponsorship'): vals = [v.casefold() for v in vals]
    return req.model_copy(update={'operator': op, 'values': vals})

def detect_term(text: str):
    """The internship term when the posting names exactly one season+year in an internship context (or its title).
    Mentions inside graduation statements are ignored; several distinct terms are ambiguous and yield None."""
    found = {}
    first_line_end = text.find('\n') if '\n' in text else len(text)
    for sentence, start, end in sentences(text):
        if GRADUATION_CONTEXT.search(sentence): continue
        for m in TERM.finditer(sentence):
            if start < first_line_end or TERM_CONTEXT.search(sentence):
                key = f"{m.group(1).casefold().replace('autumn', 'fall').title()} {m.group(2)}"
                found.setdefault(key, sentence)
    return next(iter(found.items())) if len(found) == 1 else (None, None)

def source_incomplete(text: str) -> bool:
    """Heuristic for truncated postings: almost no text, or an explicit pointer to a fuller description elsewhere."""
    return len(text.strip()) < 120 or bool(re.search(r'\b(see|view|read) (the )?(full|complete) (job )?description\b|\.\.\.\s*$|…\s*$', text, re.I))

def _ground(req: RequirementData) -> str | None:
    """Return a problem description if the normalized values are not supported by the quote."""
    q, ql = req.quote, req.quote.casefold()
    vals = [v.casefold().strip() for v in req.values]
    if req.kind == 'graduation':
        if req.operator != 'between' or len(vals) != 2: return 'graduation rule is not a two-sided window'
        try: lo, hi = date.fromisoformat(vals[0]), date.fromisoformat(vals[1])
        except ValueError: return 'graduation bounds are not ISO dates'
        if lo > hi: return 'graduation window bounds are reversed'
        for d in (lo, hi):
            if str(d.year) not in q: return f'graduation year {d.year} does not appear in the quote'
            month_named = MONTHS[d.month-1] in ql or MONTHS[d.month-1][:3] + ' ' in ql or MONTHS[d.month-1][:3] + '.' in ql
            numeric = re.search(rf'\b0?{d.month}/(\d{{2}}/)?(\d{{2}})?{str(d.year)[2:]}\b', q)
            # A bare year is only accepted for full-year bounds (Jan 1 / Dec 31).
            full_year = (d == lo and (d.month, d.day) == (1, 1)) or (d == hi and (d.month, d.day) == (12, 31))
            if not (month_named or numeric or full_year): return f'graduation month for {d.isoformat()} is not stated in the quote'
    elif req.kind == 'gpa':
        if req.operator != 'minimum' or len(vals) != 1: return 'GPA rule is not a single minimum'
        try: v = float(vals[0])
        except ValueError: return 'GPA value is not numeric'
        if not 0 <= v <= 4: return 'GPA outside the 4.0 scale'
        if not SIGNALS['gpa'].search(q): return 'quote does not mention GPA'
        if re.search(r'(/|out of|scale of)\s*(5|10|20|100)\b', ql): return 'GPA uses a scale other than 4.0'
        if not any(abs(float(n) - v) < 1e-9 for n in re.findall(r'\b\d(?:\.\d{1,2})?\b', q)): return 'GPA value does not appear in the quote'
    elif req.kind == 'standing':
        if req.operator != 'one_of' or not vals: return 'standing rule is not a list of standings'
        for v in vals:
            if v not in STANDINGS: return f'unsupported standing value {v!r}'
            base = v.replace('rising ', '')
            words = {base, base + 's'} | ({'first-year', 'first year', 'freshmen'} if base == 'freshman' else set())
            if not any(w in ql for w in words): return f'standing {v!r} does not appear in the quote'
            if v.startswith('rising') and 'rising' not in ql: return f'quote does not say "rising" for {v!r}'
        # "4th-year senior PhD student" is not undergraduate class standing.
        if GRADUATE_PROGRAM.search(q): return 'standing wording refers to a graduate program, not undergraduate class standing'
    elif req.kind in ('work_authorization', 'sponsorship'):
        if req.operator != 'equals' or vals not in (['true'], ['false']): return 'authorization rule is not a boolean'
        if not GROUNDING[req.kind].search(q): return f'quote does not mention {req.kind.replace("_", " ")}'
        if req.kind == 'work_authorization' and vals != ['true']: return 'work authorization rule must require authorization'
    elif req.kind in ('citizenship', 'degree'):
        if req.operator != 'one_of' or not vals: return f'{req.kind} rule is not a list'
        if not GROUNDING[req.kind].search(q): return f'quote does not mention {req.kind}'
    elif req.kind in ('major', 'skills'):
        if req.operator not in ('one_of', 'all_of') or not vals: return f'{req.kind} rule is not a list'
        missing = [v for v in vals if v not in ql]
        if missing: return f'{req.kind} value {missing[0]!r} does not appear in the quote'
        if req.operator == 'all_of' and re.search(r'\bor\b', ql): return 'quote contains OR but the rule requires all values'
    return None

def validate_extraction(text: str, ex: Extraction, title: str | None = None) -> tuple[Extraction, dict]:
    report = {'validator_version': VALIDATOR_VERSION, 'downgraded': [], 'unreviewed_signals': 0, 'metadata_dropped': [], 'contradictions': []}
    reqs: list[RequirementData] = []
    for raw in ex.requirements:
        span = locate(text, raw.quote)
        if span is None:
            # Fabricated or paraphrased evidence: the whole extraction is unreliable.
            from .ai import AIOutputInvalid
            raise AIOutputInvalid('Requirement quote is not present verbatim in source')
        req = normalize(raw.model_copy(update={'quote': text[span[0]:span[1]], 'origin': 'model', 'note': None}))
        if req.kind not in ('other', 'experience'):
            problem = _ground(req)
            # Exceptions are checked across every full sentence the quote touches: a model may quote only the
            # "must be rising seniors" fragment of "...rising seniors, unless they are in a BS/MS program...".
            context = ' '.join(sent for sent, a, b in sentences(text) if a < span[1] and span[0] < b) or req.quote
            if not problem and NESTED.search(context): problem = 'condition contains an exception, alternative or discretionary wording'
            if problem:
                report['downgraded'].append({'kind': raw.kind, 'reason': problem})
                req = _unknown(req, 'Needs manual review: ' + problem, mandatory=req.mandatory)
        # Mandatory/preferred classification must agree with the wording; disagreement stays unresolved.
        says_pref, says_must = bool(PREFERENCE.search(req.quote)), bool(MANDATORY.search(req.quote))
        if (req.mandatory and says_pref and not says_must) or (not req.mandatory and says_must and not says_pref):
            report['downgraded'].append({'kind': req.kind, 'reason': 'mandatory/preferred classification conflicts with wording'})
            req = _unknown(req, 'Needs manual review: unclear whether this condition is mandatory')
        reqs.append(req)

    # Same-kind mandatory rules that cannot both hold are surfaced instead of producing a confident FAIL.
    windows = [r for r in reqs if r.kind == 'graduation' and r.mandatory]
    for i, a in enumerate(windows):
        for b in windows[i+1:]:
            if a.values[1] < b.values[0] or b.values[1] < a.values[0]:
                report['contradictions'].append('graduation windows do not overlap')
                reqs[reqs.index(a)] = _unknown(a, 'Posting states conflicting graduation windows')
                reqs[reqs.index(b)] = _unknown(b, 'Posting states conflicting graduation windows')

    covered = [locate(text, r.quote) for r in reqs]
    for sentence, start, end, category in signal_sentences(text):
        if any(s and s[0] < end and start < s[1] for s in covered): continue
        reqs.append(RequirementData(kind='other', mandatory=True, quote=sentence, operator='unspecified', origin='scanner',
                                    note=f'Possible {category.replace("_", " ")} condition not captured by extraction; unresolved'))
        covered.append((start, end)); report['unreviewed_signals'] += 1

    meta = {}
    for name in ('compensation', 'deadline', 'internship_start', 'internship_end', 'work_arrangement', 'posting_date', 'internship_term'):
        value = getattr(ex, name)
        if value is None: continue
        quote = ex.metadata_evidence.get(name) or ''
        span = locate(text, quote)
        ok = span is not None
        if ok and isinstance(value, date): ok = str(value.year) in quote
        if ok and name == 'internship_term':
            m = re.fullmatch(r'(spring|summer|fall|autumn|winter) (\d{4})', value.strip().casefold())
            ok = bool(m) and m.group(1) in quote.casefold() and m.group(2) in quote
        if ok: meta[name] = text[span[0]:span[1]]
        else: report['metadata_dropped'].append(name)
    updates = {n: (getattr(ex, n) if n in meta else None) for n in ('compensation', 'deadline', 'internship_start', 'internship_end', 'work_arrangement', 'posting_date', 'internship_term')}
    # The internship term is read from the text deterministically; a conflicting model value is discarded.
    # The ATS title is part of the source record (Greenhouse/Lever deliver it separately from the body text).
    term, term_quote = detect_term((title.strip() + '\n' if title else '') + text)
    model_term = updates.get('internship_term')
    if model_term and model_term.strip().title().replace('Autumn', 'Fall') != term: report['metadata_dropped'].append('internship_term (model value not uniquely stated)')
    updates['internship_term'] = term
    meta.pop('internship_term', None)
    if term: meta['internship_term'] = term_quote
    report['source_incomplete'] = source_incomplete(text)

    academic = any(r.kind in ('graduation', 'standing') for r in reqs) or any(r.origin == 'scanner' and 'academic' in (r.note or '') for r in reqs)
    return ex.model_copy(update={'requirements': reqs, 'metadata_evidence': meta, 'academic_scope_explicit': academic, **updates}), report

ABBREVIATIONS = {'u.s', 'e.g', 'i.e', 'inc', 'dr', 'st', 'jr', 'sr', 'no', 'vs', 'etc', 'u.k', 'approx'}

def sentences(text: str):
    """Yield (sentence, start, end). Splits at newlines and at ., !, ?, ; followed by space and a capital,
    except after common abbreviations such as "U.S." so eligibility statements stay whole."""
    for line in re.finditer(r'[^\n]+', text):
        seg_start, value = line.start(), line.group()
        cut = 0
        for m in re.finditer(r'[.!?;](?=\s+[A-Z0-9(•\-])', value):
            word = re.findall(r'[\w.]+$', value[:m.start()])
            if m.group() == '.' and word and word[0].casefold() in ABBREVIATIONS: continue
            yield from _trimmed(value, seg_start, cut, m.end())
            cut = m.end()
        yield from _trimmed(value, seg_start, cut, len(value))

def _trimmed(value, offset, a, b):
    chunk = value[a:b]
    stripped = chunk.strip()
    if len(stripped) >= 8:
        start = offset + a + chunk.index(stripped)
        yield stripped, start, start + len(stripped)

def signal_sentences(text: str):
    """Sentences (or bullet lines) containing hard eligibility-gate wording, with exact spans."""
    for sentence, start, end in sentences(text):
        if BOILERPLATE.search(sentence): continue
        for category, pattern in SIGNALS.items():
            if pattern.search(sentence):
                yield sentence, start, end, category
                break

def ground_resume(text: str, p: ProfileData) -> tuple[ProfileData, list[str]]:
    """Keep only resume fields whose values appear in the document; never fill standing or preferences."""
    tl = text.casefold()
    dropped = []
    def keep(name, ok):
        if getattr(p, name) is not None and not ok: dropped.append(name)
        return getattr(p, name) if ok else None
    stated = [float(x) for pair in re.findall(r'(?:gpa|grade point average)[^0-9\n]{0,20}(\d\.\d{1,2})|(\d\.\d{1,2})\s*(?:/\s*4\.0+)?\s*gpa', tl) for x in pair if x]
    gpa_ok = p.gpa is not None and any(abs(x - p.gpa) < 1e-9 for x in stated)
    def present(v): return bool(v) and _norm(str(v)).casefold() in _norm(tl)
    data = p.model_dump()
    data.update({
        'gpa': keep('gpa', gpa_ok and not re.search(r'gpa[^\n]{0,25}(/|out of)\s*(5|10|100)\b', tl)),
        'degree': keep('degree', present(p.degree)),
        'major': keep('major', present(p.major)),
        'minor': keep('minor', present(p.minor)),
        'university': keep('university', present(p.university)),
        'citizenship': keep('citizenship', present(p.citizenship) and 'citizen' in tl),
        'work_authorization': keep('work_authorization', bool(SIGNALS['work_authorization'].search(text))),
        'sponsorship_required': keep('sponsorship_required', bool(SIGNALS['sponsorship'].search(text))),
        'graduation': keep('graduation', p.graduation is not None and str(p.graduation.year) in text),
        'skills': [s for s in (p.skills or []) if present(s)] or None,
        'certifications': [c for c in (p.certifications or []) if present(c)] or None,
        # Standing, target term and preferences are confirmed by the student, never extracted.
        'standing': None, 'standing_at_start': None, 'standing_as_of': None, 'target_start': None, 'standing_term': None, 'season': None,
        'titles': None, 'industries': None, 'locations': None, 'arrangements': None, 'compensation_min': None,
    })
    for name in ('skills', 'certifications'):
        if len(data[name] or []) != len(getattr(p, name) or []): dropped.append(name + ' (items not found verbatim)')
    data.pop('weights', None)
    return ProfileData.model_validate(data), dropped
