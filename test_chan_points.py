import datetime as dt
import random
import unittest
from copy import deepcopy
import chan_points as cp
import backtest_chan as bt

class PointTests(unittest.TestCase):
    def detector(self):
        d=cp.Detector()
        d.bars=[[(dt.date(2025,1,1)+dt.timedelta(days=i)).isoformat(),20,40,1,20,1000000,20000000] for i in range(200)]
        d.hist=[-1.]*200
        return d

    def pivot(self,d,price,side,i):
        return d.accept_pivot({'price':price,'type':side,'i':i,'j':i,'confirmed':i+2},i+2)

    def test_no_unconfirmed_right_fractal(self):
        d=cp.Detector()
        for i,(h,l) in enumerate([(11,9),(14,12),(12,10)]):
            self.assertEqual(d.push([str(i),l,h,l,l,1000,10000]),[])
        self.assertEqual(d.pivots,[])
        d.push(['3',8,10,8,9,1000,10000])
        self.assertEqual(len(d.pivots),1)
        self.assertEqual(d.pivots[0]['i'],1)
        self.assertEqual(d.pivots[0]['confirmed'],3)

    def test_third_buy_needs_confirmed_departure_and_first_return(self):
        d=self.detector()
        for b in d.bars:b[2]=50;b[3]=31
        d.contexts=[{'lower':20,'upper':30,'start_index':0,'end_index':30,'confirmed_index':32}]
        self.assertEqual(self.pivot(d,35,1,40),[])
        ev=self.pivot(d,32,-1,50)
        self.assertEqual([e['kind'] for e in ev],['B3'])
        self.assertEqual(ev[0]['confirmed_date'],d.bars[52][0])
        self.assertEqual(ev[0]['point_date'],d.bars[50][0])
        self.pivot(d,36,1,60)
        self.assertFalse(any(e['kind']=='B3' for e in self.pivot(d,33,-1,70)))

    def test_return_to_center_disqualifies_third_buy(self):
        d=self.detector();d.contexts=[{'lower':20,'upper':30,'start_index':0,'end_index':30,'confirmed_index':32}]
        self.pivot(d,35,1,40)
        self.assertFalse(any(e['kind']=='B3' for e in self.pivot(d,29,-1,50)))

    def test_third_sell_is_mirror(self):
        d=self.detector()
        for b in d.bars:b[2]=19;b[3]=10
        d.contexts=[{'lower':20,'upper':30,'start_index':0,'end_index':30,'confirmed_index':32}]
        self.pivot(d,15,-1,40)
        self.assertIn('S3',[e['kind'] for e in self.pivot(d,18,1,50)])

    def test_second_buy_is_first_return_only(self):
        d=self.detector()
        for b in d.bars:b[3]=11
        self.pivot(d,10,-1,10)
        d.pending_first['B']={'point_index':10,'point_date':d.bars[10][0],'price':10}
        self.pivot(d,20,1,20)
        events=self.pivot(d,12,-1,30)
        self.assertIn('B2',[e['kind'] for e in events])
        self.pivot(d,21,1,40)
        self.assertNotIn('B2',[e['kind'] for e in self.pivot(d,13,-1,50)])

    def test_second_buy_rejects_intervening_break(self):
        d=self.detector()
        for b in d.bars:b[3]=11
        self.pivot(d,10,-1,10)
        d.pending_first['B']={'point_index':10,'point_date':d.bars[10][0],'price':10}
        self.pivot(d,20,1,20);d.bars[25][3]=9
        self.assertNotIn('B2',[e['kind'] for e in self.pivot(d,12,-1,30)])
        self.assertNotIn('B',d.pending_first)

    def test_first_buy_requires_two_centers_and_weaker_down_leg(self):
        d=self.detector()
        d.centers=[{'lower':25,'upper':30,'start_index':0,'end_index':30,'confirmed_index':32},
                   {'lower':15,'upper':20,'start_index':40,'end_index':70,'confirmed_index':72}]
        for i in range(100,111):d.hist[i]=-.3
        for price,side,i in [(19,1,80),(12,-1,90),(18,1,100)]:self.pivot(d,price,side,i)
        self.assertIn('B1',[e['kind'] for e in self.pivot(d,10,-1,110)])
        e=[e for e in d.events if e['kind']=='B1'][-1]
        self.assertAlmostEqual(e['macd_area_ratio'],.3)

    def test_one_center_is_not_first_class(self):
        d=self.detector();d.centers=[{'lower':15,'upper':20,'start_index':40,'end_index':70,'confirmed_index':72}]
        for i in range(100,111):d.hist[i]=-.3
        for price,side,i in [(19,1,80),(12,-1,90),(18,1,100)]:self.pivot(d,price,side,i)
        self.assertNotIn('B1',[e['kind'] for e in self.pivot(d,10,-1,110)])

    def test_first_sell_is_mirrored_uptrend_divergence(self):
        d=self.detector();d.hist=[1.]*200
        d.centers=[{'lower':10,'upper':15,'start_index':0,'end_index':30,'confirmed_index':32},
                   {'lower':20,'upper':25,'start_index':40,'end_index':70,'confirmed_index':72}]
        for i in range(100,111):d.hist[i]=.3
        for price,side,i in [(20,-1,80),(28,1,90),(22,-1,100)]:self.pivot(d,price,side,i)
        self.assertIn('S1',[e['kind'] for e in self.pivot(d,30,1,110)])

    def test_second_sell_is_first_lower_high(self):
        d=self.detector()
        for b in d.bars:b[2]=29
        self.pivot(d,30,1,10)
        d.pending_first['S']={'point_index':10,'point_date':d.bars[10][0],'price':30}
        self.pivot(d,20,-1,20)
        self.assertIn('S2',[e['kind'] for e in self.pivot(d,28,1,30)])

    def test_future_bars_do_not_rewrite_emitted_events(self):
        rng=random.Random(42);bars=[];price=50
        for i in range(350):
            price=max(12,price+rng.uniform(-4,4))
            bars.append([str(i),price,price+1,price-1,price,1000000,50000000])
        first=cp.analyse(bars[:240]);events=deepcopy(first.events)
        self.assertGreater(len(events),0)
        for bar in bars[240:]:first.push(bar)
        self.assertEqual([e for e in first.events if int(e['confirmed_date'])<240],events)
        for n in [100,200,300]:
            self.assertEqual(cp.analyse(bars[:n]).events,[e for e in first.events if int(e['confirmed_date'])<n])

    def test_stop_uses_lower_tick_at_boundary(self):
        self.assertEqual(cp.below(50),49.95)
        self.assertEqual(cp.below(100),99.9)
        self.assertEqual(cp.below(1000),999)

