# ChanQuant V6.1 台股市場掃描

手機網址：https://lin19981203.github.io/chanquant-v6/

官方上市／上櫃普通股盤後日K掃描，無金鑰、無自動下單。

GitHub Actions 每週一至五台灣時間17:10與18:10執行；排程可能延遲。可在 Actions 的「Scan Taiwan market and deploy」按 Run workflow 手動更新。

`scanner.py` 使用 Python 標準函式庫下載兩市場每日資料，初次回補120個日曆天，之後跳過已完成日期；失敗日期自動重試。`history.json`保留最近180筆日K。以每個市場最新可得交易日掃描，停牌或缺最新成交的股票不產生候選。

範圍：四位數、不以0開頭的上市／上櫃普通股，排除ETF、權證、TDR、特別股與興櫃。至少60筆有效日K，股價≥10元、量≥500張、成交額≥2千萬元。

以包含合併、已確認分型、至少相距4根處理後K線的交替分型與三筆重疊構造簡化中樞。候選包括中樞突破、守穩中樞上緣後回升，以及獨立的20日新高趨勢觀察。詳見網頁規則。不是完整正統纏論，沒有線段、背馳或週／60分鐘共振。分型會隨後續行情確認或修訂，不應將當前掃描結果用作歷史無前視回測。

未還原權息，除權息、減資、分割可能產生假訊號。評分不是勝率。V6.0內建台積電回測是獨立的歷史紀錄，本次未重新驗證其績效。

```sh
python -m unittest -v test_scanner.py
python scanner.py --days 120
```

資料來源：
- https://www.twse.com.tw/zh/trading/historical/mi-index.html
- https://www.tpex.org.tw/zh-tw/mainboard/trading/info/pricing.html

更新失敗時請核對頁面資料日期與 Actions 記錄。前端的更新按鈕只下載已發布結果，不會觸發伺服器掃描。
