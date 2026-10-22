"""Causal, explicitly simplified Chan buy/sell point references, on daily bars.

Not a full recursive Chan implementation. A fractal's right inclusion group must
be sealed by a new non-included bar before it is emitted. Event dates are the
confirmation date, never the historical pivot date. Previously emitted events
are retained even if a later, more extreme same-side pivot replaces an endpoint.
"""
from copy import deepcopy
import math

LABELS = {'B1':'一類買點參考','B2':'二類買點參考','B3':'三類買點參考',
          'S1':'一類賣點參考','S2':'二類賣點參考','S3':'三類賣點參考'}

RULES = [
    '日K簡化筆級代理，沒有遞迴次級別走勢或線段，不能稱完整正統一、二、三類買賣點。',
    '包含K依方向合併；右側合併K封閉後才確認分型，交替端點至少相距4根合併K；訊號記在確認日而非分型日。',
    '一類：至少兩個依序不重疊的同向中樞，端點創新低／高，最後同向筆的MACD(12,26,9)同號柱面積不超過前一同向筆80%；這是背馳代理。',
    '二類：一類參考之後第一次反向回檔／反彈的已確認端點，不破一類低點／高點；若第一次不符合，不將後續端點冒充第一次。',
    '三類：已確認中樞形成後，已確認端點離開中樞，第一次反向筆的已確認端點不返回中樞；買點在上緣上方、賣點在下緣下方。',
    '中樞由連續三筆價格重疊形成，趨勢一類參考要求兩個先後不共用筆區間且價格不重疊的中樞。',
    '買入只用當日新確認B1/B2/B3，保留股價10元、成交量500張、成交額2千萬元及60根日K門檻；不再強制MA20>MA60，以容許一類反轉。',
    '出場用新確認S1/S2/S3，在下一交易日開盤執行；不使用固定2R、均線或20日時間出場。',
    '結構停損設於買點已確認回檔低點下一個有效跳動單位；後續B2/B3可提高、不可降低停損，收盤確認後次交易日起生效。',
    '50,000,000元是模擬本金；每檔最多淨值10%、最多10檔、每筆風險預算0.5%、整張且最多訊號日量1%；距結構停損超過8%不進場。',
]

def tick(price):
    return .01 if price < 10 else .05 if price < 50 else .1 if price < 100 else .5 if price < 500 else 1 if price < 1000 else 5

def below(price):
    # Use the lower bracket at tick boundaries: 50 -> 49.95, 100 -> 99.9.
    step = tick(price-1e-8)
    return round(math.ceil(price/step-1e-8)*step-step,2)

def center_for(ps):
    if len(ps) != 4:
        return None
    lower=max(min(a['price'],b['price']) for a,b in zip(ps,ps[1:]))
    upper=min(max(a['price'],b['price']) for a,b in zip(ps,ps[1:]))
    if lower >= upper:
        return None
    return {'lower':lower,'upper':upper,'start_index':ps[0]['i'],
            'end_index':ps[-1]['i'],'confirmed_index':ps[-1]['confirmed']}

