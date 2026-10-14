import urllib.request, ssl, json, datetime, time, os
from concurrent.futures import ThreadPoolExecutor, as_completed

ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
BASE="https://qhhqzl.eastmoney.com/marketFutuWeb/dragonAndTigerInfo/"
HEAD={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64)','Referer':'https://qhweb.eastmoney.com/lhb/dkcc/dce/i'}

# commodity -> (market, 高盛出力key, 摩根出力key(铁矿才有))
COMMODITIES = [
    ('i',  '114', 'gs_iron',  'ms_iron'),
    ('rb', '113', 'gs_rebar', None),
    ('hc', '113', 'gs_hrc',   None),
]

def fetch_json(url, retries=3):
    for attempt in range(retries):
        try:
            req=urllib.request.Request(url, headers=HEAD)
            with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                return json.loads(r.read().decode('utf-8','ignore'))
        except Exception:
            if attempt==retries-1: return None
            time.sleep(1.0)
    return None

def find_in_list(lst, keyword):
    for it in (lst or []):
        if keyword in it.get('futureCompanyName',''):
            return it.get('longNum') or it.get('shortNum')
    return None

def net_of(d):
    if d['long'] is None or d['short'] is None:
        return None
    return d['long'] - d['short']

def get_contract(ymd, code, market):
    url = BASE+"getLongAndShortPosition?"+ "&".join(["date="+ymd,"contract="+code,"market="+market])
    j = fetch_json(url)
    if not j or j.get('code')!=10000 or 'data' not in j:
        return None
    data = j['data']
    td = data.get('tradeDate')
    longs = data.get('longInfoList') or []
    shorts = data.get('shortInfoList') or []
    return {
        'tradeDate': td,
        'gs_long': find_in_list(longs,'高盛期货'),
        'gs_short': find_in_list(shorts,'高盛期货'),
        'ms_long': find_in_list(longs,'摩根大通'),
        'ms_short': find_in_list(shorts,'摩根大通'),
    }

def get_day(ymd):
    res={}
    matched=False
    for code, market, gk, mk in COMMODITIES:
        c=get_contract(ymd, code, market)
        if c and c['tradeDate']==ymd:
            matched=True
            res[code]=c
    return ymd, (res if matched else None)

start = datetime.date(2026,1,1)
end = datetime.date.today()

outpath = os.path.join(os.path.dirname(__file__), 'data.json')
existing = {}
if os.path.exists(outpath):
    try:
        with open(outpath, 'r', encoding='utf-8') as fp:
            for rec in json.load(fp).get('records', []):
                existing[rec['date']] = rec
    except Exception as e:
        print("failed to load existing data.json:", e, flush=True)

tasks=[]
d=start
while d<=end:
    if d.weekday()<5:
        ymd=d.strftime('%Y%m%d')
        if existing.get(ymd,{}).get('gs_iron'):
            pass  # 已抓过，跳过
        else:
            tasks.append(ymd)
    d+=datetime.timedelta(days=1)

print("tasks to process:", len(tasks), flush=True)
t0=time.time()
if tasks:
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs=[ex.submit(get_day, ymd) for ymd in tasks]
        cnt=0
        for f in as_completed(futs):
            ymd,res=f.result()
            if res:
                rec={'date':ymd}
                for code, market, gk, mk in COMMODITIES:
                    c=res.get(code)
                    if c:
                        rec[gk]={'long':c['gs_long'],'short':c['gs_short'],
                                 'net':net_of({'long':c['gs_long'],'short':c['gs_short']})}
                        if mk:
                            rec[mk]={'long':c['ms_long'],'short':c['ms_short'],
                                     'net':net_of({'long':c['ms_long'],'short':c['ms_short']})}
                    else:
                        rec[gk]={'long':None,'short':None,'net':None}
                        if mk: rec[mk]={'long':None,'short':None,'net':None}
                existing[ymd]=rec
            cnt+=1
            if cnt%20==0:
                print("progress %d/%d elapsed %.1fs"%(cnt,len(tasks),time.time()-t0), flush=True)

records = [existing[ymd] for ymd in sorted(existing.keys())]
for r in records:
    r.pop('seasonal', None)   # 退回合约视角前，移除 seasonal 维度
last_date = records[-1]['date'] if records else end.strftime('%Y%m%d')

final = {
    'lastUpdated': last_date,
    'source': '东方财富期货龙虎榜（数据来源：大连商品交易所 / 上海期货交易所 每日持仓排名）',
    'records': records
}
with open(outpath,'w',encoding='utf-8') as fp:
    json.dump(final, fp, ensure_ascii=False, indent=1)
print("WROTE data.json days=%d elapsed=%.1fs"%(len(records), time.time()-t0))
print("last 3:", json.dumps(records[-3:], ensure_ascii=False)[:600])
