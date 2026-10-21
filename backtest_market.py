#!/usr/bin/env python3
"""Point-in-time replay of V6.1 on official daily OHLCV snapshots."""
import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import statistics
import scanner

ROOT = Path(__file__).resolve().parent
DEFAULTS = dict(capital=1_000_000, max_positions=10, allocation=0.10, risk_fraction=0.005,
                max_stop_fraction=0.08, commission=0.001425, minimum_fee=20,
                sell_tax=0.003, slippage=0.001, lot_size=1000,
                volume_participation=0.01, holding_bars=20, target_r=2)
SIGNALS = {'all': {'中樞突破候選','中樞回踩候選','趨勢新高觀察'},
           'chan': {'中樞突破候選','中樞回踩候選'}, 'trend': {'趨勢新高觀察'}}

def fee(value, config):
    return max(config['minimum_fee'], math.ceil(value*config['commission']))

def tick(price):
    return 0.01 if price < 10 else 0.05 if price < 50 else 0.1 if price < 100 else 0.5 if price < 500 else 1 if price < 1000 else 5

def tick_round(price, up=False):
    step = tick(price)
    return round((math.ceil(price/step-1e-9) if up else math.floor(price/step+1e-9))*step, 2)

def locked(bar):
    return abs(bar[2]-bar[3]) < 1e-9

def exit_cash(price, shares, config):
    gross = price*shares
    commission = fee(gross, config)
    tax = math.ceil(gross*config['sell_tax'])
    slip = gross*config['slippage']
    return gross-commission-tax-slip, commission+tax+slip

def protective_exit(bar, stop, target):
    """Daily ambiguity is resolved against the strategy: stop before target."""
    if locked(bar):
        return None
    if bar[1] <= stop:
        return bar[1], 'gap_stop', False
    if bar[1] >= target:
        return bar[1], 'gap_target', False
    if bar[3] <= stop:
        return stop, 'stop', bar[2] >= target
    if bar[2] >= target:
        return target, 'target', False
    return None

def prepare(history, start, end):
    stocks = {}
    market_dates = {}
    for market, state in history['markets'].items():
        market_dates[market] = set()
        for code, item in state['stocks'].items():
            if not scanner.common_stock(code,item['name']):
                continue
            bars = [b for b in item['bars'] if b[0] <= end]
            if not bars:
                continue
            key = market+':'+code
            stocks[key] = {'code':code,'name':item['name'],'market':market,'bars':bars,
                           'by_date':{b[0]:(i,b) for i,b in enumerate(bars)}}
            market_dates[market].update(b[0] for b in bars)
    dates = sorted(set.union(*market_dates.values()))
    evaluation_dates = [d for d in dates if start <= d <= end]
    if not evaluation_dates:
        raise ValueError('No trading dates in requested period')
    # Include the last session before the first entry date to allow a next-open order.
    before = [d for d in dates if d < evaluation_dates[0]]
    signal_dates = set(evaluation_dates + before[-1:])
    candidates = collections.defaultdict(list)
    screened = set()
    eligible = set()
    daily_coverage = collections.Counter()
    for count,(key,item) in enumerate(stocks.items(),1):
        for i,b in enumerate(item['bars']):
            if b[0] not in signal_dates:
                continue
            screened.add(key)
            if i < 59:
                continue
            eligible.add(key)
            daily_coverage[b[0]] += 1
            # Each call receives only bars that existed at this day's close.
            prefix = item['bars'][max(0,i-179):i+1]
            row = scanner.evaluate(item['code'], {'name':item['name'],'market':item['market'],'bars':prefix}, b[0])
            if row['score']:
                row.pop('candles',None)
                row['key'] = key
                row['initial_stop'] = tick_round(min(x[3] for x in prefix[-5:])*0.995)
                candidates[b[0]].append(row)
        if count % 300 == 0:
            print(f'Signals: {count}/{len(stocks)} securities',flush=True)
    for rows in candidates.values():
        rows.sort(key=lambda s:(-s['score'],-s['amount'],s['key']))
    previous = {d:dates[dates.index(d)-1] if dates.index(d)>0 else None for d in evaluation_dates}
    coverage = {'screened_symbols':len(screened), 'symbols_with_60_bars':len(eligible),
                'market_symbols':{m:sum(1 for k in screened if k.startswith(m+':')) for m in market_dates},
                'trading_sessions':len(evaluation_dates), 'daily_warmup_coverage':dict(daily_coverage),
                'signal_events':sum(len(candidates[d]) for d in signal_dates),
                'entry_window_signal_events':sum(len(candidates.get(previous[d],[])) for d in evaluation_dates),
                'signal_symbols':len({s['key'] for d in signal_dates for s in candidates[d]})}
    return stocks,evaluation_dates,previous,dict(candidates),coverage