class Detector:
    def __init__(self):
        self.bars=[];self.clean=[];self.pivots=[];self.events=[];self.centers=[]
        self.contexts=[];self.pending_first={};self.direction=1
        self.ema12=None;self.ema26=None;self.dea=0.;self.hist=[]
        self.center_ids=set()

    def _area(self,a,b,side):
        return sum(max(side*h,0.) for h in self.hist[a:b+1])

    def _event(self,kind,p,confirmation,extra=None):
        out={'kind':kind,'label':LABELS[kind],'point_date':self.bars[p['i']][0],
             'confirmed_date':self.bars[confirmation][0], 'point_index':p['i'],
             'confirmed_index':confirmation,'price':p['price'],
             'reference_stop':below(p['price']) if kind.startswith('B') else None}
        if extra:out.update(extra)
        self.events.append(out)
        return out

    def accept_pivot(self,p,confirmation):
        # Public for deterministic structural tests; push() is the OHLC entrypoint.
        replacement=False
        if self.pivots:
            last=self.pivots[-1]
            if p['type']==last['type']:
                if (p['price']-last['price'])*p['type'] <= 0:
                    return []
                self.pivots[-1]=p;replacement=True
            elif p['j']-last['j'] < 4:
                return []
            else:self.pivots.append(p)
        else:self.pivots.append(p)
        start=len(self.events)
        side='B' if p['type']==-1 else 'S'
        first=self.pending_first.get(side)
        # An extension of the same endpoint is not its first countertrend return.
        if first and p['i']>first['point_index'] and not replacement:
            valid=(p['price']>first['price'] if side=='B' else p['price']<first['price'])
            segment=self.bars[first['point_index']+1:p['i']+1]
            if side=='B':valid=valid and all(b[3]>first['price'] for b in segment)
            else:valid=valid and all(b[2]<first['price'] for b in segment)
            if valid:self._event(side+'2',p,confirmation,{'first_point_date':first['point_date']})
            del self.pending_first[side]

        # Each center contributes only its first departure-and-return attempt per side.
        for c in self.contexts:
            if p['i'] <= c['end_index']:
                continue
            for letter,departure_type,boundary in [('B',1,c['upper']),('S',-1,c['lower'])]:
                if c.get(letter+'_done'):continue
                departure=c.get(letter+'_departure')
                if departure is None and p['type']==departure_type and p['i']>c['confirmed_index']:
                    outside=p['price']>boundary if letter=='B' else p['price']<boundary
                    if outside:c[letter+'_departure']=p['i']
                elif departure is not None and p['type']==-departure_type and p['i']>departure:
                    segment=self.bars[departure+1:p['i']+1]
                    valid=(p['price']>boundary and all(b[3]>boundary for b in segment) if letter=='B'
                           else p['price']<boundary and all(b[2]<boundary for b in segment))
                    if valid:self._event(letter+'3',p,confirmation,{'center_lower':c['lower'],'center_upper':c['upper'],
                        'center_confirmed_date':self.bars[c['confirmed_index']][0]})
                    c[letter+'_done']=True

        # Require two distinct, completed, non-overlapping center intervals.
        available=[c for c in self.centers if c['confirmed_index']<p['i']]
        trend=False
        if len(available)>=2:
            recent=available[-1]
            earlier=next((c for c in reversed(available[:-1]) if c['end_index']<=recent['start_index'] and
                          (recent['upper']<c['lower'] if side=='B' else recent['lower']>c['upper'])),None)
            if earlier:
                trend=(recent['upper']<earlier['lower'] and p['price']<recent['lower'] if side=='B'
                       else recent['lower']>earlier['upper'] and p['price']>recent['upper'])
        ps=self.pivots
        if trend and len(ps)>=4:
            a,b,c,d=ps[-4:]
            more=d['price']<b['price'] if side=='B' else d['price']>b['price']
            direction=-1 if side=='B' else 1
            area1=self._area(a['i'],b['i'],direction)
            area2=self._area(c['i'],d['i'],direction)
            if more and area1>0 and 0<area2<=.8*area1:
                event=self._event(side+'1',p,confirmation,{'macd_area_ratio':round(area2/area1,6)})
                self.pending_first[side]=event

        center=center_for(ps[-4:])
        if center:
            identity=(center['start_index'],center['end_index'])
            if identity not in self.center_ids:
                self.center_ids.add(identity);self.centers.append(center)
                self.contexts.append(deepcopy(center))
        # Only contexts from the last 120 raw sessions remain eligible; this is an explicit rule.
        self.contexts=[c for c in self.contexts if confirmation-c['confirmed_index']<=120]
        # Identical points can reference several overlapping centers. Emit one event per kind/endpoint.
        new=self.events[start:];unique={}
        for e in new:unique[(e['kind'],e['point_index'])]=e
        self.events[start:]=list(unique.values())
        return self.events[start:]

    def push(self,bar):
        i=len(self.bars);self.bars.append(bar)
        price=bar[4]
        self.ema12=price if self.ema12 is None else self.ema12+2/13*(price-self.ema12)
        self.ema26=price if self.ema26 is None else self.ema26+2/27*(price-self.ema26)
        diff=self.ema12-self.ema26;self.dea+=2/10*(diff-self.dea)
        self.hist.append(2*(diff-self.dea))
        new={'h':bar[2],'l':bar[3],'i':i}
        if self.clean:
            last=self.clean[-1]
            included=((new['h']<=last['h'] and new['l']>=last['l']) or
                      (new['h']>=last['h'] and new['l']<=last['l']))
            if included:
                reducer=max if self.direction>0 else min
                self.clean[-1]={'h':reducer(last['h'],new['h']),'l':reducer(last['l'],new['l']),'i':i}
                return []
            self.direction=1 if new['h']>last['h'] else -1
        self.clean.append(new)
        if len(self.clean)<4:return []
        # All three groups are now sealed. The last group is intentionally excluded.
        a,b,c=self.clean[-4:-1];j=len(self.clean)-3
        top=b['h']>max(a['h'],c['h']) and b['l']>max(a['l'],c['l'])
        bottom=b['l']<min(a['l'],c['l']) and b['h']<min(a['h'],c['h'])
        if not (top or bottom):return []
        p={'type':1 if top else -1,'price':b['h'] if top else b['l'],'i':b['i'],'j':j,'confirmed':i}
        return self.accept_pivot(p,i)

