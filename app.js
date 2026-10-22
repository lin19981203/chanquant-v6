'use strict';
let marketCandles=null;
let marketPoints=[];
const $=id=>document.getElementById(id);
const fmt=x=>Number(x).toLocaleString('zh-TW',{maximumFractionDigits:2});
document.querySelectorAll('nav button').forEach(b=>b.addEventListener('click',()=>{
 document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active',v.id===b.dataset.tab));
 document.querySelectorAll('nav button').forEach(v=>v.classList.toggle('active',v===b));
 if(b.dataset.tab==='chart')drawCandles();
}));
function lineChart(id,series){
 const el=$(id);if(!el||!series.length)return;
 const w=Math.max(300,el.clientWidth),h=280,pad=20,lo=Math.min(...series),hi=Math.max(...series),span=Math.max(1,hi-lo);
 const points=series.map((v,i)=>`${pad+i*(w-2*pad)/Math.max(1,series.length-1)},${h-pad-(v-lo)*(h-2*pad)/span}`).join(' ');
 el.innerHTML=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="帳戶日終淨值曲線"><polyline fill="none" stroke="#8acbff" stroke-width="2" points="${points}"/></svg>`;
}
function aggregateCandles(bars,timeframe){
 if(timeframe==='D')return bars;
 const grouped=new Map();
 for(const b of bars){
  const date=new Date(b.datetime.slice(0,10)+'T00:00:00Z');let key=b.datetime.slice(0,7);
  if(timeframe==='W'){date.setUTCDate(date.getUTCDate()-((date.getUTCDay()+6)%7));key=date.toISOString().slice(0,10);}
  if(!grouped.has(key))grouped.set(key,{...b,datetime:key,volume:0});
  const g=grouped.get(key);g.high=Math.max(g.high,b.high);g.low=Math.min(g.low,b.low);g.close=b.close;g.volume+=b.volume||0;
 }
 return Array.from(grouped.values());
}
function pointBucket(date,timeframe){
 if(timeframe==='D')return date.slice(0,10);
 if(timeframe==='M')return date.slice(0,7);
 const d=new Date(date.slice(0,10)+'T00:00:00Z');d.setUTCDate(d.getUTCDate()-((d.getUTCDay()+6)%7));return d.toISOString().slice(0,10);
}
function drawCandles(){
 if(!marketCandles?.length)return;
 let bars=aggregateCandles(marketCandles,$('chartTimeframe').value);
 if($('chartRange').value==='80')bars=bars.slice(-80);
 const el=$('candlesChart'),w=Math.max(300,el.clientWidth),h=300,p=28;
 const lo=Math.min(...bars.map(b=>b.low)),hi=Math.max(...bars.map(b=>b.high)),span=Math.max(.01,hi-lo),bw=(w-p*2)/bars.length;
 const y=v=>h-p-(v-lo)*(h-p*2)/span;
 let svg=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="歷史K線圖"><text x="4" y="15" fill="#aabbd2" font-size="11">${fmt(hi)}</text><text x="4" y="${h-5}" fill="#aabbd2" font-size="11">${fmt(lo)}</text>`;
 bars.forEach((b,i)=>{const x=p+(i+.5)*bw,c=b.close>=b.open?'#ff8e90':'#7cdeae';svg+=`<line x1="${x}" x2="${x}" y1="${y(b.high)}" y2="${y(b.low)}" stroke="${c}"/><rect x="${x-bw*.3}" y="${Math.min(y(b.open),y(b.close))}" width="${Math.max(.7,bw*.6)}" height="${Math.max(1,Math.abs(y(b.open)-y(b.close)))}" fill="${c}"/>`;});
 const offsets=new Map();
 for(const event of marketPoints){
  if(!/^[BS][123]$/.test(event.kind)||!/^\d{4}-\d{2}-\d{2}$/.test(event.confirmed_date)||!/^\d{4}-\d{2}-\d{2}$/.test(event.point_date))continue;
  const bucket=pointBucket(event.confirmed_date,$('chartTimeframe').value),i=bars.findIndex(b=>b.datetime===bucket);
  if(i<0)continue;const b=bars[i],buy=event.kind[0]==='B',offset=offsets.get(bucket+buy)||0;offsets.set(bucket+buy,offset+1);
  const x=p+(i+.5)*bw,py=Math.max(12,Math.min(h-8,y(buy?b.low:b.high)+(buy?12:-9)+offset*(buy?10:-10)));
  svg+=`<text x="${x}" y="${py}" text-anchor="middle" fill="${buy?'#ffd07c':'#abacff'}" font-size="9">${event.kind}<title>端點 ${event.point_date}；確認 ${event.confirmed_date}</title></text>`;
 }
 el.innerHTML=svg+'</svg>';
 $('chartCaption').textContent=bars[0].datetime+' ～ '+bars.at(-1).datetime+' · '+bars.length+'根'+($('chartTimeframe').value==='D'?'日K':'聚合K（末根可能未完成）');
}
['chartTimeframe','chartRange'].forEach(id=>$(id).addEventListener('change',drawCandles));
function lowerTick(price){const v=price-1e-8,s=v<10?.01:v<50?.05:v<100?.1:v<500?.5:v<1000?1:5;return Math.round((Math.ceil(price/s-1e-8)*s-s)*100)/100;}
function risk(){
 const cap=+$('capital').value,pct=+$('riskpct').value,allocation=+$('allocation').value,entry=+$('entry').value,anchor=+$('anchor').value,volume=+$('signalVolume').value;
 const stop=lowerTick(anchor),budget=cap*pct/100;
 if(![cap,pct,allocation,entry,anchor,volume].every(Number.isFinite)||cap<=0||pct<=0||pct>100||allocation<=0||allocation>100||entry<=stop||stop<=0||volume<0){$('shares').textContent='請輸入有效數值';$('riskmsg').textContent='進場價必須高於結構停損。';$('budget').textContent='—';$('stopPrice').textContent='—';return;}
 $('stopPrice').textContent=fmt(stop);$('budget').textContent='NT$'+fmt(budget);
 const distance=entry-stop,friction=entry*(2*.001425+.003+2*.001);
 let shares=Math.floor(Math.min(cap*allocation/100/(entry*(1+.001425+.001)),budget/(distance+friction),volume*.01)/1000)*1000;
 if(distance/entry>.08)shares=0;
 while(shares>0){const gross=entry*shares,cost=gross+Math.max(20,Math.ceil(gross*.001425))+gross*.001;
 const sale=stop*shares-Math.max(20,Math.ceil(stop*shares*.001425))-Math.ceil(stop*shares*.003)-stop*shares*.001;
 if(cost<=cap*allocation/100&&cost-sale<=budget)break;shares-=1000;}
 $('shares').textContent=fmt(shares/1000)+' 張（'+fmt(shares)+'股）';
 $('riskmsg').textContent=distance/entry>.08?'進場價距結構停損超過8%，依本次模擬規則不進場。':shares?'預估投入 NT$'+fmt(shares*entry)+'；五千萬元仍受前日量1%限制。':'資金、風險或流動性不足一張，略過。';
}
['capital','riskpct','allocation','entry','anchor','signalVolume'].forEach(id=>$(id).addEventListener('input',risk));risk();
let liveTimer=null,liveController=null,liveGeneration=0,liveQuotesAt=null;
function disconnectLive(){liveGeneration++;clearInterval(liveTimer);liveTimer=null;liveController?.abort();liveController=null;liveQuotesAt=null;$('liveStatus').textContent='即時行情未連線';$('liveQuotes').replaceChildren();}
$('liveDisconnect').addEventListener('click',disconnectLive);
$('liveConnect').addEventListener('click',()=>{
 disconnectLive();let endpoint;
 try{endpoint=new URL($('liveEndpoint').value);if(endpoint.protocol!=='https:'||endpoint.username||endpoint.password||endpoint.search)throw new Error('請輸入不含密碼、金鑰與查詢參數的HTTPS網址');}
 catch(e){$('liveStatus').textContent=e.message||'網址無效';return;}
 const generation=liveGeneration;
 async function refreshLive(){
  if(liveController)return;const controller=new AbortController();liveController=controller;
  const timeout=setTimeout(()=>controller.abort(),8000);
  try{
   const token=$('liveAccess').value.trim();
   const response=await fetch(endpoint.href,{cache:'no-store',credentials:'omit',headers:token?{'Authorization':'Bearer '+token}:{},signal:controller.signal});if(!response.ok)throw new Error('HTTP '+response.status);
   const data=await response.json();if(generation!==liveGeneration)return;
   if(!Array.isArray(data.quotes))throw new Error('行情格式無效');
   $('liveQuotes').replaceChildren();
   const valid=data.quotes.filter(q=>q&&/^\d{4}$/.test(String(q.code))&&Number.isFinite(q.close)&&q.close>0&&Number.isFinite(Date.parse(q.date))&&Date.parse(q.date)<=Date.now()+5000);
   for(const quote of valid){const p=document.createElement('p');p.textContent=quote.code+' · '+fmt(quote.close)+' · '+new Date(quote.date).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false});$('liveQuotes').append(p);}
   const newest=Math.max(...valid.map(q=>Date.parse(q.date)));
   liveQuotesAt=newest;
   $('liveStatus').textContent=data.connected&&valid.length&&Date.now()-newest<90000?'行情串流連線中（畫面每5秒更新）':'尚無新鮮盤中行情／非交易時間';
  }catch(error){if(generation===liveGeneration){$('liveStatus').textContent='行情連線失敗：'+error.message;$('liveQuotes').replaceChildren();}}
  finally{clearTimeout(timeout);if(liveController===controller)liveController=null;}
 }
 refreshLive();liveTimer=setInterval(refreshLive,5000);
});
window.addEventListener('pagehide',()=>{disconnectLive();$('liveAccess').value='';});
