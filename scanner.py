#!/usr/bin/env python3
"""Official end-of-day universe scanner. No trading, credentials or third-party packages."""
import argparse
import datetime as dt
import html
import json
import math
import os
from pathlib import Path
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
SOURCES = {
    'TWSE': 'https://www.twse.com.tw/exchangeReport/MI_INDEX',
    'TPEX': 'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes',
}
TZ = ZoneInfo('Asia/Taipei')

def number(v):
    try:
        value = float(re.sub(r'<[^>]+>', '', str(v)).replace(',', '').replace(' ', ''))
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None

def atomic_json(path, obj):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    temporary.replace(path)

def fetch_day(market, day):
    compact = day.strftime('%Y%m%d')
    query = (f'?response=json&date={compact}&type=ALLBUT0999' if market == 'TWSE'
             else f'?date={day:%Y/%m/%d}&id=&response=json')
    request = Request(SOURCES[market] + query, headers={'User-Agent': 'ChanQuant-EOD/6.1', 'Accept': 'application/json'})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=35) as response:
                data = json.load(response)
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    if not isinstance(data, dict):
        raise ValueError('Unexpected response envelope')
    returned = str(data.get('date', ''))
    if returned and returned != compact:
        raise ValueError(f'Date mismatch: requested {compact}, received {returned}')
    tables = data.get('tables', [])
    # Support the legacy TWSE layout as well as the current tables envelope.
    if not tables and 'fields9' in data:
        tables = [{'fields': data['fields9'], 'data': data.get('data9', [])}]
    matching = []
    for table in tables:
        fields = [re.sub(r'<[^>]+>', '', str(x)).strip() for x in table.get('fields', [])]
        if ('證券代號' in fields or '代號' in fields) and ('收盤價' in fields or '收盤' in fields):
            matching.append((table, fields))
    if not matching:
        stat = str(data.get('stat', ''))
        if ('沒有符合' in stat or '查無' in stat or (market == 'TPEX' and tables and all(not t.get('data') for t in tables))):
            return []
        raise ValueError('No recognised daily-price table; refusing to treat a schema failure as a holiday')
    table, fields = matching[0]
    def index(*names):
        return next(i for i, f in enumerate(fields) if f in names)
    indices = [index('證券代號', '代號'), index('證券名稱', '名稱'), index('開盤價', '開盤'),
               index('最高價', '最高'), index('最低價', '最低'), index('收盤價', '收盤'),
               index('成交股數'), index('成交金額', '成交金額(元)')]
    rows = []
    for raw in table.get('data', []):
        if len(raw) <= max(indices):
            continue
        code, name, *values = [raw[i] for i in indices]
        code = str(code).strip()
        # Four-digit common shares only: exclude ETFs, warrants, preferred shares and TDRs.
        if not re.fullmatch(r'[1-9][0-9]{3}', code):
            continue
        values = [number(v) for v in values]
        if any(v is None for v in values):
            continue
        o, h, l, c, volume, amount = values
        if not (0 < l <= min(o, c) <= max(o, c) <= h and volume > 0 and amount > 0):
            continue
        rows.append((code, html.unescape(re.sub(r'<[^>]+>', '', str(name))).strip(),
                     [day.isoformat(), o, h, l, c, int(volume), int(amount)]))
    if table.get('data') and len(rows) < 100:
        raise ValueError(f'Only {len(rows)} common shares parsed; possible incomplete response')
    return rows

def merge_inclusions(bars):
    merged = []
    direction = 1
    for i, b in enumerate(bars):
        new = {'h': b[2], 'l': b[3], 'i': i}
        if merged:
            last = merged[-1]
            included = (new['h'] <= last['h'] and new['l'] >= last['l']) or (new['h'] >= last['h'] and new['l'] <= last['l'])
            if included:
                reducer = max if direction > 0 else min
                merged[-1] = {'h': reducer(last['h'], new['h']), 'l': reducer(last['l'], new['l']), 'i': i}
                continue
            direction = 1 if new['h'] > last['h'] else -1
        merged.append(new)
    return merged