def analyse(bars):
    d=Detector()
    for bar in bars:d.push(bar)
    return d

def scan_row(code,stock,market_date):
    bars=stock['bars'];current=bars[-1]
    row={'code':code,'name':stock['name'],'market':stock['market'],'date':current[0],
         'close':current[4],'volume':current[5],'amount':current[6],'bars':len(bars),
         'signal':'觀察','score':0,'change_pct':round(100*(current[4]/bars[-2][4]-1),2) if len(bars)>1 else None,
         'history_start':bars[0][0], 'chart_path':f'charts/{stock["market"]}/{code}.json'}
    if current[0]!=market_date:row['signal']='缺當日成交';return row
    if len(bars)<60:row['signal']='資料累積中';return row
    d=analyse(bars)
    events=[e for e in d.events if e['confirmed_date']==current[0]]
    row['recent_points']=d.events[-8:]
    row['points']=events
    row['ma20']=round(sum(b[4] for b in bars[-20:])/20,2)
    row['ma60']=round(sum(b[4] for b in bars[-60:])/60,2)
    row['volume_ratio']=round(current[5]/(sum(b[5] for b in bars[-21:-1])/20),2)
    liquid=current[4]>=10 and current[5]>=500_000 and current[6]>=20_000_000
    sells=[e for e in events if e['kind'].startswith('S')]
    buys=[e for e in events if e['kind'].startswith('B')]
    selected=max(sells or buys,key=lambda e:e['kind']) if (sells or buys) else None
    if selected:
        row['signal']=selected['label'];row['point']=selected
        row['reasons']=['端點 '+selected['point_date']+'；確認日 '+selected['confirmed_date'],'日K簡化筆級代理，非遞迴次級別確認']
        alive=not selected['kind'].startswith('B') or all(b[3]>selected['reference_stop'] for b in bars[selected['point_index']+1:])
        if selected['kind'].startswith('S') or (liquid and alive):
            row['score']=70+int(selected['kind'][1])*5
        elif not liquid:row['signal']='流動性未達';row['reasons'].append('買入流動性門檻未達')
        else:row['signal']='買點結構已失效';row['reasons'].append('端點確認時已跌破結構停損參考')
    elif not liquid:row['signal']='流動性未達'
    if d.centers:
        c=d.centers[-1];row['center']={'lower':c['lower'],'upper':c['upper'],
            'start':bars[c['start_index']][0],'end':bars[c['end_index']][0]}
    return row