class StructuralExecutionTests(unittest.TestCase):
    def fixture(self):
        bars=[['2026-01-01',20,20.5,19.5,20,100000000,2000000000],
              ['2026-01-02',20,23,19.5,22,100000000,2000000000],
              ['2026-01-05',24,25,23,24,100000000,2400000000],
              ['2026-01-06',23,24,22,23,100000000,2300000000]]
        stock={'code':'1111','name':'測試','market':'TWSE','bars':bars,'by_date':{b[0]:(i,b) for i,b in enumerate(bars)}}
        signal={'key':'TWSE:1111','date':bars[0][0],'signal':'B3','score':85,'amount':bars[0][6],
                'volume':bars[0][5],'initial_stop':19,'entry_allowed':True,'point_date':'2025-12-30'}
        dates=[b[0] for b in bars[1:]]
        return {'TWSE:1111':stock},dates,dict(zip(dates,[b[0] for b in bars[:-1]])),{bars[0][0]:[signal]}

    def test_no_fixed_target_and_fifty_million(self):
        report=bt.simulate(*self.fixture())
        self.assertEqual(report['summary']['initial_capital'],50_000_000)
        self.assertEqual(report['summary']['closed_trades'],0)
        self.assertEqual(report['summary']['open_positions'],1)

    def test_sell_point_executes_only_next_open(self):
        stocks,dates,previous,events=self.fixture()
        events[dates[0]]=[{'key':'TWSE:1111','signal':'S1'}]
        report=bt.simulate(stocks,dates,previous,events)
        self.assertEqual(report['trades'][0]['exit_date'],dates[1])
        self.assertEqual(report['trades'][0]['exit_price'],24)
        self.assertEqual(report['trades'][0]['reason'],'S1_next_open')

    def test_new_stop_not_applied_before_confirmation(self):
        stocks,dates,previous,events=self.fixture()
        events[dates[0]]=[{'key':'TWSE:1111','signal':'B2','initial_stop':21,'entry_allowed':False}]
        # Entry day's low 19.5 is below the close-confirmed raised stop, but above original 19.
        report=bt.simulate(stocks,dates[:1],previous,events)
        self.assertEqual(report['summary']['closed_trades'],0)
        self.assertEqual(report['open_positions'][0]['structural_stop'],21)

    def test_volume_limit_does_not_scale_with_capital(self):
        stocks,dates,previous,events=self.fixture()
        events['2026-01-01'][0]['volume']=500000
        report=bt.simulate(stocks,dates,previous,events)
        self.assertLessEqual(report['open_positions'][0]['shares'],5000)

    def test_blocked_structural_stop_stays_pending(self):
        stocks,dates,previous,events=self.fixture()
        bars=stocks['TWSE:1111']['bars']
        bars[2][:]=[dates[1],18,18,18,18,1000000,18000000]
        report=bt.simulate(stocks,dates,previous,events)
        self.assertEqual(report['trades'][0]['exit_date'],dates[2])
        self.assertEqual(report['trades'][0]['reason'],'blocked_stop_next_open')

    def test_no_fixed_holding_period_or_ma_exit(self):
        stocks,dates,previous,events=self.fixture()
        bars=stocks['TWSE:1111']['bars']
        # After entry a slow decline stays above the structural stop for 30 valid bars.
        bars[:]=bars[:2]
        for i in range(30):
            date=(dt.date(2026,1,5)+dt.timedelta(days=i)).isoformat()
            price=22-i*.05
            bars.append([date,price,price+.2,price-.2,price,1000000,20000000])
        stocks['TWSE:1111']['by_date']={b[0]:(i,b) for i,b in enumerate(bars)}
        dates[:]=[b[0] for b in bars[1:]]
        previous={b[0]:bars[i][0] for i,b in enumerate(bars[1:])}
        report=bt.simulate(stocks,dates,previous,events)
        self.assertEqual(report['summary']['closed_trades'],0)
        self.assertEqual(report['summary']['open_positions'],1)

if __name__=='__main__':unittest.main()
