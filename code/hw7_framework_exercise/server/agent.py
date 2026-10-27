from __future__ import annotations
import math, os, re, time
from pathlib import Path
from typing import Any
import httpx
from .tools import SNAPSHOT_DIR, calculate, csv_sql, retrieve_policy

def quote(s: str) -> str: return '"' + s.replace('"','""') + '"'

def num(n: float) -> str: return format(float(n),'.12g')

def category(s: str) -> str:
    s=re.sub(r'[^a-z]','',str(s).lower())
    return 'scooter' if 'scooter' in s else ('ebike' if 'electric' in s or 'ebike' in s else 'classic')

def csv_summary(ds: dict[str,Any], prompt: str = ""):
    h={str(x).lower():str(x) for x in ds.get('headers',[])}
    a=h.get('started_at') or h.get('start_time') or h.get('starttime')
    b=h.get('ended_at') or h.get('end_time') or h.get('stoptime')
    if not a or not b: raise ValueError('CSV needs start and end timestamp columns.')
    typ=next((h[n] for n in ('rideable_type','bike_type','vehicle_type') if n in h),None)

    d='((julianday({})-julianday({}))*1440.0)'.format(quote(b),quote(a))

    t=("CASE WHEN trim(COALESCE({},''))='' THEN 'classic_bike' ELSE {} END".format(quote(typ),quote(typ)) if typ else "'classic_bike'")

    sql=("SELECT {0} AS ride_type, COUNT(*) AS ride_count, AVG({1}) AS average_minutes, MIN(date({2})) AS first_ride, "
         "MAX(date({2})) AS last_ride FROM trips WHERE {2}<>'' AND {3}<>'' AND {1}>=0 GROUP BY ride_type").format(t,d,quote(a),quote(b))
    obs=csv_sql({'sql':sql},ds)
    if not obs.get('success'): raise ValueError(obs.get('error','CSV query failed.'))
    groups=obs['data']['rows']
    context=prompt.lower()
    requested='classic' if 'classic' in context and 'only' in context else ('ebike' if ('ebike' in context or 'e-bike' in context or 'electric bike' in context) and 'only' in context else ('scooter' if 'scooter' in context and 'only' in context else None))
    if requested:
        groups=[x for x in groups if category(x.get('ride_type') or 'classic_bike')==requested]
        if not groups: raise ValueError('Extra context selected a vehicle type with no matching rows in the uploaded CSV.')
    count=sum(int(x.get('ride_count') or 0) for x in groups)
    if not count: raise ValueError('No valid ride durations were found.')
    avg=sum(int(x.get('ride_count') or 0)*float(x.get('average_minutes') or 0) for x in groups)/count
    summary={
            'valid_trip_count':count,
             'average_duration':avg,
             'date_start':min((str(x['first_ride']) for x in groups if x.get('first_ride')),default=None),
             'date_end':max((str(x['last_ride']) for x in groups if x.get('last_ride')),default=None),'vehicle_mix':[
        {'type':x.get('ride_type') or 'classic_bike',
         'category':category(x.get('ride_type') or 'classic_bike'),
         'share':int(x.get('ride_count') or 0)/count,
         'average_minutes':float(x.get('average_minutes') or 0)} for x in groups], 
         'context_selection':requested}
    return obs,summary,sql

