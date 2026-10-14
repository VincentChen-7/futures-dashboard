#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SGX 新交所铁矿期货(FEF)持仓量 自动更新脚本
数据源：SGX 公开 CDN（与期权同源，无 Akamai 拦截）
  https://links.sgx.com/1.0.0/derivatives-daily/{ID}/FUTURE.zip
  ID 规则：7544 = 2026-07-01，之后每个交易日 +1（周末不加）
商品代码：FEF（铁矿期货）；持仓量列：OINT
  - 总持仓量 = 所有 FEF 合约月 OINT 之和
  - 主力合约持仓量 = OINT 最大的合约月（COM_MM/COM_YY）
日期：直接使用 CSV 内的 DATE 字段（SGX 官方结算日戳，与用户 Excel 口径一致）

输出：sgx_futures.json  { dates:[8位], data:{date:{totalOI,dominantMonth,dominantOI,contracts}}, meta }
      sgx_futures_history.json  { dates:[8位], data:{date:{totalOI,dominantOI,dominantMonth}} }

用法：
  日常增量：python sgx_futures_auto_update.py
  历史回填：python sgx_futures_auto_update.py --backfill --min-date 2025-01-01 --start-id 7100
"""
import os, sys, json, io, csv, urllib.request, zipfile, datetime, time, ssl

# SGX CDN(links.sgx.com) 在本环境默认 SSL 证书校验会失败，需忽略校验（与期权脚本一致）
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'sgx_futures.json')
HIST = os.path.join(HERE, 'sgx_futures_history.json')
COM_CODE = 'FEF'
CDN = 'https://links.sgx.com/1.0.0/derivatives-daily/{id}/FUTURE.zip'
BACKFILL_START_ID = 7100
MAX_SCAN = 760          # 单次最多扫描的 ID 数（防死循环）
CONSEC_FAIL_LIMIT = 6   # 连续抓取失败上限（到达未来/数据尽头则停）
HIST_MIN = '20250701'   # 历史文件只保留 2025-07 起（供同比/环比，避免占用过多内存）
# 说明：sgx_futures.json 保留「2026-07-01 起全部」（累计，跨月不丢，汇总表近→远展示）；
#       sgx_futures_history.json 保留 2025-07 至今，仅供走势图的环比/同比叠加。
#       走势图仍按「当前月」过滤 sgx_futures.json，故折线图行为不变。

def today_ymd():
    return datetime.date.today().strftime('%Y%m%d')

def fetch_future(idn, retries=2):
    url = CDN.format(id=idn)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            data = urllib.request.urlopen(req, timeout=20, context=ctx).read()
            z = zipfile.ZipFile(io.BytesIO(data))
            name = [n for n in z.namelist() if n.lower().endswith('.csv')]
            if not name:
                return None
            return z.read(name[0]).decode('utf-8', errors='replace')
        except urllib.error.HTTPError:
            # 404/403 等：该 ID 无数据（周末/历史未保留/未来），直接跳过，不重试
            return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(1.0)
    return None

def aggregate(txt):
    """返回 (date_str, totalOI, dominantMonth, dominantOI, contracts) 或 None"""
    if not txt:
        return None
    rdr = list(csv.DictReader(io.StringIO(txt)))
    if not rdr:
        return None
    dates = sorted(set((r.get('DATE') or '').strip() for r in rdr if r.get('DATE')))
    date_str = dates[0] if dates else ''
    if not date_str:
        return None
    fef = [r for r in rdr if (r.get('COM') or '').strip() == COM_CODE]
    if not fef:
        return None
    contracts = {}
    total = 0
    for r in fef:
        mm = (r.get('COM_MM') or '').strip()
        yy = (r.get('COM_YY') or '').strip()
        key = f'{mm}/{yy}' if mm else '?'
        try:
            oi = int(r.get('OINT') or 0)
        except Exception:
            oi = 0
        contracts[key] = contracts.get(key, 0) + oi
        total += oi
    # 主力 = OINT 最大的合约月
    best = max(contracts.items(), key=lambda kv: kv[1]) if contracts else (None, 0)
    return date_str, total, best[0], best[1], contracts

def load_json(path):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding='utf-8'))
        except Exception:
            pass
    return {'dates': [], 'data': {}, 'meta': {}}

def save_json(path, obj):
    json.dump(obj, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

def run(backfill=False, min_date='2025-01-01', start_id=None):
    out = load_json(OUT)
    out.setdefault('dates', [])
    out.setdefault('data', {})
    out.setdefault('meta', {})
    hist = load_json(HIST)
    hist.setdefault('dates', [])
    hist.setdefault('data', {})

    today = today_ymd()
    if backfill:
        sid = int(start_id) if start_id else BACKFILL_START_ID
        # 回填：从 start_id 向前扫，记录 >= min_date 的数据
        min_d = min_date.replace('-', '')
        scanned = 0
        while scanned < MAX_SCAN:
            txt = fetch_future(sid)
            scanned += 1
            if txt is None:
                # 旧数据/CDN未保留/周末：跳过继续，不据此停止
                sid += 1
                continue
            res = aggregate(txt)
            if res is None:
                sid += 1
                continue
            date_str, total, dm, doi, contracts = res
            if date_str < min_d:
                # 已越过 min_date 之前，继续前进
                sid += 1
                continue
            if date_str > today:
                print(f'  遇到未来日期 {date_str}，停止回填')
                break
            _store(out, hist, date_str, total, dm, doi, contracts)
            out['meta']['last_id'] = sid
            sid += 1
        print(f'回填完成：扫描 {scanned} 个 ID')
    else:
        # 增量：从 last_id+1 向前扫，直到未来或无新数据
        sid = int(out.get('meta', {}).get('last_id', BACKFILL_START_ID)) + 1
        scanned = 0
        consec_fail = 0
        added = 0
        while scanned < 30:
            txt = fetch_future(sid)
            scanned += 1
            if txt is None:
                consec_fail += 1
                if consec_fail >= CONSEC_FAIL_LIMIT:
                    break
                sid += 1
                continue
            consec_fail = 0
            res = aggregate(txt)
            if res is None:
                sid += 1
                continue
            date_str, total, dm, doi, contracts = res
            if date_str > today:
                break
            if date_str in out['data']:
                # 已存在（重复），仍推进
                sid += 1
                continue
            _store(out, hist, date_str, total, dm, doi, contracts)
            out['meta']['last_id'] = sid
            added += 1
            sid += 1
        print(f'增量完成：新增 {added} 天，扫描 {scanned} 个 ID')

    # 裁剪：当月文件保留「2026-07-01 起全部」（累计，跨月不丢；折线图仍按当前月过滤）
    #       历史文件只保留 >= HIST_MIN(2025-07) 供环比/同比
    LIVE_FLOOR = '20260701'
    if out['data']:
        out['data'] = {d: v for d, v in out['data'].items() if d >= LIVE_FLOOR}
    hist['data'] = {d: v for d, v in hist['data'].items() if d >= HIST_MIN}

    # 整理排序
    out['dates'] = sorted(out['data'].keys())
    hist['dates'] = sorted(hist['data'].keys())
    out['lastUpdated'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    save_json(OUT, out)
    save_json(HIST, hist)
    print(f'已写 sgx_futures.json(当月): {len(out["dates"])} 天, 最新={out["dates"][-1] if out["dates"] else None}')
    print(f'已写 sgx_futures_history.json(2025-07起): {len(hist["dates"])} 天')

def _store(out, hist, date_str, total, dm, doi, contracts):
    out['data'][date_str] = {
        'totalOI': total,
        'dominantMonth': dm,
        'dominantOI': doi,
        'contracts': contracts,
    }
    hist['data'][date_str] = {
        'totalOI': total,
        'dominantMonth': dm,
        'dominantOI': doi,
    }

if __name__ == '__main__':
    backfill = '--backfill' in sys.argv
    min_date = '2025-01-01'
    start_id = None
    if '--min-date' in sys.argv:
        i = sys.argv.index('--min-date')
        if i + 1 < len(sys.argv):
            min_date = sys.argv[i + 1]
    if '--start-id' in sys.argv:
        i = sys.argv.index('--start-id')
        if i + 1 < len(sys.argv):
            start_id = sys.argv[i + 1]
    run(backfill=backfill, min_date=min_date, start_id=start_id)
