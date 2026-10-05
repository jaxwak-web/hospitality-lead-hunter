import csv, html, io, re, time, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urljoin, urlparse
import requests, streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title='JJ Opportunity Radar', page_icon='🎯', layout='wide')
PLACES='https://places.googleapis.com/v1/places:searchText'
CATS={'Bar & Grill':'bar and grill','Tavern / Pub':'tavern pub','Independent Restaurant':'local independent restaurant','Brewery / Brewpub':'brewery brewpub','Cafe / Coffee':'local cafe coffee shop','Hotel / Resort':'independent hotel resort'}
CHAINS=['applebee','arby','buffalo wild wings','burger king','chili','chipotle','cracker barrel','culver','dairy queen','denny','domino','five guys','hardee','hooters','ihop','jersey mike','jimmy john','kfc','little caesars','longhorn steakhouse','mcdonald','olive garden','outback steakhouse','panera','perkins','pizza hut','qdoba','raising cane','red robin','sonic','starbucks','subway','taco bell','texas roadhouse','tgi friday','wendy']
MGR=['general manager','restaurant manager','bar manager','kitchen manager','operations manager','assistant general manager','agm','foh manager','front of house manager','executive chef']
HIRING=['now hiring',"we're hiring",'we are hiring','join our team','careers','employment','help wanted','apply now','job openings']
STRESS=['reduced hours','staffing shortage','short staffed','struggling','labor shortage','temporarily closed','closing early','slow business','turnaround','understaffed']
OWN=['new ownership','new owner','under new management','sold to','acquired by','ownership change']
GROW=['second location','new location','expanding','expansion','grand opening','reopening']
CAREER=['career','jobs','employment','join-us','work-with-us','hiring','apply']
LOCAL=['locally owned','family owned','family-owned','independently owned','owner-operated','owner operated','neighborhood','local favorite']

def sec(k):
    try: return st.secrets.get(k,'')
    except Exception: return ''

def get(url,t=8):
    return requests.get(url,timeout=t,headers={'User-Agent':'Mozilla/5.0 JJOpportunityRadar/4.0'},allow_redirects=True)

def places(key,q,n):
    h={'Content-Type':'application/json','X-Goog-Api-Key':key,'X-Goog-FieldMask':'places.id,places.displayName,places.formattedAddress,places.types,places.websiteUri,places.googleMapsUri,places.rating,places.userRatingCount,places.businessStatus'}
    r=requests.post(PLACES,json={'textQuery':q,'pageSize':min(max(n,1),20),'languageCode':'en','regionCode':'US'},headers=h,timeout=20)
    if r.status_code!=200: raise RuntimeError(f'Google Places {r.status_code}: {r.text[:250]}')
    return r.json().get('places',[])

def news(name,market,days):
    u='https://news.google.com/rss/search?q='+quote_plus(f'"{name}" "{market}" when:{days}d')+'&hl=en-US&gl=US&ceid=US:en'
    try: root=ET.fromstring(get(u,10).text)
    except Exception: return []
    out=[]
    for i in root.findall('.//item')[:8]:
        d=re.sub('<[^>]+>',' ',html.unescape(i.findtext('description') or ''))
        out.append({'title':(i.findtext('title') or '').strip(),'url':i.findtext('link') or '','source':i.findtext('source') or '','text':re.sub(r'\s+',' ',d).strip()})
    return out

def market_jobs(key, market):
    if not key: return []
    payload={
        'keywords':'general manager, restaurant manager, kitchen manager, bar manager, operations manager, executive chef',
        'location':market,'radius':'40','page':1,'ResultOnPage':100,'companysearch':False
    }
    try:
        r=requests.post(f'https://jooble.org/api/{key}',json=payload,timeout=15)
        if r.status_code!=200:return []
        return r.json().get('jobs',[])
    except Exception:return []