def extract_rules(text:str)->dict:
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    def ix(name): return next((i for i,x in enumerate(lines) if name.lower() in x.lower()),-1)
    an,si,cl,eb,sc=ix('Divvy Annual'),ix('Single Ride'),ix('Classic bike prices'),ix('Ebike prices'),ix('Scooter prices')
    if min(an,si,cl)<0: raise ValueError('Captured page does not show Divvy annual, single-ride, and classic-bike rules.')
    annual=re.search(r'\$([0-9]+(?:\.[0-9]{1,2})?)/year','\n'.join(lines[an:an+10]),re.I)
    single=re.search(r'\$([0-9]+(?:\.[0-9]{1,2})?)\s*\+\s*\$([0-9]+(?:\.[0-9]{1,2})?)/min','\n'.join(lines[si:si+10]),re.I)
    classic=re.search(r'([0-9]+)\s*min(?:ute)?s?\s+free,\s*then\s*\$([0-9]+(?:\.[0-9]{1,2})?)/min','\n'.join(lines[cl:cl+6]),re.I)
    if not all((annual,single,classic)): raise ValueError('Captured page lacks verifiable Divvy fare rules.')
    rules={'annual':float(annual.group(1)),'single':{'classic':{'unlock':float(single.group(1)),'rate':float(single.group(2))}},
      'member':{'classic':{'included':int(classic.group(1)),'rate':float(classic.group(2)),'cap':None}},
      'evidence':['\n'.join(lines[si:si+10]),'\n'.join(lines[an:an+10]),'\n'.join(lines[cl:cl+6])]}
    for title,cat in (('Ebike prices','ebike'),('Scooter prices','scooter')):
        pos=ix(title)
        if pos<0: continue
        one=re.search(r'\$([0-9]+(?:\.[0-9]{1,2})?)\s*unlock\s*\+\s*\$([0-9]+(?:\.[0-9]{1,2})?)/min',lines[pos+1],re.I) if pos+1<len(lines) else None
        memline=lines[pos+3] if pos+3<len(lines) else ''
        rate=re.search(r'\$([0-9]+(?:\.[0-9]{1,2})?)/min',memline,re.I)
        cap=re.search(r'capped at \$([0-9]+(?:\.[0-9]{1,2})?)','\n'.join(lines[pos:pos+5]),re.I)
        if one and rate:
            rules['single'][cat]={'unlock':float(one.group(1)),'rate':float(one.group(2))}
            rules['member'][cat]={'included':0,'rate':float(rate.group(1)),'cap':float(cap.group(1)) if cap else None}
            rules['evidence'].append('\n'.join(lines[pos:pos+5]))
    return rules

def calc(expr:str,units:str,timeline:list)->float:
    args={'expression':expr,
          'units':units}; obs=calculate(expr,units)
    timeline.append({'step':len(timeline)+1,
                     'tool':'calculator',
                     'input':args,'observation':obs})
    if not obs.get('success'): raise ValueError(obs.get('error','Calculator failed.'))

    return float(obs['data']['value'])

def ride_costs(summary,rules,multiplier,timeline):
    pterms=[]; mterms=[]
    for v in summary['vehicle_mix']:
        cat,share=v['category'],float(v['share'])
        minutes=math.ceil(float(v.get('average_minutes') or summary['average_duration'])*multiplier)
        one=rules['single'].get(cat,rules['single']['classic']); member=rules['member'].get(cat,rules['member']['classic'])
        p=one['unlock']+minutes*one['rate']
        if cat=='classic': residual=max(0,minutes-member['included'])*member['rate']
        elif member['cap']:
            residual=min(min(minutes,45)*member['rate'],member['cap']) + max(0,minutes-45)*member['rate']
        else: residual=minutes*member['rate']
        pterms.append('({}*{})'.format(num(share),num(p))); mterms.append('({}*{})'.format(num(share),num(residual)))
    return calc('+'.join(pterms),'USD/ride',timeline),calc('+'.join(mterms),'USD/ride',timeline)

def cases(scenario):
    all_cases=[
      {'name':'Frequent / longer rides',
       'counts':[8,8,8,8],
       'multiplier':1.5,
       'definition':'8 rides each week and 1.5x uploaded average duration.'},
      {'name':'Occasional / short rides',
       'counts':[1,0,1,0],
       'multiplier':0.5,
       'definition':'2 rides in four weeks and 0.5x uploaded average duration.'}]
    
    if scenario in ('Run both acceptance cases','Both acceptance cases'): 
        return all_cases
    return [x for x in all_cases if x['name']==scenario]

