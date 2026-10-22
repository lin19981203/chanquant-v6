# ChanQuant V6.2｜五千萬元・買賣點參考

這是接續 V6.1 的更新包。包含完整來源、年度行情、日K掃描、各組回測、逐股懶載入圖表與可選即時行情後端。正式網站是否已更新，請以頁面版本及 GitHub Actions 成功部署紀錄為準；本更新包不代表已發布到 GitHub Pages。

## 已變更

- **模擬本金 NT$50,000,000**。每檔最多淨值10%、最多10檔、每筆風險0.5%、整張且前一日成交股數1%；不能把舊版損益直接乘50。
- 以簡化一／二／三類買點參考進場，新確認一／二／三類賣點參考出場；不使用固定2R、MA20或20日時間出場。
- 停損設在已確認買點結構低點下一有效跳動單位。後續二／三類買點可提高停損，不能降低；在確認日收盤後形成、次日生效。
- 行情保存420根日K；查詢最近365個日曆天另加112天暖機。股票上市不足一年、停牌、缺價時會有較少K線。
- 手機選股不一次載入全市場歷史；點選個股才下載其近一年K線。
- 圖表支援日K、週K、月K；後兩者為日K聚合。**策略計算仍只有日K**，尚無5／15／60分鐘多級別確認。
- 即時行情介面與唯讀Fugle串流轉接程式已準備；**未接入金鑰、未部署私人後端、未驗證供應商實際連線**。畫面每5秒讀取後端快照，不能稱逐筆無延遲串流。

## 簡化買賣點的精確條件

見 `RULES_V62.md`、`chan_points.py` 及網頁「完整掃描與交易規則」。這是日K筆級代理，沒有遞迴次級別走勢／線段，不等同完整正統纏論。一類的MACD面積減弱只是背馳代理，參數事前固定，未依本次績效搜尋。

端點日期與訊號確認日期分開記錄。右側合併K封閉後才確認分型，訊號不回填到歷史端點；買入在確認日後的下一交易日開盤。賣點即使出現在成本以下也出場，不保證停利。

## 執行

Python 3.12建議；盤後掃描、圖表匯出、回測只用標準函式庫。

```sh
python -m unittest -v test_scanner.py test_backtest_market.py test_chan_points.py test_live_gateway.py test_year_data.py
python scanner.py --days 477
python backtest_chan.py --history history.json --start 2025-10-22 --end 2026-10-21 --capital 50000000
```

`backtest_market.py`的命令列也會轉到V6.2；舊版帳本函式保留供成本工具與回歸測試使用。每日掃描只更新候選，回測報告是指定區間的獨立快照，不會因刷新手機自動重算。

只用已下載資料重算掃描：

```sh
python scanner.py --offline --as-of 2026-10-21
```

## 手機讀取與恢復

掃描的手動更新、回到前景及定時更新共用一個進行中的下載，避免重複消耗流量；網路恢復會重新讀取。掃描與逐股K線超過20秒會結束等待並顯示重試提示。掃描版本不符或更新失敗時保留上次有效結果及原行情日期。

切換股票會取消前一請求、立即清除舊圖，避免新股票標題搭配上一檔K線。離開頁面取消讀圖。即時介面拒絕非正價格、無效時間與超前目前時間超過5秒的資料；仍需私人行情後端才有真實盤中行情。

## GitHub Pages 部署

把更新包中的來源檔、行情及 `.github/workflows/v62.yml` 合併至既有 `lin19981203/chanquant-v6` 儲存庫的 `main`。**保留 workflows 目錄結構**，不可把workflow扁平上傳到根目錄。Pages來源選GitHub Actions。

工作流程會執行測試、更新官方盤後資料、保存history/scan_results，並只把公開前端檔與逐股圖表打包部署；`live_gateway.py`及行情金鑰不進Pages公開網站。

台灣時間平日17:10、18:10排程，GitHub可能延遲。首次年度回補需較久；`history_year.py`可逐日快取續傳，有任何未解決查詢時，完整年度回測拒絕執行，避免把不完整資料當作全年度。

本機檢視公開網站：

```sh
python export_charts.py --history history.json --destination public
python -m http.server 8000 --directory public
```

不要直接用手機「檔案」打開`index.html`當作已部署網站；瀏覽器對本機檔案讀取JSON有限制。`public`檔案夾是可部署的靜態網站。

## 即時行情（尚未啟用）

Fugle官方支援WebSocket分鐘K與歷史分K。需要你自己的行情服務權限及金鑰，訂閱數／可用歷史依方案而定。**不要把金鑰貼在聊天、HTML或公開GitHub。**

1. 在你控制的私人伺服器安裝`requirements-live.txt`。
2. 在伺服器環境設定`FUGLE_API_KEY`、`FUGLE_SYMBOLS`（如2330,2317）；另設定至少32字元、與行情金鑰不同的`LIVE_ACCESS_TOKEN`，再啟動`python live_gateway.py`。
3. 程式只綁127.0.0.1。手機使用需在前方部署HTTPS反向代理，保留Authorization標頭；轉接程式驗證獨立存取憑證，無需第三方Cookie。不要把loopback relay直接當公開無驗證報價服務。
4. 在網頁「資料」輸入你自己的HTTPS `/live-snapshot` 位址，輸入私人服務的存取憑證，再按連接。憑證僅存在這次開啟的網頁記憶體，不寫入檔案或localStorage；Provider金鑰不經前端。程式只在設定後連線，不會預設傳送請求給未知服務。

即時分鐘K可能未完成。它與官方盤後日K分開，**不覆寫日K、不驅動本次回測、不自動下單**。若要盤中買賣點，需先取得足夠已完成分鐘K與次級別歷史，再另行驗證。

官方參考：
- https://developer.fugle.tw/docs/data/websocket-api/getting-started/
- https://developer.fugle.tw/docs/data/websocket-api/market-data-channels/candles/
- https://developer.fugle.tw/docs/data/http-api/historical/candles/

## 研究限制

未還原權息、現金股息／公司行動與完整下市主檔未納入；仍可能有存活者偏誤。無逐筆委託簿，日K一價K保守假設無法成交；缺價不補造，部位保留最後估值並揭露日期。未完全模擬T+2交割限制。費用是假設：每邊0.1425%、最低20元、賣出稅0.3%、每邊滑價0.1%。最大回撤為日終值，未平倉不算勝率分母；帳戶淨值含未平倉估值並預扣估計賣出費用。

單一年結果與單一套工程參數不證明長期有效，尚無獨立樣本外驗證。
