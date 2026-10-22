import json,os,time,urllib.request
base=os.environ['SITE_URL'].rstrip('/')+'/'
for attempt in range(12):
    try:
        def read( ame):
            return urllib.request.urlopen(base+name+'?verify='+os.environ['GITHUB_RUN_ID'],timeout=20).read()
        assert '6.2' in read('index.html').decode()
        assert json.loads(read('scan_results.json'))['version']=='6.2'
 d=json.loads(read('backtest_results.json'))
        assert d['version']=='6.2-chan-reference' and d['config']['capital']==50000000
        assert read('app.js') and read('app.css')
        print('Published V6.2, current scan, assets and fifty-million replay verified');break
    except Exception as error:
        if attempt==11:raise
        print('Waiting for Pages:',repr(error),flush=True);time.sleep(5)