def fallback(report,snapshot):
    c=report['costBreakdown']; ev=report['citations'][0]['text'].replace('\n',' ')[:140]
    
    return ('For the {0} profile, estimated four-week pay-per-use cost is {1}, versus {2} for Divvy Annual including residual charges. '
      'The model uses {3} rides averaging {4:.1f} minutes under the stated synthetic frequency and duration assumptions. '
      'The annual membership fee is divided by 12 to show a monthly equivalent, not a separate monthly product. '
      'The captured official page states “{5}” (accessed {6}); the systemwide CSV does not identify individual riders.').format(
       report['scenario'].lower(),'\u0024{:.2f}'.format(c['payPerUse']),'\u0024{:.2f}'.format(c['membership']),
       report['usage']['rides'],report['usage']['averageDuration'],ev,snapshot['accessedAt'])

async def rationale(report,snapshot,backup):
    base=os.getenv('OLLAMA_BASE_URL','http://localhost:11434').rstrip('/'); model=os.getenv('OLLAMA_MODEL','qwen3')
    ppu='\u0024{:.2f}'.format(report['costBreakdown']['payPerUse']); mem='\u0024{:.2f}'.format(report['costBreakdown']['membership'])
    prompt=('Write exactly four sentences using only these facts: scenario {0}; decision {1}; four-week pay-per-use {2}; membership total {3}; '
      'rides {4}; average minutes {5:.1f}; source {6}; accessed {7}. Say membership is an annual price shown as monthly equivalent and CSV is systemwide, not one rider. '
      'Add no other numbers or pricing claims.').format(report['scenario'],report['decision'],ppu,mem,report['usage']['rides'],report['usage']['averageDuration'],snapshot['sourceUrl'],snapshot['accessedAt'])
    try:
        async with httpx.AsyncClient(timeout=float(os.getenv('OLLAMA_RATIONALE_TIMEOUT','8'))) as client:
            r=await client.post(base+'/api/chat',json={'model':model,'messages':[{'role':'system','content':'Use only supplied facts. Final rationale only; no chain of thought.'},{'role':'user','content':prompt}],'stream':False,'think':False,'options':{'num_predict':180}})
            r.raise_for_status(); answer=str(r.json().get('message',{}).get('content','')).strip()
        decision_phrase='buy monthly membership' if report['decision']=='Buy Monthly Membership' else 'pay per ride'
        if len(re.findall(r'[.!?](?:\s|$)',answer))==4 and ppu in answer and mem in answer and decision_phrase in answer.lower() and 'annual' in answer.lower() and 'systemwide' in answer.lower(): return answer
    except Exception: pass
    return backup

