import unittest
from copy import deepcopy
import backtest_market as bt

class ExecutionTests(unittest.TestCase):
    def fixture(self):
        bars=[['2026-01-01',20,20.5,19.5,20,1000000,20000000],
              ['2026-01-02',20,20.5,19.5,20.2,1000000,20000000],
              ['2026-01-05',22,22.5,21.5,22,1000000,22000000]]
        stock={'code':'1111','name':'測試','market':'TWSE','bars':bars,'by_date':{b[0]:(i,b) for i,b in enumerate(bars)}}
        signal={'key':'TWSE:1111','date':bars[0][0],'signal':'中樞突破候選','score':80,'amount':20000000,'volume':1000000,'initial_stop':19}
        dates=[b[0] for b in bars[1:]]
        return {'TWSE:1111':stock},dates,{dates[0]:bars[0][0],dates[1]:bars[1][0]},{bars[0][0]:[signal]}

    def test_next_open_and_cost_accounting(self):
        report=bt.simulate(*self.fixture())
        trade=report['trades'][0]
        self.assertEqual(trade['entry_date'],'2026-01-02')
        self.assertEqual(trade['exit_date'],'2026-01-05')
        self.assertEqual(trade['shares'],4000)
        self.assertEqual(trade['entry_cost'],80194)
        self.assertEqual(trade['pnl'],7328)
        self.assertEqual(report['summary']['final_equity'],1007328)
        self.assertEqual(trade['reason'],'gap_target')

    def test_stop_precedes_target_in_ambiguous_bar(self):
        b=['2026-01-02',20,23,18,21,1000000,20000000]
        self.assertEqual(bt.protective_exit(b,19,22),(19,'stop',True))

    def test_gap_cannot_fill_at_old_stop(self):
        b=['2026-01-02',17,18,16,17.5,1000000,20000000]
        self.assertEqual(bt.protective_exit(b,19,22),(17,'gap_stop',False))

    def test_locked_bar_has_no_assumed_execution(self):
        b=['2026-01-02',18,18,18,18,1000000,18000000]
        self.assertIsNone(bt.protective_exit(b,19,22))

    def test_open_holdings_not_counted_as_wins(self):
        stocks,dates,previous,candidates=self.fixture()
        result=bt.simulate(stocks,dates[:1],previous,candidates)
        self.assertEqual(result['summary']['closed_trades'],0)
        self.assertIsNone(result['summary']['win_rate_pct'])
        self.assertEqual(result['summary']['open_positions'],1)
        self.assertNotEqual(result['summary']['total_return_pct'],0)

    def test_minimum_fee_and_sell_tax(self):
        cfg=bt.DEFAULTS
        self.assertEqual(bt.fee(1000,cfg),20)
        self.assertEqual(bt.exit_cash(10,100,cfg),(976,24))

    def test_future_prices_do_not_change_earlier_results(self):
        stocks,dates,previous,candidates=self.fixture()
        earlier=bt.simulate(stocks,dates[:1],previous,candidates)
        stocks['TWSE:1111']['bars'][-1][4]=10000
        later=bt.simulate(stocks,dates[:1],previous,candidates)
        self.assertEqual(earlier,later)

    def test_cannot_use_capital_for_more_than_one_board_lot(self):
        stocks,dates,previous,candidates=self.fixture()
        report=bt.simulate(stocks,dates,previous,candidates,config={'capital':1000})
        self.assertEqual(report['summary']['closed_trades'],0)
        self.assertEqual(report['summary']['open_positions'],0)
        self.assertEqual(report['summary']['final_equity'],1000)

    def test_signal_groups_remain_separate(self):
        report=bt.simulate(*self.fixture(),group='trend')
        self.assertEqual(report['summary']['closed_trades'],0)

    def test_missing_next_day_does_not_backdate_order(self):
        stocks,dates,previous,candidates=self.fixture()
        del stocks['TWSE:1111']['by_date'][dates[0]]
        report=bt.simulate(stocks,dates,previous,candidates)
        self.assertEqual(report['summary']['closed_trades'],0)
        self.assertEqual(report['summary']['open_positions'],0)
        self.assertEqual(report['summary']['skipped']['missing_next_session'],1)

    def test_blocked_stop_stays_pending_after_price_recovers(self):
        stocks,dates,previous,candidates=self.fixture()
        bars=stocks['TWSE:1111']['bars']
        bars[-1][:]=['2026-01-05',18,18,18,18,1000000,18000000]
        bars.append(['2026-01-06',20,20.5,19.8,20.1,1000000,20000000])
        stocks['TWSE:1111']['by_date']={b[0]:(i,b) for i,b in enumerate(bars)}
        dates.append(bars[-1][0]);previous[dates[-1]]=dates[-2]
        report=bt.simulate(stocks,dates,previous,candidates)
        self.assertEqual(report['trades'][0]['exit_date'],'2026-01-06')
        self.assertEqual(report['trades'][0]['reason'],'blocked_stop_next_open')

if __name__=='__main__':unittest.main()