def match_jobs(all_jobs, name):
    toks={x.lower() for x in re.findall(r'[A-Za-z0-9]+',name) if len(x)>=4}
    if not toks:return []
    out=[]
    for j in all_jobs:
        hay=f"{j.get('company','')} {j.get('title','')}".lower()
        # Require at least one distinctive business-name token and a management title.
        if any(t in hay for t in toks) and any(m in (j.get('title') or '').lower() for m in MGR):
            out.append(j)
    return out[:8]

def scan_site(url):
    z={'reachable':False,'hiring':False,'management':False,'local':False,'terms':[]}
    if not url:return z
    try:
        r=get(url); r.raise_for_status(); z['reachable']=True
    except Exception:return z
    pages=[(r.url,r.text)]
    try:
        s=BeautifulSoup(r.text,'html.parser'); seen={r.url}
        for a in s.find_all('a',href=True):
            label=f"{a.get_text(' ',strip=True)} {a['href']}".lower()
            if any(w in label for w in CAREER):
                u=urljoin(r.url,a['href'])
                if urlparse(u).netloc==urlparse(r.url).netloc and u not in seen and len(pages)<4:
                    seen.add(u)
                    try:
                        rr=get(u,7)
                        if rr.status_code<400:pages.append((u,rr.text))
                    except Exception:pass
    except Exception:pass
    text=' '.join(BeautifulSoup(b,'html.parser').get_text(' ',strip=True).lower() for _,b in pages)
    h=[x for x in HIRING if x in text]; m=[x for x in MGR if x in text]; l=[x for x in LOCAL if x in text]
    z.update({'hiring':bool(h),'management':bool(m),'local':bool(l),'terms':(h+m+l)[:12]});return z

def chain(n):return any(x in (n or '').lower() for x in CHAINS)
def hits(items,terms):
    t=' '.join(f"{x.get('title','')} {x.get('text','')}" for x in items).lower();return [x for x in terms if x in t]

def rank(p,w,n,j):
    score=0;e=[];types=[];ch=chain(p['name'])
    if ch: score-=55;e.append('Major chain / franchise signal')
    else: score+=22;e.append('Independent/local operator candidate')
    if w['hiring']:score+=18;e.append('Website shows hiring/careers activity');types.append('Leadership / Staffing')
    if w['management']:score+=22;e.append('Management-level hiring language on website');types.append('Leadership Vacancy')
    mj=[x for x in j if any(t in (x.get('title') or '').lower() for t in MGR)]
    if mj:score+=28;e.append(f'{len(mj)} management job posting(s) detected');types.append('Leadership Vacancy')
    if len(mj)>=2:score+=12;e.append('Multiple management openings')
    if not p.get('website'):score+=8;e.append('No website listed');types.append('Digital Opportunity')
    elif not w['reachable']:score+=8;e.append('Website not reachable during scan');types.append('Digital Opportunity')
    if w['local']:score+=10;e.append('Website signals local/family ownership')
    rating=p.get('rating'); reviews=p.get('reviews',0) or 0
    if rating is not None and reviews>=25:
        if rating<=3.7:score+=18;e.append(f'Low rating: {rating:.1f} ({reviews} reviews)');types.append('Reputation / Operations')
        elif rating<=4.0:score+=9;e.append(f'Moderate rating: {rating:.1f} ({reviews} reviews)');types.append('Reputation / Operations')
    own,hst,gr,mg=hits(n,OWN),hits(n,STRESS),hits(n,GROW),hits(n,MGR)
    if own:score+=22;e.append('Recent ownership/management transition signal');types.append('Ownership Transition')
    if hst:score+=20;e.append('Recent operating stress signal');types.append('Turnaround Candidate')
    if mg:score+=12;e.append('Recent management signal in public reporting');types.append('Leadership Vacancy')
    if gr:score+=14;e.append('Recent expansion/opening/reopening signal');types.append('Growth Stress')
    groups=sum(bool(x) for x in [w['hiring'] or w['management'],mj,own or hst or gr or mg,rating is not None and reviews>=25 and rating<=4.0,w['local']])
    conf='HIGH' if groups>=4 else 'MEDIUM' if groups>=2 else 'LOW'
    if conf=='LOW':score=min(score,69)
    if ch:score=min(score,25)
    return max(0,min(100,score)),conf,e,list(dict.fromkeys(types or ['Needs Verification'])),mj