async def build_report(spec,summary,rules,snapshot,timeline):
    avg=summary['average_duration']*spec['multiplier']; counts=spec['counts']; rides=sum(counts)
    ppu_ride,residual_ride=ride_costs(summary,rules,spec['multiplier'],timeline)
    ppu=calc('{}*{}'.format(rides,num(ppu_ride)),'USD/4 weeks',timeline)
    residual=calc('{}*{}'.format(rides,num(residual_ride)),'USD/4 weeks',timeline)
    fee=calc('{}/12'.format(num(rules['annual'])),'USD/month equivalent',timeline)
    member=calc('{}+{}'.format(num(fee),num(residual)),'USD/4 weeks',timeline)
    saving=ppu_ride-residual_ride
    if saving>0:
        raw=calc('{}/{}'.format(num(fee),num(saving)),'break-even rides before rounding',timeline)
        be=math.ceil(raw); bemin=calc('{}*{}'.format(be,num(avg)),'break-even ride minutes',timeline)
    else: be,bemin=None,None
    weekly=[]
    for i,n in enumerate(counts,1):
        spend=calc('{}*{}'.format(n,num(ppu_ride)),'USD weekly pay-per-use',timeline)
        weekly_residual=calc('{}*{}'.format(n,num(residual_ride)),'USD weekly member overage',timeline)
        weekly.append({'week':i,'rideCount':n,'averageDuration':round(avg,2) if n else 0,'spend':round(spend,2),'membershipSpend':round(fee/4+weekly_residual,2)})
    decision='Buy Monthly Membership' if member<ppu else 'Pay Per Ride/Minute'
    citations=[{'text':s,'sourceUrl':snapshot['sourceUrl'],'accessedAt':snapshot['accessedAt'],'sha256':snapshot['sha256']} for s in rules['evidence']]
    report={'scenario':spec['name'],'decision':decision,'rationale':'',
      'costBreakdown':{'payPerUse':round(ppu,2),'membership':round(member,2),'membershipFee':round(fee,2),'residualCharges':round(residual,2),'breakEvenRides':be,'breakEvenMinutes':round(bemin,1) if bemin is not None else None},
      'weeklyTable':weekly,'usage':{'rides':rides,'averageDuration':round(avg,2)},'citations':citations,
      'assumptions':['The uploaded CSV is systemwide and has no rider ID; it informs average ride duration and vehicle mix, not individual frequency.',
       'Synthetic acceptance profile: '+spec['definition'],
       'Duration uses {:,} valid uploaded trips from {} through {}; multiplier is {}x.'.format(summary['valid_trip_count'],summary.get('date_start') or 'unknown start date',summary.get('date_end') or 'unknown end date',spec['multiplier']),
       'Divvy Annual is \u0024{:.2f}/year, modeled as \u0024{:.2f}/month by dividing by 12; this is not a separate monthly product.'.format(rules['annual'],fee),
       'Scenario average duration is rounded up to whole minutes for per-minute fare calculations; the uploaded pricing-page snapshot does not state a rounding rule. Vehicle-specific durations and rates are weighted using the uploaded trip mix.',
       'Extra context vehicle filter: '+(summary['context_selection']+' only' if summary.get('context_selection') else 'none; uploaded vehicle mix used.'),
       'Four-week totals exclude taxes, parking violations, day passes, and limited-time promotional eligibility; verify current app prices before purchase.'],
      'stopReason':'Completed after successful trip aggregation, official pricing capture, and calculator-backed comparison.','totalSteps':0}
    report['rationale']=await rationale(report,snapshot,fallback(report,snapshot))
    return report

async def run_agent(dataset:dict,pricing_url:str,scenario:str,prompt:str)->dict[str,Any]:
    started=time.perf_counter(); timeline=[]
    csv_obs,summary,sql=csv_summary(dataset,prompt)
    timeline.append({'step':1,
                     'tool':'csv_sql',
                     'input':{'sql':sql},
                     'observation':csv_obs})
    pi={'url':pricing_url,
        'query':'Divvy Single Ride unlock price per minute Annual membership classic bike included minutes and overage e-bike scooter','k':8}
    po=await retrieve_policy(pi); timeline.append({'step':2,
                                                   'tool':'policy_retriever',
                                                   'input':pi,'observation':po})
    if not po.get('success'): raise ValueError('Could not retrieve pricing evidence: '+str(po.get('error')))
    snapshot=po['data']['snapshot']; path=SNAPSHOT_DIR/Path(snapshot['filename']).name
    rules=extract_rules(path.read_text(encoding='utf-8')); selected=cases(scenario)
    if not selected: raise ValueError('Choose Frequent / longer rides, Occasional / short rides, or Run both acceptance cases.')
    reports=[]
    for spec in selected: reports.append(await build_report(spec,summary,rules,snapshot,timeline))
    for i,item in enumerate(timeline,1): item['step']=i
    for report in reports: report['totalSteps']=len(timeline)
    return {'scenario':scenario,
            'report':reports[0],
            'reports':reports,
            'timeline':timeline,
            'snapshots':[snapshot],
      'source':dataset.get('filename','uploaded.csv'),'rowCount':len(dataset.get('rows',[])),
      'validTripCount':summary['valid_trip_count'],'elapsedSeconds':round(time.perf_counter()-started,2)}
