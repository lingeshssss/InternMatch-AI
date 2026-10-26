"""Benchmark a provider/model on the controlled eligibility cases.

Usage (from backend/):
  ../.venv/bin/python -m evaluation.benchmark --model qwen3.5:9b [--embedding-model qwen3-embedding:0.6b] [--repeat 1]

Runs the production path: structured extraction -> deterministic source validation -> eligibility engine.
Reports decision accuracy, false "Verified Eligible" decisions (must be zero), requirement recall/precision
for hard-gate kinds, schema validity and latency. Results are written to evaluation/results/.
"""
import argparse, json, math, os, platform, statistics, subprocess, sys, time
from datetime import date, datetime, timezone
from pathlib import Path

os.environ.setdefault('DATABASE_URL', 'sqlite://')
HERE = Path(__file__).resolve().parent
GATED = ('graduation', 'standing', 'gpa', 'work_authorization', 'sponsorship', 'citizenship', 'degree', 'skills')

def norm_values(kind, values):
    vals = sorted(v.casefold().strip() for v in values)
    if kind == 'degree':
        aliases = {"bachelor": "bachelor's", "bachelors": "bachelor's", "master": "master's", "masters": "master's", "ph.d.": "phd", "doctorate": "phd"}
        vals = sorted(aliases.get(v, v) for v in vals)
    if kind == 'citizenship':
        return ['*']  # Free-text values; matched on kind only.
    return vals

def requirement_scores(gold, got):
    gold_g = [g for g in gold if g['kind'] in GATED]
    got_g = [r for r in got if r.kind in GATED]
    def key(kind, mandatory, values): return (kind, mandatory, tuple(norm_values(kind, values)))
    gold_keys = [key(g['kind'], g['mandatory'], g['values']) for g in gold_g]
    got_keys = [key(r.kind, r.mandatory, r.values) for r in got_g]
    tp = sum(1 for k in gold_keys if k in got_keys)
    fp = sum(1 for k in got_keys if k not in gold_keys)
    return tp, len(gold_keys), fp, len(got_keys)

def profile_of(d):
    from app.schemas import ProfileData
    return ProfileData.model_validate(d)

def gold_check(cases):
    """The expected decisions must follow from the gold requirements under the engine, or the dataset is wrong."""
    from app.eligibility import evaluate
    from app.schemas import RequirementData
    problems = []
    for c in cases:
        reqs = [RequirementData(kind=g['kind'], mandatory=g['mandatory'], values=g['values'], operator=op_for(g), quote='gold') for g in c['gold']]
        scope = c.get('scope') or any(g['kind'] in ('graduation', 'standing') for g in c['gold']) or c['id'] in ('H-nested-exception', 'L-contradictory-windows', 'K-buried-footnote')
        for p in c['profiles']:
            got = evaluate(reqs, profile_of(p['profile']), academic_scope_explicit=scope, term=c.get('term'), extracted=True,
                           source_complete=not c.get('source_incomplete', False))['status']
            if got != p['expected']: problems.append(f"{c['id']}/{p['name']}: gold implies {got}, expected {p['expected']}")
    return problems

def op_for(g):
    return {'graduation': 'between', 'gpa': 'minimum', 'work_authorization': 'equals', 'sponsorship': 'equals'}.get(g['kind'], 'one_of' if g['values'] else 'unspecified')

def score(c, raw_json, row):
    """Apply production validation and the engine to one raw model output (also used by --rescore)."""
    from app import ai
    from app.eligibility import evaluate
    from app.quality import validate_extraction
    from app.schemas import Extraction
    try:
        validated, report = validate_extraction(c['text'], Extraction.model_validate(raw_json))
    except ai.AIOutputInvalid as exc:
        # Extraction rejected: production stores no requirements and the posting is Unverified.
        row.update(outcome='invalid', error=str(exc)[:200], tp=0, gold_n=sum(1 for g in c['gold'] if g['kind'] in GATED), fp=0, got_n=0,
                   decisions=[{'profile': p['name'], 'expected': p['expected'], 'got': 'Unverified'} for p in c['profiles']])
        return row
    row.update(outcome='ok', report=report, term=validated.internship_term, complete=validated.complete,
               start=str(validated.internship_start) if validated.internship_start else None)
    tp, gold_n, fp, got_n = requirement_scores(c['gold'], validated.requirements)
    row.update(tp=tp, gold_n=gold_n, fp=fp, got_n=got_n)
    row['decisions'] = [{'profile': p['name'], 'expected': p['expected'], 'got': evaluate(
        validated.requirements, profile_of(p['profile']), complete=validated.complete, academic_scope_explicit=validated.academic_scope_explicit,
        start=validated.internship_start, term=validated.internship_term, source_complete=not report['source_incomplete'], extracted=True)['status']} for p in c['profiles']]
    row['requirements'] = [r.model_dump(include={'kind', 'mandatory', 'operator', 'values', 'origin', 'note'}) for r in validated.requirements]
    return row

