import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import scanner
import export_charts
import backtest_chan

class YearDataTests(unittest.TestCase):
    def history(self):
        bars=[]
        for i in range(477):
            date=dt.date(2025,7,2)+dt.timedelta(days=i)
            if date.weekday()<5:
                price=100+i*.01
                bars.append([str(date),price,price+1,price-1,price,1000000,100000000])
        return {'markets':{'TWSE':{'fetched':[],'stocks':{'2330':{'name':'台積電','market':'TWSE','bars':bars}}}}}
    def test_history_update_does_not_truncate_to_180(self):
        history=self.history();bars=history['markets']['TWSE']['stocks']['2330']['bars']
        day=dt.date.fromisoformat(bars[-1][0])+dt.timedelta(days=1)
        while day.weekday()>4:day+=dt.timedelta(days=1)
        row=('2330','台積電',[str(day),105,106,104,105,1000000,105000000])
        with patch.object(scanner,'fetch_day',return_value=[row]):
            scanner.update_market('TWSE',history,[day],0)
        self.assertGreater(len(history['markets']['TWSE']['stocks']['2330']['bars']),300)
    def test_chart_exports_one_year_not_warmup_or_last_80(self):
        history=self.history()
        with tempfile.TemporaryDirectory() as tmp:
            export_charts.export(history,Path(tmp))
            data=json.loads((Path(tmp)/'charts/TWSE/2330.json').read_text())
            self.assertGreater(len(data['bars']),200)
            self.assertLess(len(data['bars']),300)
            self.assertTrue(all(data['requested_start']<=b[0]<=data['end'] for b in data['bars']))
            self.assertGreater(data['bars'][0][0],history['markets']['TWSE']['stocks']['2330']['bars'][0][0])
    def test_incomplete_download_cannot_be_published_as_year_backtest(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'history.json'
            p.write_text(json.dumps({'markets':{},'_backtest_provenance':{
                'expected_queries':682,'successful_queries':681,'unresolved_queries':[{'date':'2025-07-02'}]}}))
            with patch('sys.argv',['backtest_chan.py','--history',str(p)]):
                with self.assertRaisesRegex(SystemExit,'unresolved'):
                    backtest_chan.main()

if __name__=='__main__':unittest.main()
