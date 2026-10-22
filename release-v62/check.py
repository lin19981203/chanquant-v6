import json,pathlib
d=json.loads(pathlib.Path('backtest_results.json').read_text())
assert d['version']=='6.2-chan-reference'
q=d['data_quality']
assert q['expected_queries']==q['successful_queries']==682 and not q['unresolved_queries']
for k,v in {'trading_sessions':242,'screened_symbols':1992,'symbols_with_60_bars':1980,'signal_symbols':1945,'eligible_buy_events':2610}.items():assert d['coverage'][k]==v,(k,d['coverage'][k])
keys=['closed_trades','wins','losses','open_positions','total_return_pct','max_drawdown_pct']
rows={'all':[172,40,132,9,35.706485,-13.73806],'b1':[138,42,96,7,22.311968,-10.545142],'b2':[88,20,68,2,13.123442,-4.995273],'b3':[172,38,134,9,26.673566,-15.144491]}
for g,values in rows.items():
    for k,v in zip(keys,values):assert abs(d['reports'][g]['summary'][k]-v)<0.01,(g,k)
pathlib.Path('.v62-installed').write_text('6.2-chan-reference\n')
print('All annual replay checks passed')