def run_llm(model, cases, repeat):
    from app import ai
    from app.config import settings
    from app.schemas import Extraction
    settings.ai_provider, settings.ollama_model = 'ollama', model
    settings.ai_allow_hosted_fallback = False
    rows = []
    for c in cases:
        for attempt in range(repeat):
            started = time.monotonic(); row = {'case': c['id'], 'attempt': attempt}
            try:
                raw, provenance = ai.structured(c['text'], Extraction, ai.JOB_INSTRUCTION)
                row.update(model=provenance['model'], raw=raw.model_dump(mode='json'))
                score(c, row['raw'], row)
            except ai.AIOutputInvalid as exc:
                row.update(outcome='invalid', error=str(exc)[:200], tp=0, gold_n=sum(1 for g in c['gold'] if g['kind'] in GATED), fp=0, got_n=0,
                           decisions=[{'profile': p['name'], 'expected': p['expected'], 'got': 'Unverified'} for p in c['profiles']])
            except ai.AIUnavailable as exc:
                row.update(outcome='unavailable', error=str(exc)[:200]); rows.append(row); continue
            row['seconds'] = round(time.monotonic() - started, 2)
            rows.append(row)
            print(f"  {c['id']:<38} {row['outcome']:<8} {row.get('seconds', 0):>6}s  " + ' '.join(
                ('OK' if d['got'] == d['expected'] else f"[{d['expected']}->{d['got']}]") for d in row.get('decisions', [])), flush=True)
    return rows

def summarize(rows):
    ok = [r for r in rows if r['outcome'] != 'unavailable']
    decisions = [d for r in ok for d in r['decisions']]
    false_verified = [d for d in decisions if d['got'] == 'Verified Eligible' and d['expected'] != 'Verified Eligible']
    false_ineligible = [d for d in decisions if d['got'] == 'Ineligible' and d['expected'] != 'Ineligible']
    missed_verified = [d for d in decisions if d['expected'] == 'Verified Eligible' and d['got'] != 'Verified Eligible']
    missed_ineligible = [d for d in decisions if d['expected'] == 'Ineligible' and d['got'] != 'Ineligible']
    tp, gold_n, fp, got_n = (sum(r.get(k, 0) for r in ok) for k in ('tp', 'gold_n', 'fp', 'got_n'))
    secs = [r['seconds'] for r in ok if 'seconds' in r]
    return {
        'runs': len(rows), 'unavailable': sum(r['outcome'] == 'unavailable' for r in rows), 'schema_or_evidence_rejected': sum(r['outcome'] == 'invalid' for r in rows),
        'decisions': len(decisions), 'decision_accuracy': round(sum(d['got'] == d['expected'] for d in decisions) / len(decisions), 3) if decisions else None,
        'false_verified': len(false_verified), 'false_ineligible': len(false_ineligible),
        'missed_verified': len(missed_verified), 'missed_ineligible': len(missed_ineligible),
        'gated_requirement_recall': round(tp / gold_n, 3) if gold_n else None, 'gated_requirement_precision': round((got_n - fp) / got_n, 3) if got_n else None,
        'latency_median_s': round(statistics.median(secs), 1) if secs else None, 'latency_p90_s': round(sorted(secs)[max(0, math.ceil(len(secs) * .9) - 1)], 1) if secs else None,
        'false_verified_detail': false_verified, 'false_ineligible_detail': false_ineligible,
    }