def angle(types):
    if 'Leadership Vacancy' in types:return 'Lead with the management recruiting signal. Offer leadership stabilization, labor structure, accountability, SOPs and KPI discipline while they hire.'
    if 'Ownership Transition' in types:return 'Lead with the ownership transition. Offer a first-90-day operating assessment: leadership, labor, KPIs, profitability and team alignment.'
    if 'Turnaround Candidate' in types:return 'Lead with current operating pressure. Offer an operator-to-operator conversation around labor, systems, service execution, menu mix and profitability.'
    if 'Growth Stress' in types:return 'Lead with growth. Position JJ around replicable systems, leadership depth, training, opening execution and KPI discipline.'
    if 'Digital Opportunity' in types:return 'Lead with operations first; digital weakness can become a secondary JJ/Spectral opportunity after credibility is established.'
    return 'Verify the owner/operator and current need before outreach.'

def csvout(rows):
    s=io.StringIO();f=['score','confidence','business','address','rating','review_count','opportunity_types','why_this_is_a_lead','suggested_angle','website','google_maps','management_jobs'];w=csv.DictWriter(s,fieldnames=f);w.writeheader()
    for r in rows:w.writerow({'score':r['score'],'confidence':r['confidence'],'business':r['name'],'address':r['address'],'rating':r.get('rating',''),'review_count':r.get('reviews',''),'opportunity_types':' | '.join(r['types2']),'why_this_is_a_lead':' | '.join(r['evidence']),'suggested_angle':r['angle'],'website':r.get('website',''),'google_maps':r.get('google_maps',''),'management_jobs':' | '.join(x.get('title','') for x in r.get('manager_jobs',[]))})
    return s.getvalue().encode()

G=sec('GOOGLE_PLACES_API_KEY');J=sec('JOOBLE_API_KEY')
st.title('🎯 JJ Opportunity Radar')
st.caption('V4 • Map the market → detect signals → cross-reference evidence → rank real prospects')
with st.sidebar:
    st.header('Market Scan');market=st.text_input('Market','Sioux Falls, SD');cats=st.multiselect('Hospitality targets',list(CATS),default=['Bar & Grill','Tavern / Pub','Independent Restaurant','Brewery / Brewpub']);per=st.slider('Businesses per category',5,20,12);deep=st.slider('Deep-scan top businesses',5,40,20);days=st.select_slider('News lookback',[30,60,90,180,365],180);st.divider();st.write('✅ Google Places' if G else '❌ Google Places key needed');st.write('✅ Jooble Jobs' if J else '⚪ Jooble optional')
