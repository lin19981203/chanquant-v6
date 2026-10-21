import datetime as dt
import unittest
from unittest.mock import patch
import scanner

class ScannerTests(unittest.TestCase):
    def bars(self, count=65):
        start=dt.date(2026,1,1)
        return [[(start+dt.timedelta(days=i)).isoformat(), 100+i,102+i,99+i,101+i,1000000,150000000] for i in range(count)]

    def stock(self,bars):
        return {'name':'測試','market':'TWSE','bars':bars}

    def test_numeric_missing_and_nonfinite(self):
        self.assertEqual(scanner.number('1,234.5'),1234.5)
        for value in ['--','NaN','inf','除權息']:
            self.assertIsNone(scanner.number(value))

    def test_security_universe(self):
        self.assertTrue(scanner.common_stock('2330','台積電'))
        for code, name in [('0050','元大台灣50'),('9103','美德醫療DR'),('2002A','中鋼特'),('123456','權證')]:
            self.assertFalse(scanner.common_stock(code,name))

    def test_source_date_mismatch_rejected(self):
        import io
        with patch('scanner.urlopen',return_value=io.BytesIO(b'{"date":"20260101","tables":[]}')):
            with self.assertRaisesRegex(ValueError,'Date mismatch'):
                scanner.fetch_day('TWSE',dt.date(2026,1,2))

    def test_unrecognised_schema_is_not_holiday(self):
        import io
        with patch('scanner.urlopen',return_value=io.BytesIO(b'{"date":"20260102","stat":"OK","tables":[]}')):
            with self.assertRaisesRegex(ValueError,'recognised'):
                scanner.fetch_day('TWSE',dt.date(2026,1,2))

    def test_warmup_has_no_candidate(self):
        bars=self.bars(59)
        row=scanner.evaluate('2330',self.stock(bars),bars[-1][0])
        self.assertEqual(row['signal'],'資料累積中')
        self.assertEqual(row['score'],0)

    def test_stale_stock_is_excluded(self):
        row=scanner.evaluate('2330',self.stock(self.bars()),'2026-10-21')
        self.assertEqual(row['signal'],'缺當日成交')
        self.assertEqual(row['score'],0)

    def test_liquidity_filter(self):
        bars=self.bars();bars[-1][6]=1000
        self.assertEqual(scanner.evaluate('2330',self.stock(bars),bars[-1][0])['signal'],'流動性未達')

    def test_prior_volume_average_excludes_current_bar(self):
        bars=self.bars();bars[-1][5]=2000000
        row=scanner.evaluate('2330',self.stock(bars),bars[-1][0])
        self.assertEqual(row['volume_ratio'],2)

    def test_trend_breakout(self):
        bars=self.bars();bars[-1][2]=180;bars[-1][4]=179;bars[-1][5]=2000000
        row=scanner.evaluate('2330',self.stock(bars),bars[-1][0])
        self.assertEqual(row['signal'],'趨勢新高觀察')
        self.assertGreater(row['score'],0)

    def test_center_reference_excludes_signal_bar(self):
        bars=self.bars()
        with patch('scanner.latest_center', return_value=None) as f:
            scanner.evaluate('2330',self.stock(bars),bars[-1][0])
            self.assertEqual(f.call_args.args[0],bars[:-1])

    def test_center_breakout_requires_prior_close_below_upper(self):
        bars=self.bars();bars[-1][2]=180;bars[-1][4]=179;bars[-1][5]=2000000
        center={'lower':150,'upper':165,'end_index':45,'confirmed_index':46,'start':bars[30][0],'end':bars[45][0]}
        with patch('scanner.latest_center',return_value=center):
            self.assertEqual(scanner.evaluate('2330',self.stock(bars),bars[-1][0])['signal'],'中樞突破候選')

    def test_center_pullback_must_hold_upper(self):
        bars=self.bars()
        center={'lower':145,'upper':155,'end_index':45,'confirmed_index':46,'start':bars[30][0],'end':bars[45][0]}
        with patch('scanner.latest_center',return_value=center):
            self.assertEqual(scanner.evaluate('2330',self.stock(bars),bars[-1][0])['signal'],'中樞回踩候選')
            bars[-1][3]=154
            self.assertNotEqual(scanner.evaluate('2330',self.stock(bars),bars[-1][0])['signal'],'中樞回踩候選')

    def test_fractal_requires_right_bar(self):
        bars=self.bars(4)
        self.assertIsNone(scanner.latest_center(bars))

    def test_inclusion_direction(self):
        bars=[['1',9,10,8,9,1,1],['2',10,12,9,11,1,1],['3',10,11,9.5,10,1,1]]
        merged=scanner.merge_inclusions(bars)
        self.assertEqual(len(merged),2)
        self.assertEqual((merged[-1]['h'],merged[-1]['l']),(12,9.5))

if __name__=='__main__':unittest.main()
