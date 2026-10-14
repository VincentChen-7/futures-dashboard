#!/usr/bin/env python3
"""SGX 期权持仓自动更新：从 links.sgx.com 抓取最新 OPTION.zip 并并入 sgx_options.json。
   用法: python sgx_auto_update.py
   逻辑: 读取已有最新日期 -> 从下个交易日ID起向前抓 -> 处理 DATE<=今天 的新交易日 -> 并入。
   数据源(CDN, 无Akamai): https://links.sgx.com/1.0.0/derivatives-daily/{ID}/OPTION.zip
   ID规则: 7544 = 2026-07-01, 之后每个交易日 +1。"""
import urllib.request, ssl, io, zipfile, subprocess, os, sys, datetime, json

ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
BASE="https://links.sgx.com/1.0.0/derivatives-daily/"
HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable  # 自动使用当前解释器（兼容本地 Windows 与 GitHub Linux Runner）
PROC = os.path.join(HERE, "sgx_options_processor.py")
ANCHOR_ID = 7544          # 2026-07-01
ANCHOR_DATE = datetime.date(2026, 7, 1)

def fetch(url):
    req=urllib.request.Request(url, headers={'User-Agent':UA})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r: return r.read()

def date_of_zip(data):
    if data[:15].lower().startswith(b'<!doctype') or b'no record' in data[:200].lower():
        return None
    try:
        z=zipfile.ZipFile(io.BytesIO(data))
        with z.open(z.namelist()[0]) as f:
            for _ in range(30):
                line=f.readline().decode('utf-8',errors='replace').strip()
                if not line or line.startswith('DATE'): continue
                return line.split(',')[0]
    except Exception:
        return None
    return None

def id_for(date):
    return ANCHOR_ID + sum(1 for d in range((date-ANCHOR_DATE).days) if False)  # placeholder

def main():
    json_path = os.path.join(HERE, 'sgx_options.json')
    existing = {'dates': [], 'data': {}}
    if os.path.exists(json_path):
        with open(json_path, encoding='utf-8') as f:
            existing = json.load(f)
    dates = existing.get('dates', [])
    last_date = datetime.date.fromisoformat(dates[-1]) if dates else (ANCHOR_DATE - datetime.timedelta(days=1))
    print(f"已有最新日期: {dates[-1] if dates else '无'}")

    today = datetime.date.today()
    # 计算 last_date 对应的下一个 ID：必须用「交易日(周一~周五)计数」，不能用日历天
    # 否则 07-13 会被算成 7544+12=7556，直接跳过 07-14(7553) 永远抓不到
    def trading_days_between(start, end):
        cnt = 0; d = start
        while d < end:
            if d.weekday() < 5:
                cnt += 1
            d += datetime.timedelta(days=1)
        return cnt
    start_id = ANCHOR_ID + trading_days_between(ANCHOR_DATE, last_date) + 1  # last_date 的下一个交易日 ID
    idn = start_id
    added = []
    none_streak = 0
    for _ in range(60):
        try:
            data = fetch(f"{BASE}{idn}/OPTION.zip")
        except Exception as e:
            print(f"ID {idn} 下载异常: {e}"); idn += 1; none_streak += 1
            if none_streak > 8: break
            continue
        d = date_of_zip(data)
        if d is None:
            idn += 1; none_streak += 1
            if none_streak > 8: 
                print("连续8次无数据，停止(可能已到未来)。"); break
            continue
        none_streak = 0
        # 解析CSV日期(YYYYMMDD)为date对象后比较, 避免字符串/日期格式混用(含'-'的isoformat导致误判)
        try:
            d_date = datetime.datetime.strptime(d, "%Y%m%d").date()
        except Exception:
            idn += 1; continue
        if dates and d_date <= last_date:
            idn += 1; continue  # 已处理过
        if d_date > today:
            print(f"ID {idn} -> {d} 超过今天，停止。"); break
        # 新交易日, 处理
        z=zipfile.ZipFile(io.BytesIO(data)); csv_name=z.namelist()[0]
        with z.open(csv_name) as f: raw=f.read()
        tmp=os.path.join(HERE, f"_sgx_{d}.csv")
        with open(tmp,'wb') as w: w.write(raw)
        print(f"\n=== 新增 {d} (ID {idn}) ===")
        r=subprocess.run([PY, PROC, "--file", tmp, "--date", d], capture_output=True, text=True)
        print(r.stdout.strip())
        if r.returncode!=0: print("ERR", r.stderr.strip())
        os.remove(tmp)
        added.append(d)
        idn += 1
    print(f"\n✅ 本次新增 {len(added)} 个交易日: {added}")

if __name__=='__main__':
    main()
