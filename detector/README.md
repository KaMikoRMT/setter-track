# detector：自動找出影片裡的球

網頁工具（`app/index.html`）可以全部手動標記。這裡的 Python 程式是讓電腦先把球找出來，網頁工具再用物理條件挑出哪些是舉球。

## 安裝

```bash
pip install -r detector/requirements.txt
```

訓練與 `--model` 才需要 ultralytics（會一起裝 PyTorch，檔案很大）：

```bash
pip install ultralytics
```

## 1. 不用訓練：基準版

```bash
python3 detector/detect.py 影片.mp4 -o detections.json
```

常用選項：

- `--start 60 --end 180`：只處理第 60～180 秒。
- `--color yellow`：黃色的球（Mikasa 黃藍球）加分。
- `--debug debug.mp4`：另外輸出一支標出候選（紅圈）與軌跡（綠線）的影片，用來看哪裡找錯了。
- `--thr 25`：畫面雜訊多（光線暗、壓縮嚴重）就把差分門檻調高。
- `--max-width 1280`：球很小（遠端、4K 縮小後只剩幾個像素）就調大，會比較慢。

接著在網頁工具：先完成「① 場地校正」→ 專案 → **匯入自動偵測結果** → 「② 標記舉球」最下面會列出像舉球的段，按「加入」或「全部加入像舉球的」。

基準版的限制：球被人擋住、跟人重疊、在人前面飛過時常常斷掉；人揮手、跳起來的動作也會被當成候選（網頁工具會用物理條件濾掉大部分）。

## 2. 用自己的影片訓練 YOLO

1. 在網頁工具標記 30～50 顆舉球（大約 300～500 個球的位置），涵蓋近端、遠端、高球、快攻。
2. 專案 → **匯出訓練標註**，得到 `影片-labels.json`。
3. 轉成 YOLO 資料集（多支影片就兩兩一組接下去）：

   ```bash
   python3 detector/make_dataset.py 影片.mp4 影片-labels.json -o datasets/ball
   ```

4. 訓練（建議有 GPU 的電腦或 Google Colab；`--device 0` 用第一張 GPU）：

   ```bash
   python3 detector/train.py datasets/ball/data.yaml --epochs 100
   ```

5. 用訓練好的模型偵測，之後步驟跟基準版一樣：

   ```bash
   python3 detector/detect.py 影片.mp4 --model runs/detect/ball/weights/best.pt -o detections.json
   ```

`make_dataset.py` 在球附近切 640×640 的小圖（不縮放），所以 `detect.py --model` 預設用影片原解析度偵測，球的大小才跟訓練時一致。

注意：

- **標什麼就學會什麼**。訓練標註只來自網頁工具裡標記的舉球，所以模型很會找「舉球時的球」，接球、扣球比較差（合成影片實測：舉球每一格都找到，扣球只找回一部分）。對這個工具的目的沒有影響。
- 近端、遠端、高球、快攻、背傳、對方的舉球都要有，模型才不會只認得某一種。
- CPU 偵測 1280×720 大約每秒 10 格，一整場比賽建議用 GPU；或用 `--start/--end` 只跑需要的片段。
- 檢查訓練好的模型：`python3 detector/tests/test_synthetic.py <合成影片資料夾> --model best.pt`。

## 測試

```bash
node tests/make-synthetic.mjs /tmp/syn
```

```bash
python3 detector/tests/test_synthetic.py /tmp/syn
```

```bash
node tests/ui-check.mjs /tmp/syn
```

```bash
python3 detector/tests/test_dataset.py /tmp/syn
```

`ui-check.mjs` 會用 `test_synthetic.py` 產生的 `detections.json` 測匯入，並匯出 `labels.json` 給 `test_dataset.py`，所以要照這個順序跑。
