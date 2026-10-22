"""Optional PRIVATE, read-only Fugle candle relay. No trading APIs.

Provider secrets stay in environment variables. Binds to loopback only. For mobile access,
put an HTTPS reverse proxy in front; a separate private access token is required;
do not expose this process or provider data as an unauthenticated public feed.
Live candles never overwrite final daily quotes or enter the daily backtest.
"""
import datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hmac
import math
import os
import re
import threading
import time

ENDPOINT='wss://api.fugle.tw/marketdata/v1.0/stock/streaming'

def authorized(header,token):
    return bool(token) and hmac.compare_digest(str(header or '').encode(),'Bearer '.encode()+token.encode())

def normalize(message, symbols):
    if not isinstance(message,dict) or message.get('event')!='data' or message.get('channel')!='candles':return None
    data=message.get('data',{})
    if not isinstance(data,dict):return None
    code=str(data.get('symbol',''))
    if code not in symbols or not re.fullmatch(r'[1-9][0-9]{3}',code):return None
    try:
        stamp=dt.datetime.fromisoformat(str(data['date']).replace('Z','+00:00'))
        if stamp.tzinfo is None:return None
        values=[float(data[k]) for k in ['open','high','low','close','volume']]
        o,h,l,c,v=values
        if not all(math.isfinite(x) for x in values) or not 0<l<=min(o,c)<=max(o,c)<=h or v<0:return None
        if stamp.timestamp()>time.time()+120:return None
    except (KeyError,ValueError,TypeError):return None
    return {'code':code,'date':stamp.isoformat(),'open':o,'high':h,'low':l,'close':c,
            'volume_shares':int(v*1000),'timeframe':'1','final':False,
            'notice':'Minute candle updates may be unfinished; not a daily trading signal.'}

class Feed:
    def __init__(self,symbols):
        self.symbols=set(symbols);self.lock=threading.Lock();self.connected=False;self.quotes={}
    def message(self,ws,raw):
        try:message=json.loads(raw)
        except (ValueError,TypeError):return
        if not isinstance(message,dict):return
        if message.get('event')=='authenticated':
            with self.lock:self.connected=True
            ws.send(json.dumps({'event':'subscribe','data':{'channel':'candles','symbols':sorted(self.symbols)}}))
        elif message.get('event')=='error':
            # Provider text is deliberately not logged: authentication errors may contain secrets.
            with self.lock:self.connected=False
        else:
            q=normalize(message,self.symbols)
            if q:
                with self.lock:
                    previous=self.quotes.get(q['code'])
                    if previous and dt.datetime.fromisoformat(previous['date'])>dt.datetime.fromisoformat(q['date']):return
                    self.quotes[q['code']]=q
    def snapshot(self):
        with self.lock:
            return {'connected':self.connected,'provider':'Fugle','quotes':list(self.quotes.values()),
                    'display_refresh_seconds':5,'strategy_timeframe':'D','live_signals_enabled':False}

def main():
    key=os.environ.get('FUGLE_API_KEY','')
    access=os.environ.get('LIVE_ACCESS_TOKEN','')
    symbols=os.environ.get('FUGLE_SYMBOLS','2330').split(',')
    symbols=[x.strip() for x in symbols]
    if not key:raise SystemExit('FUGLE_API_KEY is missing. No live connection was started.')
    if len(access)<32:raise SystemExit('Set a separate LIVE_ACCESS_TOKEN of at least 32 characters; never use your provider key.')
    if not symbols or any(not re.fullmatch(r'[1-9][0-9]{3}',x) or x.startswith('91') for x in symbols):
        raise SystemExit('FUGLE_SYMBOLS must contain ordinary-share codes; respect your subscription limit.')
    try:import websocket
    except ImportError:raise SystemExit('Install requirements-live.txt before running this optional gateway.')
    feed=Feed(symbols)
    def opening(ws):
        with feed.lock:feed.connected=False
        ws.send(json.dumps({'event':'auth','data':{'apikey':key}}))
    def closing(ws,*args):
        with feed.lock:feed.connected=False
    def worker():
        while True:
            app=websocket.WebSocketApp(ENDPOINT,on_open=opening,on_message=feed.message,
                on_close=closing,on_error=closing)
            app.run_forever(ping_interval=20,ping_timeout=10)
            closing(app);time.sleep(10)
    threading.Thread(target=worker,daemon=True).start()
    allowed=os.environ.get('LIVE_ALLOWED_ORIGIN','https://lin19981203.github.io')
    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self):
            if self.headers.get('Origin')!=allowed:self.send_error(403);return
            self.send_response(204)
            self.send_header('Access-Control-Allow-Origin',allowed)
            self.send_header('Access-Control-Allow-Methods','GET, OPTIONS')
            self.send_header('Access-Control-Allow-Headers','Authorization')
            self.send_header('Vary','Origin');self.end_headers()
        def do_GET(self):
            origin=self.headers.get('Origin')
            if origin and origin!=allowed:self.send_error(403);return
            if not authorized(self.headers.get('Authorization'),access):
                self.send_error(401);return
            if self.path!='/live-snapshot':self.send_error(404);return
            body=json.dumps(feed.snapshot(),allow_nan=False).encode()
            self.send_response(200)
            if origin:
                self.send_header('Access-Control-Allow-Origin',allowed)
                self.send_header('Access-Control-Allow-Credentials','true')
                self.send_header('Vary','Origin')
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    print('Private quote relay listening on loopback. Requires authenticated HTTPS proxy for mobile access.',flush=True)
    ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('LIVE_PORT','8787'))),Handler).serve_forever()

if __name__=='__main__':main()
