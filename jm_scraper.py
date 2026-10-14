import urllib.request, ssl, json, datetime, time, os, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
BASE="https://qhhqzl.eastmoney.com/marketFutuWeb/dragonAndTigerInfo/"
HEAD={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64)','Referer':'https://qhweb.eastmoney.com/lhb/dkcc/dce/jm'}

# 期货公司 -> 东方财富席位名称关键字
BROKERS = {
    '国君': '国泰君安',
    '永安': '永安期货',
    '东证': '东证期货',
    '中信': '中信期货',
    '银河': '银河期货',
}

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

def find_long(longs, kw):
    for it in (longs or []):
        if kw in it.get('futureCompanyName',''):
            return it.get('longNum')
    return None

def find_short(shorts, kw):
    for it in (shorts or []):
        if kw in it.get('futureCompanyName',''):
            return it.get('shortNum')
    return None

def net_of(d):
    if d['long'] is None or d['short'] is None:
        return None
    return d['long'] - d['short']

def get_day(ymd):
    url = BASE+"getLongAndShortPosition?date=%s&contract=jm&market=114"%ymd
    j = fetch_json(url)
    if not j or j.get('code')!=10000 or 'data' not in j:
        return ymd, None
    data = j['data']
    td = data.get('tradeDate')
    # only accept if tradeDate matches (filter holiday stale data)
    if td != ymd:
        return ymd, None
    longs = data.get('longInfoList') or []
    shorts = data.get('shortInfoList') or []
    rec = {'date': ymd}
    for name, kw in BROKERS.items():
        lng = find_long(longs, kw)
        sht = find_short(shorts, kw)
        rec[name] = {'long': lng, 'short': sht, 'net': net_of({'long':lng,'short':sht})}
    return ymd, rec

start = datetime.date(2026,1,1)
end = datetime.date.today()
all_dates = []
d = start
while d <= end:
    if d.weekday() < 5:
        all_dates.append(d.strftime('%Y%m%d'))
    d += datetime.timedelta(days=1)

print("weekday dates:", len(all_dates), flush=True)
out = {}
lock = threading.Lock()
t0=time.time()
with ThreadPoolExecutor(max_workers=8) as ex:
    futs=[ex.submit(get_day,y) for y in all_dates]
    cnt=0
    for f in as_completed(futs):
        ymd, rec = f.result()
        if rec:
            with lock: out[ymd]=rec
        cnt+=1
        if cnt%20==0:
            print("progress %d/%d got=%d %.1fs"%(cnt,len(all_dates),len(out),time.time()-t0), flush=True)

records=[out[ymd] for ymd in sorted(out.keys())]
final = {
    'lastUpdated': end.strftime('%Y-%m-%d'),
    'source': '东方财富期货龙虎榜（数据来源：大连商品交易所 焦煤jm 每日持仓排名）',
    'brokerages': list(BROKERS.keys()),
    'records': records
}
outpath = os.path.join(os.path.dirname(__file__), 'JM_data.json')
with open(outpath,'w',encoding='utf-8') as fp:
    json.dump(final, fp, ensure_ascii=False, indent=1)
print("WROTE JM_data.json days=%d elapsed=%.1fs"%(len(records), time.time()-t0))
print("date range:", records[0]['date'], "~", records[-1]['date'])
print("last 2:", json.dumps(records[-2:], ensure_ascii=False))