if not G:st.warning('V4 needs a Google Places API key. Add GOOGLE_PLACES_API_KEY to Streamlit Secrets. Jooble is optional.')
if st.button('🚀 SCAN MARKET FOR OPPORTUNITY',type='primary',use_container_width=True) and G:
    d={}
    with st.status('Building the hospitality market...',expanded=True) as status:
        for c in cats:
            try: ps=places(G,f'{CATS[c]} in {market}',per)
            except Exception as e:st.error(f'{c}: {e}');continue
            for p in ps:
                pid=p.get('id');name=(p.get('displayName') or {}).get('text','').strip()
                if not pid or not name:continue
                x=d.setdefault(pid,{'place_id':pid,'name':name,'address':p.get('formattedAddress',''),'website':p.get('websiteUri',''),'google_maps':p.get('googleMapsUri',''),'rating':p.get('rating'),'reviews':p.get('userRatingCount',0),'business_status':p.get('businessStatus',''),'cats':[]})
                if c not in x['cats']:x['cats'].append(c)
        st.write(f'Found {len(d)} unique hospitality businesses.')
        base=sorted(d.values(),key=lambda x:(chain(x['name']),-(x.get('reviews') or 0)))
        targets=base[:deep];out=[]
        all_jobs=market_jobs(J,market) if J else []
        if J: st.write(f'Loaded {len(all_jobs)} management job postings for market matching.')
        for i,p in enumerate(targets,1):
            st.write(f'{i}/{len(targets)} — {p["name"]}')
            w=scan_site(p.get('website',''));n=news(p['name'],market,days);j=match_jobs(all_jobs,p['name']) if J else []
            score,conf,e,types,mj=rank(p,w,n,j);r={**p,'score':score,'confidence':conf,'evidence':e,'types2':types,'manager_jobs':mj,'news':n,'angle':angle(types),'chain':chain(p['name'])};out.append(r);time.sleep(.03)
        tids={x['place_id'] for x in targets}
        for p in base:
            if p['place_id'] in tids:continue
            ch=chain(p['name']);out.append({**p,'score':5 if ch else 22,'confidence':'LOW','evidence':['Mapped hospitality business; not yet deep-scanned'],'types2':['Needs Verification'],'manager_jobs':[],'news':[],'angle':'Deep-scan this business before outreach.','chain':ch})
        out.sort(key=lambda x:(x['chain'],-x['score'],x['confidence']=='LOW',-(x.get('reviews') or 0)));st.session_state['radar']=out;status.update(label=f'Scan complete — {len(out)} businesses ranked',state='complete',expanded=False)
rows=st.session_state.get('radar',[])
if rows:
    indep=[x for x in rows if not x['chain']];qual=[x for x in indep if x['score']>=50];lead=[x for x in indep if 'Leadership Vacancy' in x['types2']]
    a,b,c,d=st.columns(4);a.metric('Market Businesses',len(rows));b.metric('Independent',len(indep));c.metric('Qualified 50+',len(qual));d.metric('Leadership Signals',len(lead));st.divider()
    for r in rows:
        label='⚪ CHAIN / LOW PRIORITY' if r['chain'] else '🔥 HIGH OPPORTUNITY' if r['score']>=75 else '🟠 QUALIFIED' if r['score']>=50 else '👀 WATCH' if r['score']>=30 else '🔎 VERIFY'
        with st.expander(f'{label} • {r["score"]}/100 • {r["confidence"]} CONFIDENCE • {r["name"]}'):
            st.write(f'**Address:** {r["address"]}')
            if r.get('rating') is not None:st.write(f'**Google rating:** {r["rating"]} ({r.get("reviews",0)} reviews)')
            st.write('**Opportunity type:** '+' • '.join(r['types2']));st.write('**WHY THIS IS A LEAD**')
            for e in r['evidence']:st.write('• '+e)
            st.write('**Suggested JJ opening**');st.write(r['angle'])
            for j in r.get('manager_jobs',[]):
                st.write(f"• {j.get('title','')} — {j.get('company','')} — {j.get('updated','')}")
                if j.get('link'):st.link_button('Open job',j['link'],use_container_width=True)
            for n in r.get('news',[])[:2]:
                st.write(f"• {n.get('title','')} — {n.get('source','')}")
                if n.get('url'):st.link_button('Open evidence',n['url'],use_container_width=True)
            x,y=st.columns(2)
            if r.get('website'):x.link_button('Website',r['website'],use_container_width=True)
            if r.get('google_maps'):y.link_button('Google Maps',r['google_maps'],use_container_width=True)
    st.download_button('⬇️ EXPORT RADAR LEADS TO CSV',csvout(rows),f'jj_opportunity_radar_{datetime.now():%Y%m%d_%H%M}.csv','text/csv',use_container_width=True)
st.caption('Radar scores are prospecting intelligence, not proof that a business needs consulting. Higher confidence requires multiple independent signals. Chains are intentionally capped low.')