def latest_center(bars):
    clean = merge_inclusions(bars)
    pivots = []
    for j in range(1, len(clean) - 1):
        a, b, c = clean[j-1:j+2]
        top = b['h'] > max(a['h'], c['h']) and b['l'] > max(a['l'], c['l'])
        bottom = b['l'] < min(a['l'], c['l']) and b['h'] < min(a['h'], c['h'])
        if not (top or bottom):
            continue
        p = {'type': 1 if top else -1, 'price': b['h'] if top else b['l'], 'i': b['i'], 'j': j, 'confirmed': c['i']}
        if not pivots:
            pivots.append(p)
        elif pivots[-1]['type'] == p['type']:
            if (p['price'] - pivots[-1]['price']) * p['type'] > 0:
                pivots[-1] = p
        elif p['j'] - pivots[-1]['j'] >= 4:
            pivots.append(p)
    # Three alternating price legs overlap; this is an explicit simplified rule, not full Chan theory.
    for end in range(len(pivots)-1, 2, -1):
        ps = pivots[end-3:end+1]
        lows = [min(a['price'], b['price']) for a, b in zip(ps, ps[1:])]
        highs = [max(a['price'], b['price']) for a, b in zip(ps, ps[1:])]
        lower, upper = max(lows), min(highs)
        if lower < upper and len(bars)-36 <= ps[-1]['i'] <= len(bars)-4:
            return {'lower': lower, 'upper': upper, 'end_index': ps[-1]['i'], 'confirmed_index': ps[-1]['confirmed'],
                    'start': bars[ps[0]['i']][0], 'end': bars[ps[-1]['i']][0]}
    return None

def evaluate(code, stock, market_date):
    bars = stock['bars']
    current = bars[-1]
    result = {'code': code, 'name': stock['name'], 'market': stock['market'], 'date': current[0], 'close': current[4],
              'volume': current[5], 'amount': current[6], 'bars': len(bars), 'signal': '觀察', 'score': 0,
              'change_pct': round((current[4]/bars[-2][4]-1)*100, 2) if len(bars)>1 else None}
    if current[0] != market_date:
        result['signal'] = '缺當日成交'
        return result
    if len(bars) < 60:
        result['signal'] = '資料累積中'
        return result
    closes = [b[4] for b in bars]
    ma20, ma60 = statistics.mean(closes[-20:]), statistics.mean(closes[-60:])
    v20 = statistics.mean(b[5] for b in bars[-21:-1])
    vr = current[5] / v20 if v20 else 0
    result.update(ma20=round(ma20, 2), ma60=round(ma60, 2), volume_ratio=round(vr, 2))
    if current[6] < 20_000_000 or current[5] < 500_000 or current[4] < 10:
        result['signal'] = '流動性未達'
        return result
    trend = current[4] > ma20 > ma60
    center = latest_center(bars[:-1])  # Today's bar cannot confirm/revise today's reference center.
    reasons = []
    if center and trend:
        zg = center['upper']
        if current[4] > zg and bars[-2][4] <= zg and vr >= 1.2:
            result['signal'] = '中樞突破候選'
            reasons = ['收盤突破已確認中樞上緣', '收盤 > MA20 > MA60', '成交量 ≥ 前20日均量1.2倍']
        else:
            first = max(center['confirmed_index']+1, len(bars)-16)
            for k in range(first, len(bars)-2):
                after = bars[k+1:-1]
                if bars[k][4] > zg and after and min(b[3] for b in after) > zg and current[3] > zg:
                    recent_low = min(b[3] for b in bars[-5:])
                    if recent_low <= zg*1.04 and current[4] > bars[-2][4] and vr >= 0.8:
                        result['signal'] = '中樞回踩候選'
                        reasons = ['突破後回檔低點守在中樞上緣之上', '近5日低點距上緣 ≤ 4%', '收盤回升且 > MA20 > MA60']
                        break
        result['center'] = {k: v for k, v in center.items() if not k.endswith('index')}
    if not reasons and trend and current[4] > max(b[2] for b in bars[-21:-1]) and vr >= 1.2:
        result['signal'] = '趨勢新高觀察'
        reasons = ['收盤突破前20日高點', '收盤 > MA20 > MA60', '成交量 ≥ 前20日均量1.2倍；非纏論買點']
    if reasons:
        result['score'] = min(100, round(50 + min(vr, 3)*10 + min((current[4]/ma60-1)*100, 15)))
        result['reasons'] = reasons
        result['candles'] = bars[-80:]
    return result