def simulate(stocks, dates, previous, candidates, group='all', config=None):
    cfg = DEFAULTS | (config or {})
    cash = float(cfg['capital'])
    positions = {}
    trades, curve = [], []
    skips = collections.Counter()
    ambiguous = 0
    peak = cash
    minimum_dd = 0
    fees_total = 0
    exposures = []

    def value(date, opening=False):
        total = cash
        for key,p in positions.items():
            found = stocks[key]['by_date'].get(date)
            price = found[1][1 if opening else 4] if found else p['last_close']
            total += exit_cash(price,p['shares'],cfg)[0]
        return total

    def close(key,date,price,reason,amb=False):
        nonlocal cash,fees_total,ambiguous
        p = positions.pop(key)
        received,cost = exit_cash(price,p['shares'],cfg)
        cash += received
        fees_total += cost
        ambiguous += int(amb)
        pnl = received-p['cost']
        trades.append({'market':stocks[key]['market'],'code':stocks[key]['code'],'name':stocks[key]['name'],
                       'signal':p['signal'],'signal_date':p['signal_date'],'entry_date':p['entry_date'],
                       'exit_date':date,'entry_price':p['entry_price'],'exit_price':price,
                       'shares':p['shares'],'entry_cost':round(p['cost'],2),'pnl':round(pnl,2),
                       'net_return_pct':round(100*pnl/p['cost'],6),'reason':reason,
                       'holding_bars':p['holding'],'costs':round(p['entry_friction']+cost,2),
                       'same_bar_stop_target':amb})

    for date in dates:
        # A close-derived exit order can execute only at a subsequent session's open.
        for key,p in list(positions.items()):
            found = stocks[key]['by_date'].get(date)
            if found and p['pending'] and not locked(found[1]):
                close(key,date,found[1][1],p['pending'])

        opening_equity = value(date,True)
        for s in candidates.get(previous[date],[]):
            if s['signal'] not in SIGNALS[group]:
                continue
            key = s['key']
            if key in positions:
                skips['already_held'] += 1
                continue
            if len(positions) >= cfg['max_positions']:
                skips['position_limit'] += 1
                continue
            found = stocks[key]['by_date'].get(date)
            if not found:
                skips['missing_next_session'] += 1
                continue
            bar = found[1]
            if locked(bar):
                skips['one_price_bar'] += 1
                continue
            price,stop = bar[1],s['initial_stop']
            risk = price-stop
            if risk <= 0 or risk/price > cfg['max_stop_fraction']:
                skips['invalid_or_wide_stop'] += 1
                continue
            allocation = min(cash, opening_equity*cfg['allocation'])
            risk_per_share = risk+price*(2*cfg['commission']+cfg['sell_tax']+2*cfg['slippage'])
            max_shares = min(allocation/(price*(1+cfg['commission']+cfg['slippage'])),
                             opening_equity*cfg['risk_fraction']/risk_per_share,
                             s['volume']*cfg['volume_participation'])
            shares = math.floor(max_shares/cfg['lot_size'])*cfg['lot_size']
            if shares <= 0:
                skips['capital_or_risk_below_one_lot'] += 1
                continue
            gross = shares*price
            friction = fee(gross,cfg)+gross*cfg['slippage']
            cost = gross+friction
            if cost > cash+1e-7:
                skips['cash_limit'] += 1
                continue
            cash -= cost
            fees_total += friction
            positions[key] = {'signal':s['signal'],'signal_date':s['date'],'entry_date':date,
                              'entry_price':price,'shares':shares,'cost':cost,'entry_friction':friction,
                              'stop':stop,'target':tick_round(price+cfg['target_r']*risk,True),
                              'last_close':price,'holding':0,'pending':None}

        for key,p in list(positions.items()):
            found = stocks[key]['by_date'].get(date)
            if not found:
                continue
            i,bar = found
            p['holding'] += 1
            p['last_close'] = bar[4]
            if locked(bar) and not p['pending']:
                if bar[1] <= p['stop']:
                    p['pending'] = 'blocked_stop_next_open'
                elif bar[1] >= p['target']:
                    p['pending'] = 'blocked_target_next_open'
            hit = protective_exit(bar,p['stop'],p['target'])
            if hit:
                close(key,date,*hit)
                continue
            # Locked sell orders stay pending; they are not assumed filled at an unavailable price.
            ma20 = statistics.mean(b[4] for b in stocks[key]['bars'][max(0,i-19):i+1])
            if not p['pending']:
                if bar[4] < ma20:
                    p['pending'] = 'ma20_next_open'
                elif p['holding'] >= cfg['holding_bars']:
                    p['pending'] = 'time20_next_open'

        equity = value(date)
        peak = max(peak,equity)
        dd = (equity/peak-1)*100
        minimum_dd = min(minimum_dd,dd)
        exposure = sum(p['shares']*p['last_close'] for p in positions.values())/equity if equity else 0
        exposures.append(exposure)
        assert cash >= -1e-6 and len(positions) <= cfg['max_positions']
        curve.append({'date':date,'equity':round(equity,2),'cash':round(cash,2),'positions':len(positions),'drawdown_pct':round(dd,6)})

    wins = [t for t in trades if t['pnl']>0]
    losses = [t for t in trades if t['pnl']<0]
    pnl_win,pnl_loss = sum(t['pnl'] for t in wins),-sum(t['pnl'] for t in losses)
    open_trades = []
    for key,p in positions.items():
        sale,cost = exit_cash(p['last_close'],p['shares'],cfg)
        open_trades.append({'market':stocks[key]['market'],'code':stocks[key]['code'],'name':stocks[key]['name'],
                            'signal':p['signal'],'entry_date':p['entry_date'],'entry_price':p['entry_price'],
                            'shares':p['shares'],'last_price':p['last_close'],
                            'mark_date':next(b[0] for b in reversed(stocks[key]['bars']) if b[0]<=dates[-1]),
                            'estimated_net_pnl':round(sale-p['cost'],2),'pending_exit':p['pending']})
    stats = {'group':group,'start':dates[0],'end':dates[-1],'initial_capital':cfg['capital'],
             'final_equity':curve[-1]['equity'],'total_return_pct':round((curve[-1]['equity']/cfg['capital']-1)*100,6),
             'max_drawdown_pct':round(minimum_dd,6),'closed_trades':len(trades),'wins':len(wins),'losses':len(losses),
             'breakeven':len(trades)-len(wins)-len(losses),
             'win_rate_pct':round(len(wins)/len(trades)*100,6) if trades else None,
             'mean_trade_net_return_pct':round(statistics.mean(t['net_return_pct'] for t in trades),6) if trades else None,
             'median_trade_net_return_pct':round(statistics.median(t['net_return_pct'] for t in trades),6) if trades else None,
             'profit_factor':round(pnl_win/pnl_loss,6) if pnl_loss else None,
             'realized_pnl':round(sum(t['pnl'] for t in trades),2),
             'open_positions':len(positions),'open_estimated_net_pnl':round(sum(t['estimated_net_pnl'] for t in open_trades),2),
             'stale_open_positions':sum(t['mark_date']<dates[-1] for t in open_trades),
             'costs_paid':round(fees_total,2),'average_exposure_pct':round(statistics.mean(exposures)*100,2),
             'traded_symbols':len({t['market']+':'+t['code'] for t in trades}|set(positions)),
             'same_bar_ambiguities':ambiguous,'skipped':dict(skips),
             'per_signal':{signal:{'closed_trades':len(ts),'wins':sum(t['pnl']>0 for t in ts),
                                   'win_rate_pct':round(sum(t['pnl']>0 for t in ts)/len(ts)*100,6),
                                   'mean_net_return_pct':round(statistics.mean(t['net_return_pct'] for t in ts),6)}
                           for signal in SIGNALS[group] if (ts:=[t for t in trades if t['signal']==signal])}}
    # The end NAV includes estimated exit costs, without pretending remaining holdings were closed trades.
    assert abs(cfg['capital']+stats['realized_pnl']+stats['open_estimated_net_pnl']-stats['final_equity']) < 0.1
    return {'summary':stats,'trades':trades,'open_positions':open_trades,'equity':curve}

