import math
from .ai import embeddings

def fit(profile, text):
    sections={'skills':profile.skills,'projects':profile.projects,'experience':profile.experience,'academic':[x for x in (profile.major,profile.degree,profile.university) if x],'certifications':profile.certifications,'preferences':(profile.industries or [])+(profile.titles or [])+(profile.locations or [])+(profile.arrangements or [])}
    present={k:'; '.join(v) for k,v in sections.items() if v}
    if not present: return {'score':None,'method':'unavailable','explanation':'No confirmed qualifications to compare.'}
    vectors=embeddings([text]+list(present.values()))
    target=vectors[0]
    def cosine(a,b):
        denom=math.sqrt(sum(x*x for x in a)*sum(x*x for x in b))
        return max(0,min(1,sum(x*y for x,y in zip(a,b))/denom)) if denom else 0
    components={k:round(cosine(target,v)*100,1) for k,v in zip(present,vectors[1:])}
    score=round(sum(components.get(k,0)*w for k,w in profile.weights.items()),1)
    return {'score':score,'components':components,'weights':profile.weights,'evidence':present,'method':'embedding cosine similarity; missing sections contribute zero','explanation':'Semantic fit, not probability of an offer. Eligibility is evaluated independently.'}
