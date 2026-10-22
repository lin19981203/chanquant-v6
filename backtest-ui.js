(() => {
  const labels={all:'一／二／三類買點合併',b1:'一類買點參考',b2:'二類買點參考',b3:'三類買點參考'};
  const e=id=>document.getElementById(id);
  const f=n=>n==null?'—':Number(n).toLocaleString('zh-TW',{maximumFractionDigits:2});
  const pct=n=>n==null?'—':f(n)+'%';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let data=null, group='all', shown=20;
  function chart(){
    if(data&&e('marketEquity'))lineChart('marketEquity',data.reports[group].equity.map(x=>x.equity));
  }
  function render(){
    const report=data.reports[group],s=report.summary;
    e('backtestPanel').innerHTML=`<div class="card warning"><b>V6.2 · 五千萬元 · 研究回測</b><p>期間 ${esc(s.start)} ～ ${esc(s.end)}；勝率只計已平倉交易，總報酬含期末未平倉估值並預扣賣出成本。日K簡化買賣點參考；一年結果不足以證明長期有效性。</p></div>
    <div class="card"><label>查看策略組別<select id="backtestGroup">${Object.entries(labels).map(([k,v])=>'<option value="'+k+'"'+(k===group?' selected':'')+'>'+v+'</option>').join('')}</select></label>
    <div class="grid"><div class="metric"><small>已平倉勝率</small><strong>${pct(s.win_rate_pct)}</strong></div><div class="metric"><small>帳戶累積淨報酬</small><strong class="${s.total_return_pct>=0?'up':'down'}">${s.total_return_pct>=0?'+':''}${pct(s.total_return_pct)}</strong></div><div class="metric"><small>日終最大回撤</small><strong>${pct(s.max_drawdown_pct)}</strong></div><div class="metric"><small>已平倉 / 未平倉</small><strong>${s.closed_trades} / ${s.open_positions}</strong></div></div>
    <p class="muted">本金 NT$${f(s.initial_capital)} → 期末淨值 NT$${f(s.final_equity)}<br>獲利 ${s.wins} 筆／虧損 ${s.losses} 筆／持平 ${s.breakeven} 筆；每筆已平倉平均淨報酬 ${pct(s.mean_trade_net_return_pct)}。總報酬並非年化或每月報酬。</p>
    <div class="stock-metrics"><div><small>實際交易股票</small>${s.traded_symbols}檔</div><div><small>平均持倉曝險</small>${pct(s.average_exposure_pct)}</div><div><small>已付成本</small>NT$${f(s.costs_paid)}</div></div></div>
    <div class="card"><b>資金淨值曲線</b><div id="marketEquity" class="chart"></div><small>每天收盤估值；期末未平倉未被假裝成已完成交易。日內回撤可能大於此圖。</small></div>
    <div class="card scroll"><b>相同成本與出場規則下的三組結果</b><table><thead><tr><th>組別</th><th>勝率</th><th>帳戶淨報酬</th><th>平倉筆數</th></tr></thead><tbody>${Object.entries(data.reports).map(([k,r])=>'<tr><td>'+labels[k]+'</td><td>'+pct(r.summary.win_rate_pct)+'</td><td>'+pct(r.summary.total_return_pct)+'</td><td>'+r.summary.closed_trades+'</td></tr>').join('')}</tbody></table><p class="muted">每組獨立使用五千萬元模擬，並非合併帳戶或用回測結果挑出的最佳參數。</p></div>
    <div class="card"><b>回測範圍</b><p>重播 ${data.coverage.screened_symbols} 檔歷史出現的普通股，其中 ${data.coverage.symbols_with_60_bars} 檔曾具備60根日K。回測共 ${data.coverage.trading_sessions} 個交易日；有訊號股票 ${data.coverage.signal_symbols} 檔。</p><p class="muted">掃描整個市場不代表每檔都買入；資金、風險、整張交易與持倉上限會限制成交。每日股票名單由當時快照決定，沒有只回測今日候選股。</p><p>滑價加倍至每邊0.2%時，全部候選帳戶淨報酬為 ${pct(data.slippage_stress_summary.total_return_pct)}。</p></div>
    <div class="card scroll"><b>已平倉交易明細</b><table><thead><tr><th>股票</th><th>進場</th><th>出場</th><th>淨損益</th><th>淨報酬</th><th>原因</th></tr></thead><tbody>${report.trades.slice(0,shown).map(t=>'<tr><td>'+esc(t.code)+' '+esc(t.name)+'</td><td>'+esc(t.entry_date)+'</td><td>'+esc(t.exit_date)+'</td><td>'+f(t.pnl)+'</td><td>'+pct(t.net_return_pct)+'</td><td>'+esc(t.reason)+'</td></tr>').join('')}</tbody></table>${report.trades.length>shown?'<button class="action" id="moreBacktest">顯示全部交易</button>':''}<p><a href="backtest_trades_${group}.csv" download>下載此組交易 CSV</a> · <a href="backtest_audit_v62_20261021.zip" download>下載資料與重現程式 ZIP</a></p></div>
    <details class="card"><summary>期末未平倉（${s.open_positions}檔）</summary>${report.open_positions.map(p=>'<p>'+esc(p.code)+' '+esc(p.name)+'：'+f(p.shares)+'股，估計淨損益 NT$'+f(p.estimated_net_pnl)+'（估值日 '+esc(p.mark_date)+'）</p>').join('')||'<p>無未平倉部位。</p>'}</details>
    <details class="card"><summary>完整交易規則、成本與限制</summary>${data.limitations.map(x=>'<p>'+esc(x)+'</p>').join('')}<p>本次測試完成日：${esc(data.generated_at)}。資料快照指紋與掃描器指紋收錄於下載檔。</p></details>`;
    e('backtestGroup').addEventListener('change',event=>{group=event.target.value;shown=20;render();});
    e('moreBacktest')?.addEventListener('click',()=>{shown=report.trades.length;render();});
    chart();
  }
  document.querySelector('nav button[data-tab="backtest"]').addEventListener('click',chart);
  fetch('backtest_results.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}).then(r=>{if(r.version!=='6.2-chan-reference'||r.config.capital!==50000000)throw new Error('舊版回測不可套用新版參數');data=r;render();}).catch(()=>{e('backtestPanel').innerHTML='<div class="card warning">新版回測尚未產生或無法讀取。五千萬元與結構買賣點規則需重新執行，不沿用舊版績效。</div>';});
})();