def save_csv(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        if not rows:
            f.write('No closed trades\n')
            return
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    p=argparse.ArgumentParser();p.add_argument('--start',default='2026-06-24');p.add_argument('--end',default='2026-10-21')
    p.add_argument('--history',type=Path,default=ROOT/'history.json')
    p.add_argument('--report-date',type=dt.date.fromisoformat);a=p.parse_args()
    raw=a.history.read_bytes();history=json.loads(raw)
    stocks,dates,previous,candidates,coverage=prepare(history,a.start,a.end)
    reports={group:simulate(stocks,dates,previous,candidates,group) for group in SIGNALS}
    # A predefined friction stress scenario; parameters are never selected by the backtest results.
    stressed=simulate(stocks,dates,previous,candidates,'all',{'slippage':0.002})
    result={'version':'6.1-market-backtest-1','generated_at':str(a.report_date or dt.datetime.now(scanner.TZ).date()),
            'history_sha256':hashlib.sha256(raw).hexdigest(),
            'scanner_sha256':hashlib.sha256((ROOT/'scanner.py').read_bytes()).hexdigest(),
            'engine_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'data_quality':history.get('_backtest_provenance',{}),
            'config':DEFAULTS,'coverage':coverage,'primary':'all','reports':reports,'slippage_stress_summary':stressed['summary'],
            'limitations':[
                '研究回測，非實盤；未經獨立第三方重現。四個月區間不足以判定長期有效性，亦未保留獨立樣本外期間。',
                '原V6.1只有進場候選。本次出場、資金配置及成本假設新增且事前固定，績效僅適用於此完整規則。',
                '使用未還原權息OHLC，未納現金股息、配股、除權息、減資及分割調整，可能影響訊號和報酬。',
                '以歷史快照當時出現的股票重播，不只挑今天仍有候選的股票；但無完整下市、改名及公司行動主檔，不能宣稱完全排除存活者偏誤。',
                '每日收盤重算訊號只讀當時已知資料，次交易日開盤進場；無當日收盤成交或使用事後完整圖形。',
                '一價K線不假設可成交；已觸發但受阻的停損／停利保留待出場狀態，在下一可成交開盤處理。缺價不成交、持倉以最後可得收盤估值。無逐筆委託簿，無法精確驗證漲跌停排隊與市場衝擊。',
                '同一日同時碰停損與停利時先算停損；開盤跳空穿價按開盤參考價，滑價另外作為成本扣除。',
                '1000股整張、單筆不超過前一交易日成交量1%、每檔最多本金當時淨值10%、最多10檔；資金或風險不足一張則跳過。',
                '進場風險預算0.5%，初始停損為訊號當日及前四日最低價再下方0.5%並依跳動單位下修，進場距停損超過8%則跳過。',
                '固定2R停利、跌破20日均線或持有滿20根日K後次交易日開盤出場；未開放融資、放空及再投資借款。',
                '同日候選按掃描條件評分、成交額及代碼排序，依序檢查持倉、資金及風險門檻。區間末日訊號沒有區間內的次日開盤，因此不形成新交易。',
                '勝率只計自然平倉交易，期末未平倉不算輸贏；總報酬含未平倉損益並預扣估計賣出成本，因此兩項不能直接互推。',
                '費率為模擬假設：買賣各0.1425%、每筆最低20元、賣出稅0.3%、買賣各0.1%滑價；實際券商費率、最低費用及成交可能不同。',
                '日終資金與淨值模擬未逐日追蹤T+2交割限制；保守交易成本估值仍不等於可實現損益。']}
    scanner.atomic_json(ROOT/'backtest_results.json',result)
    for group,report in reports.items():
        save_csv(ROOT/f'backtest_trades_{group}.csv',report['trades'])
        save_csv(ROOT/f'backtest_equity_{group}.csv',report['equity'])
    print(json.dumps({'coverage':coverage,'reports':{k:v['summary'] for k,v in reports.items()},'stress':stressed['summary']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
