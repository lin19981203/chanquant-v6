#!/usr/bin/env python3
"""V6.2 daily Chan point reference replay; no fixed R target or time/MA exit."""
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import statistics
import scanner
import chan_points as cp
from backtest_market import fee, tick_round, locked, exit_cash, protective_exit, save_csv

ROOT=Path(__file__).resolve().parent
DEFAULTS=dict(capital=50_000_000,max_positions=10,allocation=.10,risk_fraction=.005,
    max_stop_fraction=.08,commission=.001425,minimum_fee=20,sell_tax=.003,slippage=.001,
    lot_size=1000,volume_participation=.01)
SIGNALS={'all':{'B1','B2','B3'},'b1':{'B1'},'b2':{'B2'},'b3':{'B3'}}

def prepare(history,start,end):
    stocks={};candidates=collections.defaultdict(list);dates=set();screened=set();eligible=set()
    daily_coverage=collections.Counter();signal_symbols=set()
    for market,state in history['markets'].items():
        for code,item in state['stocks'].items():
            if not scanner.common_stock(code,item['name']):continue
            bars=[b for b in item['bars'] if b[0]<=end]
            if not bars:continue
            key=market+':'+code
            stocks[key]={'code':code,'name':item['name'],'market':market,'bars':bars,
                         'by_date':{b[0]:(i,b) for i,b in enumerate(bars)}}
            dates.update(b[0] for b in bars)
    dates=sorted(dates);evaluation=[d for d in dates if start<=d<=end]
    if not evaluation:raise ValueError('No quotes in evaluation interval')
    before=[d for d in dates if d<evaluation[0]]
    signal_dates=set(evaluation+before[-1:])
    for count,(key,item) in enumerate(stocks.items(),1):
        detector=cp.Detector()
        for i,b in enumerate(item['bars']):
            events=detector.push(b)
            if b[0] not in signal_dates:continue
            screened.add(key)
            if i>=59:eligible.add(key);daily_coverage[b[0]]+=1
            for event in events:
                liquid=i>=59 and b[4]>=10 and b[5]>=500000 and b[6]>=20000000
                stop=event['reference_stop']
                # Signals cannot be entered after their structural reference was already breached.
                alive=(not event['kind'].startswith('B') or all(x[3]>stop for x in item['bars'][event['point_index']+1:i+1]))
                conflict=any(e['kind'].startswith('S') for e in events)
                row={'key':key,'code':item['code'],'name':item['name'],'market':item['market'],
                     'date':b[0],'signal':event['kind'],'score':70+5*int(event['kind'][1]),
                     'amount':b[6],'volume':b[5],'close':b[4],'initial_stop':stop,
                     'entry_allowed':liquid and alive and not conflict,'point_date':event['point_date']}
                candidates[b[0]].append(row);signal_symbols.add(key)
        if count%300==0:print(f'Chan replay signals {count}/{len(stocks)}',flush=True)
    for rows in candidates.values():rows.sort(key=lambda s:(-s['score'],-s['amount'],s['key']))
    prior={d:dates[dates.index(d)-1] if dates.index(d)>0 else None for d in evaluation}
    coverage={'screened_symbols':len(screened),'symbols_with_60_bars':len(eligible),
        'trading_sessions':len(evaluation),'daily_warmup_coverage':dict(daily_coverage),
        'signal_symbols':len(signal_symbols),'signal_events':sum(len(x) for x in candidates.values()),
        'eligible_buy_events':sum(s['entry_allowed'] and s['signal'].startswith('B') for rows in candidates.values() for s in rows),
        'event_counts':dict(collections.Counter(s['signal'] for rows in candidates.values() for s in rows)),
        'market_symbols':{m:sum(k.startswith(m+':') for k in screened) for m in history['markets']}}
    return stocks,evaluation,prior,dict(candidates),coverage

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
                       'signal':p['signal'],'signal_date':p['signal_date'],'point_date':p.get('entry_point_date'),'entry_date':p['entry_date'],
                       'exit_date':date,'entry_price':p['entry_price'],'exit_price':price,
                       'shares':p['shares'],'entry_cost':round(p['cost'],2),'pnl':round(pnl,2),
                       'net_return_pct':round(100*pnl/p['cost'],6),'reason':reason,
                       'holding_bars':p['holding'],'costs':round(p['entry_friction']+cost,2),
                       'same_bar_stop_target':amb})

    for date in dates:
        # A close-derived exit order can execute only at a subsequent session's open.
        sold_today = set()
        for key,p in list(positions.items()):
            found = stocks[key]['by_date'].get(date)
            if found and p['pending'] and not locked(found[1]):
                close(key,date,found[1][1],p['pending']); sold_today.add(key)

        opening_equity = value(date,True)
        for s in candidates.get(previous[date],[]):
            if s['signal'] not in SIGNALS[group]:
                continue
            key = s['key']
            if not s.get('entry_allowed',False):
                continue
            if key in sold_today:
                skips['same_day_reentry'] += 1
                continue
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
            # Enforce actual rounded fees and the structural-stop risk budget, including minima.
            while shares > 0 and (cost > allocation or cost-exit_cash(stop,shares,cfg)[0] > opening_equity*cfg['risk_fraction']):
                shares -= cfg['lot_size']
                gross = shares*price
                friction = fee(gross,cfg)+gross*cfg['slippage'] if shares else 0
                cost = gross+friction
            if shares <= 0:
                skips['rounded_cost_below_one_lot'] += 1
                continue
            if cost > cash+1e-7:
                skips['cash_limit'] += 1
                continue
            cash -= cost
            fees_total += friction
            positions[key] = {'signal':s['signal'],'signal_date':s['date'],'entry_date':date,
                              'entry_price':price,'shares':shares,'cost':cost,'entry_friction':friction,
                              'stop':stop,'entry_point_date':s.get('point_date'),'entry_confirmed_date':s['date'],
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

            hit = protective_exit(bar,p['stop'],math.inf)
            if hit:
                close(key,date,*hit)
                continue
            # Close-confirmed sell points and stop raises become executable on later bars.
            todays = [s for s in candidates.get(date,[]) if s['key']==key]
            sells = [s for s in todays if s['signal'].startswith('S')]
            if not p['pending'] and sells:
                p['pending'] = max(sells,key=lambda s:s['signal'])['signal']+'_next_open'
            raises = [s['initial_stop'] for s in todays if s['signal'] in {'B2','B3'}]
            if raises:
                p['stop'] = max(p['stop'],max(raises))
                # The structural stop may already be broken by the confirmation close.
                if bar[4] <= p['stop'] and not p['pending']:
                    p['pending'] = 'structure_broken_next_open'

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
                            'estimated_net_pnl':round(sale-p['cost'],2),'pending_exit':p['pending'],'structural_stop':p['stop']})
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

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--history',type=Path,default=ROOT/'history.json')
    p.add_argument('--start',default='2025-10-22');p.add_argument('--end',default='2026-10-21')
    p.add_argument('--capital',type=float,default=50_000_000)
    p.add_argument('--report-date',type=dt.date.fromisoformat)
    a=p.parse_args();raw=a.history.read_bytes();history=json.loads(raw)
    quality=history.get('_backtest_provenance',{})
    if (not quality.get('expected_queries') or quality.get('successful_queries')!=quality['expected_queries'] or
            quality.get('unresolved_queries')):
        raise SystemExit('Missing or unresolved daily-query provenance; do not label an incomplete download as a complete year.')
    if quality.get('requested_start','9999')>a.start or quality.get('requested_end','0000')<a.end:
        raise SystemExit('Requested replay dates exceed the verified download interval; rebuild history_year.py first.')
    cfg=DEFAULTS|{'capital':a.capital}
    if not math.isfinite(a.capital) or a.capital<=0:raise SystemExit('Capital must be finite and positive')
    stocks,dates,previous,candidates,coverage=prepare(history,a.start,a.end)
    reports={g:simulate(stocks,dates,previous,candidates,g,cfg) for g in SIGNALS}
    stress=simulate(stocks,dates,previous,candidates,'all',cfg|{'slippage':.002})
    result={'version':'6.2-chan-reference','generated_at':str(a.report_date or dt.datetime.now(scanner.TZ).date()),'primary':'all',
        'history_sha256':hashlib.sha256(raw).hexdigest(),'engine_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'strategy_sha256':hashlib.sha256((ROOT/'chan_points.py').read_bytes()).hexdigest(),
        'scanner_sha256':hashlib.sha256((ROOT/'scanner.py').read_bytes()).hexdigest(),
        'helpers_sha256':hashlib.sha256((ROOT/'backtest_market.py').read_bytes()).hexdigest(),
        'data_quality':quality,'config':cfg,'coverage':coverage,'reports':reports,
        'slippage_stress_summary':stress['summary'],'limitations':cp.RULES+[
            '每組獨立使用五千萬元模擬；大本金仍受成交量1%限制，不會直接放大舊版損益。',
            '未還原權息OHLC，未計股息與完整下市主檔；仍可能有公司行動及存活者偏誤。',
            '買賣各0.1425%手續費、最低20元；賣出稅0.3%；每邊滑價0.1%。T+2交割限制及逐筆市場衝擊未完整模擬。',
            '新確認賣點次日開盤出場；缺價或一價K不假設成交。結構停損跳空按開盤，受阻保留待出場。',
            '單筆未平倉不計勝率，帳戶總報酬包含未平倉估值並預扣賣出成本；回撤為日終值。',
            '價格低於成本也可能觸發賣點出場；買賣點不是保證獲利，尚未經獨立樣本外驗證。',
            '一類MACD面積80%、分型間隔4根合併K、中樞回抽等待120根日K是固定工程參數，沒有依本次績效調參。']}
    scanner.atomic_json(ROOT/'backtest_results.json',result)
    for g,r in reports.items():
        save_csv(ROOT/f'backtest_trades_{g}.csv',r['trades'])
        save_csv(ROOT/f'backtest_equity_{g}.csv',r['equity'])
    print(json.dumps({'coverage':coverage,'summary':{k:v['summary'] for k,v in reports.items()}},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