def update_market(market, history, days, delay):
    state = history['markets'].setdefault(market, {'fetched': [], 'stocks': {}})
    fetched = set(state['fetched'])
    errors = []
    for day in days:
        if day.weekday() >= 5 or day.isoformat() in fetched:
            continue
        try:
            rows = fetch_day(market, day)
            for code, name, bar in rows:
                stock = state['stocks'].setdefault(code, {'name': name, 'market': market, 'bars': []})
                stock['name'] = name
                by_date = {b[0]: b for b in stock['bars']}
                by_date[bar[0]] = bar
                stock['bars'] = sorted(by_date.values(), key=lambda b: b[0])[-180:]
            fetched.add(day.isoformat())
            print(f'{market} {day} {len(rows)} shares', flush=True)
        except Exception as exc:
            errors.append({'market': market, 'date': day.isoformat(), 'error': str(exc)[:180]})
            print(f'ERROR {market} {day}: {exc}', flush=True)
        time.sleep(delay)
    state['fetched'] = sorted(fetched)[-300:]
    return errors

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=120)
    parser.add_argument('--delay', type=float, default=1.1)
    parser.add_argument('--as-of', type=dt.date.fromisoformat)
    args = parser.parse_args()
    now = dt.datetime.now(TZ)
    # Do not label intraday data as final EOD; fetch today only after 17:00 Taipei.
    end = args.as_of or now.date() - dt.timedelta(days=0 if now.hour >= 17 else 1)
    days = [end - dt.timedelta(days=i) for i in range(args.days-1, -1, -1)]
    history_path = ROOT / 'history.json'
    history = json.loads(history_path.read_text()) if history_path.exists() else {'version': 1, 'markets': {}}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(update_market, m, history, days, args.delay) for m in SOURCES]
        errors = sum((f.result() for f in futures), [])
    if not any(s.get('stocks') for s in history['markets'].values()):
        raise SystemExit('No verified market data; existing published files were not overwritten')
    markets, stocks = [], []
    for market in SOURCES:
        state = history['markets'].get(market, {'stocks': {}})
        latest = max((b['bars'][-1][0] for b in state['stocks'].values() if b['bars']), default=None)
        evaluated = [evaluate(code, s, latest) for code, s in state['stocks'].items() if s['bars']]
        # Remove delisted/very stale securities from the current universe.
        evaluated = [s for s in evaluated if (end-dt.date.fromisoformat(s['date'])).days <= 10]
        warm = sum(s['bars'] >= 60 and s['date'] == latest for s in evaluated)
        markets.append({'market': market, 'date': latest, 'count': len(evaluated), 'ready': warm,
                        'status': 'error' if not latest else 'stale' if (end-dt.date.fromisoformat(latest)).days>4 else 'ok'})
        stocks.extend(evaluated)
    stocks.sort(key=lambda s: (-s['score'], -s['amount'], s['code']))
    output = {'version': '6.1', 'generated_at': now.isoformat(timespec='seconds'), 'as_of': end.isoformat(),
              'status': 'partial' if errors or any(m['status']!='ok' for m in markets) else 'ok',
              'markets': markets, 'errors': errors, 'stocks': stocks,
              'sources': SOURCES, 'rules': {'min_bars': 60, 'min_amount': 20000000, 'min_volume': 500000, 'min_price': 10},
              'notice': '盤後日線研究篩選；簡化分型／筆／三筆重疊中樞，非完整正統纏論，未實作線段、背馳或週／60分鐘共振。未還原權息；除權息及分割可能造成假訊號。候選不等於建議買進。'}
    atomic_json(history_path, history)
    atomic_json(ROOT/'scan_results.json', output)
    print(json.dumps({'stocks': len(stocks), 'candidates': sum(s['score']>0 for s in stocks), 'markets': markets, 'errors': len(errors)}, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    main()
