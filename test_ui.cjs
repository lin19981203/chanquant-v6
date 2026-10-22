/* Interaction tests against generated files. No live provider or GitHub requests. */
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {JSDOM}=require('jsdom');
const root=path.join(__dirname,'public');
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const actual=JSON.parse(fs.readFileSync(path.join(root,'backtest_results.json'),'utf8'));
const scan=JSON.parse(fs.readFileSync(path.join(root,'scan_results.json'),'utf8'));
const pause=()=>new Promise(r=>setTimeout(r,20));
async function boot(old=false,intercept=null){
 const dom=new JSDOM(html,{url:'https://local.chanquant.test/',runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window;w.scrollTo=()=>{};w.AbortController=AbortController;let live=false;
 w.fetch=async (url,options)=>{
  const u=new URL(url,w.location.href);
  if(intercept){const response=intercept(u,options);if(response!==undefined)return response;}
  if(u.hostname==='private-feed.test'){
   live=true;return new Response(JSON.stringify({connected:true,quotes:[{code:'2330',close:100,date:new Date().toISOString()}]}));
  }
  const p=path.join(root,u.pathname.replace(/^\//,''));
  if(old&&u.pathname.endsWith('backtest_results.json'))return new Response(JSON.stringify({version:'6.1-market-backtest-1',config:{capital:1000000}}));
  return new Response(fs.readFileSync(p),{status:200});
 };
 for(const name of ['app.js','scanner-ui.js','backtest-ui.js'])vm.runInContext(fs.readFileSync(path.join(root,name),'utf8'),dom.getInternalVMContext(),{filename:name});
 await pause();return {dom,w,liveRequested:()=>live};
}
(async()=>{
 const {dom,w,liveRequested}=await boot();const d=w.document;
 assert.equal(d.getElementById('capital').value,'50000000');
 assert.match(d.getElementById('scanState').textContent,/盤後掃描完成|部分資料未完成/);
 assert.equal(liveRequested(),false,'No private connection before user action');
 d.querySelector('[data-tab="backtest"]').click();
 assert.equal(d.querySelector('#backtest.view.active')!==null,true);
 assert.equal(d.querySelector('#backtestGroup').options.length,4);
 assert.match(d.querySelector('#backtestPanel').textContent,/50,000,000/);
 d.querySelector('#backtestGroup').value='b3';d.querySelector('#backtestGroup').dispatchEvent(new w.Event('change'));
 assert.equal(d.querySelector('#backtestGroup').value,'b3');
 assert.ok(d.querySelector('#marketEquity svg'));
 assert.equal(d.querySelector('a[download]').getAttribute('href'),'backtest_trades_b3.csv');
 d.querySelector('[data-tab="scan"]').click();
 d.querySelector('#stockQuery').value='2330';d.querySelector('#stockQuery').dispatchEvent(new w.Event('input'));
 assert.match(d.querySelector('#scanList').textContent,/2330/);
 d.querySelector('#scanList [data-stock="TWSE:2330"]').click();await pause();
 assert.ok(d.querySelector('#candlesChart svg'));
 const chartData=JSON.parse(fs.readFileSync(path.join(root,'charts/TWSE/2330.json'),'utf8'));
 assert.ok(chartData.bars.length>200,'An actual year, not the old 80-bar display');
 assert.match(d.querySelector('#chartCaption').textContent,new RegExp(chartData.bars.length+'根'));
 d.querySelector('#chartTimeframe').value='W';d.querySelector('#chartTimeframe').dispatchEvent(new w.Event('change'));
 assert.match(d.querySelector('#chartCaption').textContent,/聚合K/);
 d.querySelector('#chartTimeframe').value='M';d.querySelector('#chartTimeframe').dispatchEvent(new w.Event('change'));
 assert.match(d.querySelector('#chartCaption').textContent,/12根|13根/);
 d.querySelector('#capital').value='1000';d.querySelector('#capital').dispatchEvent(new w.Event('input'));
 assert.match(d.querySelector('#shares').textContent,/^0 張/);
 d.querySelector('#capital').value='50000000';d.querySelector('#entry').value='90';d.querySelector('#entry').dispatchEvent(new w.Event('input'));
 assert.match(d.querySelector('#riskmsg').textContent,/進場價必須高於/);
 d.querySelector('#liveEndpoint').value='https://private-feed.test/live-snapshot';d.querySelector('#liveConnect').click();await pause();
 assert.equal(liveRequested(),true);assert.match(d.querySelector('#liveStatus').textContent,/連線中/);
 d.querySelector('#liveDisconnect').click();assert.equal(d.querySelector('#liveStatus').textContent,'即時行情未連線');
 assert.equal(d.querySelector('#liveQuotes').textContent,'');
 dom.window.close();
 const old=await boot(true);
 assert.match(old.w.document.querySelector('#backtestPanel').textContent,/新版回測尚未產生或無法讀取/);
 old.dom.window.close();
 let scanCalls=0,releaseScan,invalidScan=false,holdChart=false,chartAborted=false;
 const pendingScan=new Promise(resolve=>{releaseScan=resolve;});
 const network=await boot(false,(url,options)=>{
  if(url.pathname.endsWith('scan_results.json')){
   scanCalls++;
   if(scanCalls===1)return pendingScan;
   if(invalidScan)return new Response(JSON.stringify({...scan,version:'6.1'}));
  }
  if(holdChart&&url.pathname.includes('/charts/'))return new Promise((resolve,reject)=>{
   options.signal.addEventListener('abort',()=>{chartAborted=true;reject(new DOMException('Aborted','AbortError'));},{once:true});
  });
  if(url.hostname==='private-feed.test')return new Response(JSON.stringify({connected:true,quotes:[
   {code:'2330',close:-1,date:new Date().toISOString()},
   {code:'2330',close:100,date:new Date(Date.now()+3600000).toISOString()},null]}));
 });
 const nd=network.w.document;
 network.w.dispatchEvent(new network.w.Event('online'));
 nd.dispatchEvent(new network.w.Event('visibilitychange'));
 assert.equal(scanCalls,1,'Concurrent refreshes must share the initial scan download');
 releaseScan(new Response(JSON.stringify(scan)));await pause();
 const originalList=nd.querySelector('#scanList').innerHTML;
 invalidScan=true;nd.querySelector('#refreshScan').click();await pause();
 assert.equal(nd.querySelector('#scanList').innerHTML,originalList,'An incompatible result cannot replace a valid scan');
 assert.match(nd.querySelector('#scanAlert').textContent,/版本.*先前結果/);
 nd.querySelector('#stockQuery').value='2330';nd.querySelector('#stockQuery').dispatchEvent(new network.w.Event('input'));
 nd.querySelector('#scanList [data-stock="TWSE:2330"]').click();await pause();
 assert.ok(nd.querySelector('#candlesChart svg'));
 holdChart=true;nd.querySelector('#scanList [data-stock="TWSE:2330"]').click();
 assert.equal(nd.querySelector('#candlesChart svg'),null,'Clear the previous chart immediately while the next stock loads');
 network.w.dispatchEvent(new network.w.Event('pagehide'));await pause();
 assert.equal(chartAborted,true,'Leaving the page aborts a pending chart download');
 nd.querySelector('#liveEndpoint').value='https://private-feed.test/live-snapshot';nd.querySelector('#liveConnect').click();await pause();
 assert.equal(nd.querySelector('#liveQuotes').textContent,'');
 assert.doesNotMatch(nd.querySelector('#liveStatus').textContent,/連線中/,'Invalid and future quotes cannot appear fresh');
 network.dom.window.close();
 console.log(JSON.stringify({status:'passed',checks:['50-million capital','actual scan loading','no automatic live request','group switching','equity SVG','group CSV','stock search','year chart','weekly/monthly aggregation','risk constraints','mocked live connect/disconnect','legacy report rejected','single scan request on concurrent refresh','preserve valid scan on version mismatch','clear old chart while loading','abort chart on page exit','reject invalid or future live quotes'],scope:'DOM interaction checks; no visual browser or authenticated market feed verification',actual_year_bars:chartData.bars.length,screened:scan.stocks.length,return_pct:actual.reports.all.summary.total_return_pct}));
})().catch(e=>{console.error(e);process.exitCode=1});
