"""Build the verified release and public website after the complete download."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parent
PUBLIC=ROOT/'public'
SOURCE=['index.html','app.css','app.js','scanner-ui.js','backtest-ui.js','scanner.py','chan_points.py',
 'backtest_chan.py','backtest_market.py','export_charts.py','history_year.py','live_gateway.py',
 'requirements-live.txt','test_scanner.py','test_backtest_market.py','test_chan_points.py',
 'test_year_data.py','test_live_gateway.py','test_ui.cjs','README.md','RULES_V62.md',
 'BACKTEST_REPORT.md','.github/workflows/v62.yml']
SOURCE += [str(p.relative_to(ROOT)) for p in sorted((ROOT/'release-v62').glob('payload-*.b64'))] + ['release-v62/install.txt','release-v62/verified.json']
LABELS={'all':'一／二／三類買點合併','b1':'一類買點參考','b2':'二類買點參考','b3':'三類買點參考'}

def run(*args):
    subprocess.run([sys.executable,*args],cwd=ROOT,check=True)

def write_report(d):
    groups=d['reports'];s=groups['all']['summary']
    table='| 進場組別 | 已平倉勝率 | 帳戶累積淨報酬 | 日終最大回撤 | 平倉／未平倉 | 平均曝險 |\n|---|---:|---:|---:|---:|---:|\n'
    def pct(n):return '—' if n is None else f'{n:.2f}%'
    for k,r in groups.items():
        x=r['summary'];table+=f"| {LABELS[k]} | {pct(x['win_rate_pct'])} | {pct(x['total_return_pct'])} | {pct(x['max_drawdown_pct'])} | {x['closed_trades']}／{x['open_positions']} | {pct(x['average_exposure_pct'])} |\n"
    text=f'''# ChanQuant V6.2 年度回測｜五千萬元・結構買賣點參考

報告日期：2026-10-22。期間：{s['start']}～{s['end']}，{d['coverage']['trading_sessions']}個交易日；歷史日K另有暖機區間{d['data_quality']['warmup_start']}起。官方日別查詢（含休市）{d['data_quality']['successful_queries']}／{d['data_quality']['expected_queries']}完成，未解決查詢0筆。

這是固定工程規則的日K研究模擬，非實盤、非完整正統纏論，沒有依結果挑選最佳參數。訊號標在確認日，交易在下一開盤；不是按事後歷史端點價格成交。

{table}

每組獨立使用NT$50,000,000，不能將組別損益相加。合併組期末淨值NT${s['final_equity']:,.2f}；已平倉{s['closed_trades']}筆，{s['wins']}勝、{s['losses']}負、{s['breakeven']}持平。未平倉{s['open_positions']}檔，不列入勝率分母；帳戶淨值包含它們的估值並預扣估計賣出成本。

合併組已平倉每筆平均淨報酬{pct(s['mean_trade_net_return_pct'])}，已付費用及滑價NT${s['costs_paid']:,.2f}；實際交易{s['traded_symbols']}檔。平均持倉曝險{pct(s['average_exposure_pct'])}：大本金受前日成交股數1%限制，可能有大量現金閒置，這不是50倍投入的策略。

提高雙邊滑價至每邊0.2%的事前壓力情境，合併組淨報酬{pct(d['slippage_stress_summary']['total_return_pct'])}。

## 市場與訊號覆蓋

重播{d['coverage']['screened_symbols']}檔歷史普通股；其中{d['coverage']['symbols_with_60_bars']}檔曾具60根日K。有訊號股票{d['coverage']['signal_symbols']}檔；符合買入流動性且結構未失效的候選事件{d['coverage']['eligible_buy_events']}筆。

各類新確認事件數：`{json.dumps(d['coverage']['event_counts'],ensure_ascii=False)}`。不是每個候選都成交；不足一張、資金、風險與持倉上限會排除候選。每個類別的少量交易不足以評估穩定勝率。

## 本次固定規則

'''
    text+='\n\n'.join('- '+x for x in d['limitations'])
    text+='''

## 與上一版的差異

本金、進場、出場與測試區間都改變，不能直接把上一版23%勝率／−10.05%報酬與本報告當作同條件優化比較。此次沒有市場指數基準或獨立樣本外期間；一年績效不能證明長期有效。

## 重現

解壓縮稽核ZIP後，以Python3.12在同一目錄執行，不需第三方套件：

```sh
python -m unittest -v test_scanner.py test_backtest_market.py test_chan_points.py test_live_gateway.py test_year_data.py
python backtest_chan.py --history history.json --start 2025-10-22 --end 2026-10-21 --capital 50000000
```

`SHA256SUMS.txt`記錄輸入、引擎、規則與輸出指紋；JSON包含逐筆交易、未平倉、淨值、成本與排除原因。未平倉估值可能因缺價過時，請核對JSON的`stale_open_positions`及每檔`mark_date`。

## 即時與發布狀態

本回測使用官方盤後日K。即時行情尚未啟用；串流後端只完成規格與離線驗證，沒有取得行情金鑰、沒有驗證供應商實際連線，盤中未完成分鐘K不參與本回測。

本報告由GitHub Actions執行年度資料重建與回測後產生。正式網站發布結果請以GitHub Pages部署紀錄為準；即時行情尚未啟用。

官方資料：
- https://www.twse.com.tw/zh/trading/historical/mi-index.html
- https://www.tpex.org.tw/zh-tw/mainboard/trading/info/pricing.html
- https://developer.fugle.tw/docs/data/websocket-api/getting-started/
- https://developer.fugle.tw/docs/data/http-api/historical/candles/
'''
    trades=groups['all']['trades']
    largest=sum(sorted((t['pnl'] for t in trades),reverse=True)[:3])
    text+=f"\n\n## 獲利集中\n\n已平倉前三大獲利合計NT${largest:,.2f}；全部已平倉淨損益NT${s['realized_pnl']:,.2f}。未平倉估計淨損益NT${s['open_estimated_net_pnl']:,.2f}亦影響帳戶報酬。獲利集中少數波段，低勝率與企業行動風險仍須評估；一年結果不能證明長期有效。\n"
    (ROOT/'BACKTEST_REPORT.md').write_text(text)

def zip_files(target,entries,prefix):
    pending=target.with_suffix('.pending')
    manifests=[]
    with zipfile.ZipFile(pending,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,path in entries:
            data=path.read_bytes();z.writestr(prefix+'/'+name,data)
            manifests.append(hashlib.sha256(data).hexdigest()+'  '+name)
        z.writestr(prefix+'/SHA256SUMS.txt','\n'.join(manifests)+'\n')
    pending.replace(target)
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
    print('PACKAGED',target.name,target.stat().st_size,flush=True)


def main():
    h=json.loads((ROOT/'history_year.json').read_text())
    q=h.get('_backtest_provenance',{})
    assert q.get('expected_queries') and q['successful_queries']==q['expected_queries'] and not q['unresolved_queries'],'Incomplete annual download'
    shutil.copyfile(ROOT/'history_year.json',ROOT/'history.json')
    run('scanner.py','--offline','--as-of','2026-10-21')
    run('backtest_chan.py','--history','history.json','--start','2025-10-22','--end','2026-10-21','--capital','50000000','--report-date','2026-10-22')
    d=json.loads((ROOT/'backtest_results.json').read_text());write_report(d)
    PUBLIC.mkdir(exist_ok=True)
    for file in ['index.html','app.css','app.js','scanner-ui.js','backtest-ui.js','scan_results.json','backtest_results.json']:
        shutil.copyfile(ROOT/file,PUBLIC/file)
    for file in ROOT.glob('backtest_trades_*.csv'):
        # Avoid retaining the unrelated old Chan/trend strategy files.
        if file.stem.rsplit('_',1)[-1] in LABELS:shutil.copyfile(file,PUBLIC/file.name)
    run('export_charts.py','--history','history.json','--destination','public')
    (PUBLIC/'.nojekyll').touch()
    audit=ROOT/'backtest_audit_v62_20261021.zip'
    audit_names=['scanner.py','chan_points.py','backtest_chan.py','backtest_market.py','export_charts.py','live_gateway.py',
      'test_scanner.py','test_backtest_market.py','test_chan_points.py','test_live_gateway.py','test_year_data.py',
      'history.json','backtest_results.json','BACKTEST_REPORT.md','RULES_V62.md']
    audit_names += [f'backtest_{kind}_{g}.csv' for kind in ['trades','equity'] for g in LABELS]
    zip_files(audit,[(n,ROOT/n) for n in audit_names],'ChanQuant_v62_audit_20261021')
    shutil.copyfile(audit,PUBLIC/audit.name)
    upgrade=ROOT.parent/'chanquant-v62-upgrade.zip'
    entries=[(n,ROOT/n) for n in SOURCE]
    entries += [(n,ROOT/n) for n in ['history.json','scan_results.json','backtest_results.json']]
    entries += [(f'backtest_trades_{g}.csv',ROOT/f'backtest_trades_{g}.csv') for g in LABELS]
    entries += [('public/'+str(p.relative_to(PUBLIC)),p) for p in sorted(PUBLIC.rglob('*')) if p.is_file()]
    zip_files(upgrade,entries,'chanquant-v62')
    print('FINALIZED',flush=True)

if __name__=='__main__':main()