def run_embeddings(model):
    """Semantic matching sanity check: each profile's best-matching posting should rank first."""
    from app import ai
    from app.config import settings
    settings.ai_provider, settings.ollama_embedding_model = 'ollama', model
    jobs = {
        'ml': 'Machine learning intern: train PyTorch models, deep learning research, model evaluation.',
        'frontend': 'Frontend intern: build React and TypeScript user interfaces, CSS, accessibility.',
        'security': 'Security intern: penetration testing, threat modeling, incident response, network security.',
        'finance': 'Finance intern: financial modeling, Excel, valuation, variance analysis.',
        'hardware': 'Hardware intern: embedded C firmware, PCB bring-up, oscilloscopes, microcontrollers.',
        'data': 'Data engineering intern: SQL, Airflow pipelines, data warehousing, dbt.',
    }
    profiles = {'ml': 'Python; PyTorch; neural networks; computer vision research project', 'frontend': 'JavaScript; React; Next.js; web accessibility',
                'security': 'CTF competitions; Wireshark; vulnerability assessment; Linux hardening', 'finance': 'Excel; DCF valuation; accounting coursework',
                'hardware': 'Arduino; soldering; embedded C; STM32 microcontrollers', 'data': 'PostgreSQL; ETL pipelines; Apache Airflow; data modeling'}
    started = time.monotonic()
    vectors, key = ai.embeddings(list(jobs.values()) + list(profiles.values()))
    seconds = time.monotonic() - started
    jv, pv = vectors[:len(jobs)], vectors[len(jobs):]
    cos = lambda a, b: sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))
    hits, margins = 0, []
    for (name, _), v in zip(profiles.items(), pv):
        scores = {j: cos(v, w) for j, w in zip(jobs, jv)}
        best = max(scores, key=scores.get); hits += best == name
        margins.append(scores[name] - max(s for j, s in scores.items() if j != name))
    return {'model': key, 'top1_accuracy': round(hits / len(profiles), 3), 'mean_margin': round(statistics.mean(margins), 3), 'dimensions': len(vectors[0]), 'seconds_for_12_texts': round(seconds, 2)}

def hardware():
    info = {'machine': platform.machine(), 'macos': platform.mac_ver()[0]}
    try:
        info['chip'] = subprocess.run(['sysctl', '-n', 'machdep.cpu.brand_string'], capture_output=True, text=True).stdout.strip()
        info['memory_gb'] = round(int(subprocess.run(['sysctl', '-n', 'hw.memsize'], capture_output=True, text=True).stdout) / 2**30)
        info['ollama'] = subprocess.run(['ollama', '--version'], capture_output=True, text=True).stdout.strip().splitlines()[-1]
    except Exception: pass
    return info

def main():
    sys.path.insert(0, str(HERE.parent))
    parser = argparse.ArgumentParser()
    parser.add_argument('--model'); parser.add_argument('--embedding-model'); parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--only', help='comma-separated case ids')
    parser.add_argument('--cases', default='cases.json', help='case file in evaluation/ (cases.json or cases_holdout.json)')
    parser.add_argument('--rescore', help='re-apply current validation/engine to stored raw outputs in this results file')
    args = parser.parse_args()
    cases = json.loads((HERE / args.cases).read_text())['cases']
    if args.only: cases = [c for c in cases if c['id'] in args.only.split(',')]
    problems = gold_check(cases)
    if problems: print('Dataset inconsistent with engine:\n  ' + '\n  '.join(problems)); sys.exit(2)
    if args.rescore:
        stored = json.loads(Path(args.rescore).read_text()); by_id = {c['id']: c for c in cases}
        rows = [score(by_id[r['case']], r['raw'], {k: v for k, v in r.items() if k in ('case', 'attempt', 'model', 'raw', 'seconds')}) if 'raw' in r else r for r in stored['rows']]
        summary = summarize(rows)
        print(json.dumps({k: v for k, v in summary.items() if not k.endswith('_detail')}, indent=2)); return
    result = {'generated_at': datetime.now(timezone.utc).isoformat(), 'hardware': hardware(), 'cases': len(cases), 'case_file': args.cases}
    if args.model:
        print(f'Extraction benchmark: {args.model} ({len(cases)} cases x {args.repeat})')
        rows = run_llm(args.model, cases, args.repeat)
        result.update(model=args.model, summary=summarize(rows), rows=rows)
        print(json.dumps({k: v for k, v in result['summary'].items() if not k.endswith('_detail')}, indent=2))
    if args.embedding_model:
        result['embeddings'] = run_embeddings(args.embedding_model); print(json.dumps(result['embeddings'], indent=2))
    if not (args.model or args.embedding_model): print('Gold labels consistent with the engine.'); return
    out = HERE / 'results'; out.mkdir(exist_ok=True)
    name = (args.model or args.embedding_model).replace(':', '_').replace('/', '_') + ('' if args.cases == 'cases.json' else '.' + Path(args.cases).stem)
    (out / f'{name}.json').write_text(json.dumps(result, indent=2, default=str))

if __name__ == '__main__': main()
