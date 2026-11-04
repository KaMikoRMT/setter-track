# CLAUDE.md

這個 repo 做「舉球軌跡分析」：從錄影找出每一顆舉球、重建 3D 軌跡、算出舉球指標、讓教練覆盤。

## 開工前必讀

1. `docs/ARCHITECTURE.md`：完整規格。**第 12 節「容易誤解的地方」一定要先讀。**
2. `docs/PROGRESS.md`：目前做到哪裡。每次開工先看，收工前更新。

## 工作方式

- 依 `docs/ARCHITECTURE.md` 第 10 節的階段依序做；一個階段通過驗收才進下一個。
- 每個階段完成：
  1. `node tests/selftest.mjs` 全部通過；動到 `detector/` 就跑 `python3 detector/tests/test_synthetic.py`。
  2. 有無頭瀏覽器就實測 1280×800、390×844；沒有就在 `docs/PROGRESS.md` 列出沒實測的畫面項目。
  3. 更新 `docs/PROGRESS.md`（完成項目、未完成項目、判斷紀錄）。
  4. commit，訊息開頭標階段，例如 `P2: calibration UI`。
- 規格沒寫清楚時：選最簡單的做法，記進 `docs/PROGRESS.md` 的「判斷紀錄」，繼續做，不要停下來等。
- 不要新增規格沒有的功能。

## 硬性限制

- 網頁工具是 `app/index.html` 單一檔案，用瀏覽器直接打開就能跑（`file://` 也要能用）。原生 JavaScript，不要框架、npm 套件、打包工具、外部函式庫。
- 影片只在本機讀，絕不上傳。
- 所有 3D／相機計算只在網頁工具（`@core` 區塊）裡；Python 只輸出像素座標，不重複實作幾何。
- 純邏輯放在 `/* @core-begin */` 與 `/* @core-end */` 之間，不碰 DOM 和 window，讓 `tests/selftest.mjs` 能在 Node 跑。
- 不要用 `alert`／`confirm`／`prompt`；用頁內確認。
- 介面文字繁體中文（台灣用語）；程式碼識別字用英文。
- 使用者輸入的文字放進 HTML 前一律跳脫（`esc()`）。
- `detector/` 只用 Python 3、OpenCV、numpy；ultralytics 只有訓練與 `--model` 路徑才需要，延遲 import。
- 不要把影片、截圖、別人的素材 commit 進 repo。
