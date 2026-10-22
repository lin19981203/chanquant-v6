import datetime as dt
import json
import unittest
from copy import deepcopy
from live_gateway import Feed,normalize,authorized

class LiveTests(unittest.TestCase):
    def test_relay_requires_separate_access_token(self):
        self.assertFalse(authorized(None,''))
        self.assertFalse(authorized('Bearer wrong','private-token'))
        self.assertTrue(authorized('Bearer private-token','private-token'))
    def message(self):
        return {'event':'data','channel':'candles','data':{'symbol':'2330',
            'date':dt.datetime.now(dt.timezone.utc).isoformat(),'open':100,'high':102,'low':99,'close':101,'volume':5}}
    def test_minute_lots_converted_and_unfinished_flagged(self):
        q=normalize(self.message(),{'2330'})
        self.assertEqual(q['volume_shares'],5000)
        self.assertFalse(q['final'])
    def test_wrong_channel_and_unsubscribed_symbol_rejected(self):
        m=self.message();m['channel']='trades'
        self.assertIsNone(normalize(m,{'2330'}))
        self.assertIsNone(normalize(self.message(),{'2317'}))
    def test_invalid_price_and_naive_time_rejected(self):
        m=self.message();m['data']['close']=float('nan')
        self.assertIsNone(normalize(m,{'2330'}))
        m=self.message();m['data']['date']='2026-01-01T09:00:00'
        self.assertIsNone(normalize(m,{'2330'}))
    def test_out_of_order_update_does_not_replace_new_quote(self):
        f=Feed({'2330'});m=self.message();f.message(None,json.dumps(m))
        earlier=deepcopy(m);earlier['data']['date']='2025-01-01T09:00:00+08:00'
        f.message(None,json.dumps(earlier))
        self.assertEqual(f.snapshot()['quotes'][0]['close'],101)
        self.assertEqual(f.snapshot()['quotes'][0]['date'],m['data']['date'])
        self.assertFalse(f.snapshot()['live_signals_enabled'])
    def test_provider_error_never_in_snapshot(self):
        f=Feed({'2330'});f.message(None,json.dumps({'event':'error','data':{'apikey':'private-secret'}}))
        self.assertNotIn('private-secret',json.dumps(f.snapshot()))

if __name__=='__main__':unittest.main()
