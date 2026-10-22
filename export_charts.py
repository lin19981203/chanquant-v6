"""Lazy-loaded per-symbol year charts, so phones don't download the entire market."""
import argparse
import datetime as dt
import json
from pathlib import Path
import scanner
import chan_points

def export(history, destination):
    for market,state in history['markets'].items():
        folder=destination/'charts'/market;folder.mkdir(parents=True,exist_ok=True)
        end=max(b[0] for stock in state['stocks'].values() for b in stock['bars'])
        cutoff=(dt.date.fromisoformat(end)-dt.timedelta(days=364)).isoformat()
        for code,stock in state['stocks'].items():
            if not scanner.common_stock(code,stock['name']):continue
            bars=[b for b in stock['bars'] if cutoff<=b[0]<=end]
            if not bars:continue
            scanner.atomic_json(folder/(code+'.json'),{'code':code,'name':stock['name'],
                'market':market,'timeframe':'D','adjusted':False,'bars':bars,
                'points':[p for p in chan_points.analyse(stock['bars']).events if cutoff<=p['confirmed_date']<=end],
                'requested_start':cutoff,'end':end,'available_start':bars[0][0]})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--history',type=Path,default=Path('history.json'))
    p.add_argument('--destination',type=Path,default=Path('public'));a=p.parse_args()
    export(json.loads(a.history.read_text()),a.destination)
