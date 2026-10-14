#!/usr/bin/env python3
"""
SGX Options Data Processor - CSV format from SGX Historical Settlement Data

Usage:
    python sgx_options_processor.py --file <csv_path> --date YYYYMMDD [--output sgx_options.json]
    python sgx_options_processor.py --merge  # merge existing data and recalculate summary
"""

import csv
import json
import os
import argparse
from collections import defaultdict
from datetime import datetime


def process_csv_file(filepath, target_date=None):
    """
    Process SGX Historical Settlement CSV file.
    
    Columns: DATE,COM,COM_MM,COM_YY,OPT,STRIKE,OPEN,HIGH,LOW,CLOSE,SETTLE,VOLUME,OINT,SERIES
    
    Filters:
      - COM = 'FEF' (Iron Ore Futures options)
      - OPT = 'C' (Call) or 'P' (Put)
      
    Aggregates:
      - By STRIKE price: sum OINT across all months/series
      - Splits into call_data / put_data by strike
      - Computes daily totals
    """
    
    # Read CSV - handle BOM
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # Filter FEF only
    fef_rows = [r for r in rows if r['COM'].strip() == 'FEF']
    print(f"  总行数: {len(rows)}, FEF行数: {len(fef_rows)}")
    
    if not fef_rows:
        print("  ⚠ 未找到FEF数据！")
        return None
    
    # Detect date from first row's DATE column (or use --date override)
    date_key = target_date or fef_rows[0]['DATE'].strip()
    print(f"  日期: {date_key}")
    
    # Aggregate by (STRIKE, OPT) -> sum OINT
    call_by_strike = defaultdict(int)   # strike -> total call OI
    put_by_strike = defaultdict(int)    # strike -> total put OI
    # 按合约月份(COM_MM)再分组，用于区分主力合约在不同行权价上的变化
    contracts = defaultdict(lambda: {'call': defaultdict(int), 'put': defaultdict(int)})

    for r in fef_rows:
        opt_type = r['OPT'].strip().upper()
        strike = r['STRIKE'].strip()
        mm = (r.get('COM_MM') or '').strip()
        try:
            oint_val = int(r['OINT'] or '0')
        except ValueError:
            oint_val = 0

        if oint_val == 0:
            continue

        if opt_type == 'C':
            call_by_strike[strike] += oint_val
            if mm: contracts[mm]['call'][strike] += oint_val
        elif opt_type == 'P':
            put_by_strike[strike] += oint_val
            if mm: contracts[mm]['put'][strike] += oint_val
    
    # Sort strikes numerically
    all_strikes = sorted(set(list(call_by_strike.keys()) + list(put_by_strike.keys())),
                         key=lambda s: float(s))
    
    call_dict = {s: call_by_strike.get(s, 0) for s in all_strikes}
    put_dict = {s: put_by_strike.get(s, 0) for s in all_strikes}
    
    total_call = sum(call_dict.values())
    total_put = sum(put_dict.values())
    
    # 合约月份维度（主力合约区分用）
    contracts_out = {}
    for mm in contracts:
        contracts_out[mm] = {
            'call': {s: contracts[mm]['call'].get(s, 0) for s in sorted(contracts[mm]['call'].keys(), key=lambda x: float(x))},
            'put': {s: contracts[mm]['put'].get(s, 0) for s in sorted(contracts[mm]['put'].keys(), key=lambda x: float(x))},
        }

    result = {
        'date': date_key,
        'call': call_dict,
        'put': put_dict,
        'contracts': contracts_out,
        'summary': {
            'totalCall': total_call,
            'totalPut': total_put,
            'netPosition': total_call - total_put,
            'strikeCount': len(all_strikes),
            'strikesWithCall': len([s for s in all_strikes if call_dict[s] > 0]),
            'strikesWithPut': len([s for s in all_strikes if put_dict[s] > 0]),
        }
    }
    
    print(f"  CALL总量: {total_call:,}, PUT总量: {total_put:,}, 净持仓: {total_call - total_put:,}")
    print(f"  行权价数量: {len(all_strikes)} ({result['summary']['strikesWithCall']}有CALL, {result['summary']['strikesWithPut']}有PUT)")
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Process SGX Options CSV data')
    parser.add_argument('--file', help='Path to SGX Historical Settlement CSV file')
    parser.add_argument('--date', help='Override date key (YYYYMMDD), useful when CSV lacks date column')
    parser.add_argument('--output', default=None, help='Output JSON path')
    parser.add_argument('--merge', action='store_true', help='Recalculate daily summaries from existing json')
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = args.output or os.path.join(base_dir, 'sgx_options.json')
    
    # Load existing data if any
    existing = {'dates': [], 'data': {}, 'lastUpdated': ''}
    if os.path.exists(output_path):
        with open(output_path, 'r', encoding='utf-8') as f:
            existing = json.load(f)
    
    if args.merge:
        # Just recalculate summaries
        print("重新计算每日汇总...")
        for dk in existing.get('dates', []):
            d = existing['data'].get(dk, {})
            if 'call' in d:
                tc = sum(d['call'].values())
                tp = sum(d['put'].values())
                d['summary'] = {
                    'totalCall': tc,
                    'totalPut': tp,
                    'netPosition': tc - tp,
                }
        existing['lastUpdated'] = datetime.now().strftime('%Y-%m-%d %H:%M')
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        print(f"已更新: {output_path}")
        return
    
    if not args.file:
        parser.print_help()
        print("\nExample:")
        print(f"  python {os.path.basename(__file__)} --file 0710OPT.csv --date 20260710")
        return
    
    # Process single file
    print(f"\n处理文件: {args.file}")
    processed = process_csv_file(args.file, target_date=args.date)
    
    if not processed:
        print("处理失败，无数据产出。")
        return
    
    date_key = processed['date']
    
    # Merge into existing (don't overwrite other dates)
    existing['data'][date_key] = {
        'call': processed['call'],
        'put': processed['put'],
        'contracts': processed.get('contracts', {}),
        'summary': processed['summary'],
    }
    
    # Update dates list (sorted)
    if date_key not in existing['dates']:
        existing['dates'].append(date_key)
        existing['dates'].sort()
    
    existing['lastUpdated'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    existing['source'] = 'SGX Historical Settlement Data (FEF Iron Ore Options)'
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 已保存到: {output_path}")
    print(f"   包含 {len(existing['dates'])} 个交易日: {existing['dates']}")


if __name__ == '__main__':
    main()
