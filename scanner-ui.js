/* Published EOD results only. No API key, no orders, no invented fallback data. */
(() => {
  let report = null, limit = 30, chartRequest = 0, chartController = null, scanController = null;
  const el = id => document.getElementById(id);
  const money = n => Number(n).toLocaleString('zh-TW', {maximumFractionDigits: 2});
  const escape = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const marketName = m => m === 'TWSE' ? '上市' : '上櫃';
  const candidate = s => s.score > 0;
  const stamp = s => new Date(s).toLocaleString('zh-TW', {timeZone:'Asia/Taipei', hour12:false});
  function render() {
    if (!report) return;
    const query = el('stockQuery').value.trim().toLowerCase();
    const market = el('marketFilter').value, signal = el('signalFilter').value;
    const rows = report.stocks.filter(s => (!market || s.market === market) &&
      (!query || (s.code+s.name).toLowerCase().includes(query)) &&
      (query && signal === 'candidates' || signal === 'all' || (signal === 'candidates' ? candidate(s) : (signal==='buy' ? s.signal.includes('買點') : signal==='sell' ? s.signal.includes('賣點') : s.signal===signal))));
    el('showMore').hidden = rows.length <= limit;
    if (!rows.length) {
      el('scanList').innerHTML = '<div class="card empty"><b>目前沒有符合的股票</b><p class="muted">可調整市場、訊號或搜尋條件。零筆結果也是有效的掃描結果。</p></div>';
      return;
    }
    el('scanList').innerHTML = '<p class="muted">符合 '+rows.length+' 檔，依條件評分與成交額排序</p>' + rows.slice(0,limit).map(s => {
      const change = s.change_pct == null ? '—' : (s.change_pct >= 0 ? '+' : '')+money(s.change_pct)+'%';
      const color = s.change_pct >= 0 ? 'up' : 'down';
      return `<article class="card"><div class="result-top"><div><h3>${escape(s.code)} ${escape(s.name)}</h3><span class="badge">${marketName(s.market)} · ${escape(s.signal)}</span></div><div class="price">${money(s.close)}<div class="${color}" style="font-size:14px">${change}</div></div></div>
      <div class="stock-metrics"><div><small>成交額</small>${money(s.amount/10000)}萬</div><div><small>成交量</small>${money(s.volume/1000)}張</div><div><small>量比 / 前20日</small>${s.volume_ratio == null ? '—' : money(s.volume_ratio)+'倍'}</div><div><small>MA20 / MA60</small>${s.ma20 == null ? '—' : money(s.ma20)+' / '+money(s.ma60)}</div><div><small>有效日K</small>${s.bars}根</div><div><small>條件評分</small>${s.score || '—'}</div></div>
      ${s.center ? '<p class="muted">中樞區間 '+money(s.center.lower)+' ～ '+money(s.center.upper)+'<br>'+escape(s.center.start)+' ～ '+escape(s.center.end)+'</p>' : ''}
      ${s.point ? '<p class="muted">端點 '+escape(s.point.point_date)+' → 確認 '+escape(s.point.confirmed_date)+(s.point.reference_stop ? '；結構停損參考 '+money(s.point.reference_stop) : '')+'</p>' : ''}
      ${s.reasons ? '<ul class="reasons">'+s.reasons.map(r=>'<li>'+escape(r)+'</li>').join('')+'</ul>' : ''}
      <div class="result-top"><small>行情日 ${escape(s.date)}</small>${s.chart_path ? '<button class="action" data-stock="'+escape(s.market+':'+s.code)+'">查看一年K線</button>' : '<small>未列入候選</small>'}</div></article>`;
    }).join('');
  }
  async function showStock(key) {
    const stock = report.stocks.find(s => s.market+':'+s.code === key);
    if (!stock || !/^(TWSE|TPEX):[1-9][0-9]{3}$/.test(key)) return;
    const request = ++chartRequest;
    chartController?.abort();
    const controller = new AbortController();
    chartController = controller;
    const timeout = setTimeout(()=>controller.abort(),20000);
    el('chartTitle').textContent = stock.code+' '+stock.name;
    el('chartHint').textContent = '正在讀取近一年日K…';
    marketCandles=null;marketPoints=[];
    el('candlesChart').textContent='正在讀取K線…';
    el('chartCaption').textContent='';
    document.querySelector('nav button[data-tab="chart"]').click();
    window.scrollTo({top:0,behavior:'smooth'});
    try {
      const response=await fetch('charts/'+stock.market+'/'+stock.code+'.json',{cache:'no-store',signal:controller.signal});
      if(!response.ok)throw new Error('HTTP '+response.status);
      const data=await response.json();
      if(request!==chartRequest)return;
      if(!Array.isArray(data.bars)||!data.bars.length||data.bars.some(b=>!Array.isArray(b)||!/^\d{4}-\d{2}-\d{2}$/.test(b[0])||!b.slice(1,6).every(Number.isFinite)||!(0<b[3]&&b[3]<=Math.min(b[1],b[4])&&Math.max(b[1],b[4])<=b[2])))throw new Error('沒有有效K線');
      marketCandles=data.bars.map(b=>({datetime:b[0],open:b[1],high:b[2],low:b[3],close:b[4],volume:b[5]}));
      marketPoints=Array.isArray(data.points)?data.points:[];
      el('chartHint').textContent='官方盤後行情，未還原權息。期間 '+data.available_start+' ～ '+data.end+'；B＝買點參考、S＝賣點參考，標記在確認日。週／月K僅聚合顯示，末根可能未完成。';
      drawCandles();
    } catch(error) {
      if(request!==chartRequest)return;
      el('chartHint').textContent=error.name==='AbortError'?'K線讀取逾時，請回掃描頁重新選取股票。':'K線無法讀取：'+error.message;
      el('candlesChart').textContent='暫無可用行情';
    } finally {clearTimeout(timeout);if(chartController===controller)chartController=null;}
  }
  async function load() {
    // Visibility, timer and manual refresh share one in-flight download on mobile.
    if(scanController)return;
    const controller=new AbortController();scanController=controller;
    const timeout=setTimeout(()=>controller.abort(),20000);
    const button = el('refreshScan'); button.disabled = true; button.textContent = '讀取中…';
    try {
      const response = await fetch('scan_results.json', {cache:'no-store',signal:controller.signal});
      if (!response.ok) throw new Error('HTTP '+response.status);
      const data = await response.json();
      if (data.version!=='6.2') throw new Error('掃描資料版本與畫面不一致，請稍後更新');
      if (!Array.isArray(data.stocks) || !Array.isArray(data.markets) || !Array.isArray(data.errors) || !Number.isFinite(Date.parse(data.generated_at)) ||
          data.stocks.some(s=>!s||!['TWSE','TPEX'].includes(s.market)||!/^\d{4}$/.test(s.code)||typeof s.name!=='string'||typeof s.signal!=='string'||!Number.isFinite(s.close)) ||
          data.markets.some(m=>!m||!['TWSE','TPEX'].includes(m.market)||!Number.isFinite(m.ready)||!Number.isFinite(m.count))) throw new Error('資料格式不符');
      report = data;
      el('scanState').textContent = data.status === 'ok' ? '盤後掃描完成' : '部分資料未完成，請核對各市場日期';
      el('scanTimestamp').textContent = '結果產生：'+stamp(data.generated_at)+'（台灣時間）';
      el('universeCount').textContent = money(data.stocks.length)+'檔';
      el('readyCount').textContent = money(data.markets.reduce((n,m)=>n+m.ready,0))+'檔';
      el('chanCount').textContent = money(data.stocks.filter(s=>s.signal.includes('買點') && candidate(s)).length)+'檔';
      el('trendCount').textContent = money(data.stocks.filter(s=>s.signal.includes('賣點') && candidate(s)).length)+'檔';
      el('marketHealth').innerHTML = data.markets.map(m => '<div class="health"><span>'+marketName(m.market)+' · '+m.count+'檔</span><span>'+escape(m.date || '無有效資料')+(m.status==='ok'?'':' · 待更新')+'</span></div>').join('');
      const age = (Date.now() - Date.parse(data.generated_at))/86400000;
      const sourceDates = data.markets.filter(m=>m.date).map(m=>m.date).sort();
      const sourceOld = sourceDates.length < 2 || Date.now()-Date.parse(sourceDates[0]+'T17:00:00+08:00')>4*86400000;
      el('scanAlert').textContent = (age > 3 || sourceOld ? '資料已較久未更新，請到自動更新工作確認狀態。 ' : '') +
        (data.errors.length ? '本次有 '+data.errors.length+' 筆抓取失敗；資料不足的股票不產生候選。 ' : '') +
        (sourceDates.length===2 && sourceDates[0]!==sourceDates[1] ? '上市與上櫃行情日期不同，請分別核對。 ' : '') +
        '休市顯示最後可得交易日；開市前不會有當日盤後資料。';
      el('activeRules').textContent=(data.rules?.details||[]).join('\n\n');
      render();
    } catch (error) {
      el('scanState').textContent = report ? '無法取得更新，仍顯示先前載入結果' : '掃描結果暫時無法讀取';
      el('scanAlert').textContent = (error.name==='AbortError'?'讀取超過20秒，請確認網路後重試。':'請檢查網路或查看 GitHub Actions 更新工作。'+error.message)+(report?' 目前保留先前結果，請核對原行情日期。':'');
      if (!report) el('scanList').innerHTML = '<div class="card empty error">尚無可用的市場掃描資料。系統不會用內建台積電歷史資料冒充最新市場結果。</div>';
    } finally {clearTimeout(timeout);if(scanController===controller)scanController=null;button.disabled=false;button.textContent='更新結果';}
  }
  ['stockQuery','marketFilter','signalFilter'].forEach(id=>el(id).addEventListener('input',()=>{limit=30;render();}));
  el('showMore').addEventListener('click',()=>{limit+=30;render();});
  el('scanList').addEventListener('click',e=>{const b=e.target.closest('[data-stock]');if(b)showStock(b.dataset.stock);});
  el('refreshScan').addEventListener('click',load);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
  window.addEventListener('online',load);
  window.addEventListener('pagehide',()=>{chartRequest++;chartController?.abort();});
  setInterval(()=>{if(!document.hidden)load();},300000);
  load();
})();
