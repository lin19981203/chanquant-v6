"""Resumable official full-market year + warm-up download. No synthetic prices."""
import argparse
import datetime as dt
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import scanner

ROOT = Path(__file__).resolve().parent

def build(start, end, warmup=112, workers=4):
    cache = ROOT / 'backtest_daily_cache'
    cache.mkdir(exist_ok=True)
    base = ROOT / 'backtest_history.json'
    if not base.exists():base=ROOT/'history.json'
    history = json.loads(base.read_text()) if base.exists() else {'markets': {}}
    first = start - dt.timedelta(days=warmup)
    days = [first + dt.timedelta(days=i) for i in range((end-first).days+1)
            if (first + dt.timedelta(days=i)).weekday() < 5]
    jobs = [(m,d) for m in scanner.SOURCES for d in days]
    def query(job):
        m,d = job
        path = cache / f'{m}_{d}.json'
        state = history['markets'].get(m, {})
        if path.exists():
            return m,d,json.loads(path.read_text())
        if d.isoformat() in state.get('fetched', []):
            return m,d,None
        rows = scanner.fetch_day(m,d)
        scanner.atomic_json(path,rows)
        time.sleep(1.1)
        return m,d,rows
    errors = []
    with ThreadPoolExecutor(workers) as pool:
        pending = {pool.submit(query,j):j for j in jobs}
        for n, f in enumerate(as_completed(pending),1):
            try:
                m,d,rows = f.result()
                state = history['markets'].setdefault(m, {'stocks': {}, 'fetched': []})
                for code,name,bar in rows or []:
                    s = state['stocks'].setdefault(code, {'name':name,'market':m,'bars':[]})
                    by_date = {b[0]:b for b in s['bars']}; by_date[bar[0]] = bar
                    s['bars'] = sorted(by_date.values(),key=lambda b:b[0])
                state['fetched'] = sorted(set(state.get('fetched',[])) | {d.isoformat()})
            except Exception as exc:
                m,d = pending[f]
                errors.append({'market':m,'date':str(d),'error':str(exc)[:180]})
                print('ERROR',m,d,str(exc)[:180],flush=True)
            if n % 20 == 0:
                print('PROGRESS',n,'/',len(jobs),'errors',len(errors),flush=True)
                scanner.atomic_json(ROOT/'history_year.json',history)
    # Preserve latest names from the existing snapshot, rather than overwriting with old names.
    history['_backtest_provenance'] = {
        'requested_start':str(start),'requested_end':str(end),'warmup_start':str(first),
        'expected_queries':len(jobs),'successful_queries':len(jobs)-len(errors),
        'unresolved_queries':errors,'source_snapshot_sha256':hashlib.sha256(base.read_bytes()).hexdigest() if base.exists() else None,
        'official_sources':scanner.SOURCES,
        'warning':'Unadjusted prices; no complete delisting/corporate-action master.'}
    scanner.atomic_json(ROOT/'history_year.json',history)
    print('COMPLETE',len(jobs),'unresolved',len(errors),flush=True)
    if errors:
        raise SystemExit(1)

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--start',type=dt.date.fromisoformat,default=dt.date(2025,10,22))
    p.add_argument('--end',type=dt.date.fromisoformat,default=dt.date(2026,10,21))
    a=p.parse_args();build(a.start,a.end)
