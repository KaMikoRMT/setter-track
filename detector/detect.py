#!/usr/bin/env python3
"""舉球軌跡：自動找出影片裡的球（docs/ARCHITECTURE.md 第 9 節）。

基準版不用訓練：
  1. 三格差分：|f(t) − f(t−k)| 與 |f(t+k) − f(t)| 都很大的地方 = 「這一格才在這裡」的東西（快速移動的小物體）。
  2. 面積、長寬比、填滿率過濾成「像球」的候選；用背景模型的前景把中心點修正到整顆球的中心。
  3. 追蹤：用最近幾點做二次預測，在預測位置附近找候選，最多容許連續幾格沒找到。
輸出每條連續追到的軌跡（時間＋像素座標）。切成一段段拋物線、算 3D 都在網頁工具做。

有訓練好的 YOLO 模型時用 --model best.pt（要另外 pip install ultralytics），追蹤不變。

用法：
  python3 detector/detect.py 影片.mp4 -o detections.json
  python3 detector/detect.py 影片.mp4 -o detections.json --start 60 --end 180 --debug debug.mp4
"""
import argparse
import json
import math
import os
import sys
from collections import deque

import cv2
import numpy as np

APP = "setter-track-detector"
VERSION = 1


def default_params():
    return {
        "max_width": 960,      # 處理時縮到這個寬度（輸出座標會換回原影片像素）
        "gap": 0,              # 三格差分的間隔（格）；0 = 依 fps 自動（約 1/20 秒）
        "thr": 18,             # 差分門檻（灰階）
        "min_area": 3,         # 候選面積下限（處理尺寸的像素）
        "max_area": 0.0015,    # 候選面積上限（佔畫面比例）
        "max_aspect": 3.0,     # 長寬比上限（動態模糊會拉長）
        "min_fill": 0.35,      # 填滿率下限
        "color": "none",       # "yellow"：黃色的球加分（Mikasa 黃藍球）
        "max_gap": 4,          # 追蹤最多容許連續幾格沒找到
        "min_track": 8,        # 軌跡至少幾點才輸出
        "min_speed": 1.2,      # 軌跡每 5 點的淨移動速度中位數下限（每格幾像素，以 1280 寬為準，會依畫面寬縮放）
        "min_dense": 0.7,      # 軌跡涵蓋的格數裡，至少要有這個比例真的找到球（人身上的雜訊常常斷斷續續）
        "min_extent": 0.02,    # 軌跡範圍至少佔畫面寬的比例
        "gate_init": 0.05,     # 只有一點時，下一點的搜尋半徑（佔畫面寬比例）
        "gate_pred": 0.012,    # 有預測時的搜尋半徑
        "gate_grow": 0.006,    # 每漏一格，半徑增加多少
        "conf": 0.25,          # YOLO 信心門檻
    }


# ------------------------------------------------------------------
# 候選
# ------------------------------------------------------------------
def classic_candidates(g_prev, g_cur, g_next, fg, frame_small, P):
    """回傳 [(x, y, area, score)]，座標是處理尺寸。"""
    d1 = cv2.absdiff(g_cur, g_prev)
    d2 = cv2.absdiff(g_next, g_cur)
    motion = cv2.min(d1, d2)
    _, m = cv2.threshold(motion, P["thr"], 255, cv2.THRESH_BINARY)
    m = cv2.dilate(m, np.ones((2, 2), np.uint8))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(m, connectivity=8)
    H, W = m.shape
    amax = P["max_area"] * W * H
    out = []
    hsv = None
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < P["min_area"] or area > amax:
            continue
        if max(w, h) / max(1, min(w, h)) > P["max_aspect"]:
            continue
        if area / float(w * h) < P["min_fill"]:
            continue
        cx, cy = cents[i]
        # 用背景模型的前景修正中心（差分只看到「新出現」的部分，球慢的時候會是月牙形）
        if fg is not None:
            pad = max(2, int(0.5 * max(w, h)))
            x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + h + pad)
            sub = fg[y0:y1, x0:x1]
            ys, xs = np.nonzero(sub > 0)
            if len(xs) >= area * 0.8 and len(xs) <= area * 6:
                cx, cy = x0 + xs.mean(), y0 + ys.mean()
        score = area / float(w * h)
        if P["color"] == "yellow":
            if hsv is None:
                hsv = cv2.cvtColor(frame_small, cv2.COLOR_BGR2HSV)
            px = hsv[int(round(min(H - 1, cy))), int(round(min(W - 1, cx)))]
            if 15 <= px[0] <= 40 and px[1] > 80 and px[2] > 100:
                score += 0.5
        out.append((float(cx), float(cy), float(area), float(score)))
    return out


def yolo_candidates(model, frame, conf, imgsz):
    res = model.predict(frame, conf=conf, imgsz=imgsz, verbose=False)[0]
    names = res.names if hasattr(res, "names") else {}
    ball_ids = [k for k, v in names.items() if str(v).lower() in ("ball", "volleyball", "sports ball")] or [0]
    out = []
    for b in res.boxes:
        if int(b.cls) not in ball_ids:
            continue
        x0, y0, x1, y1 = [float(v) for v in b.xyxy[0]]
        out.append(((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * (y1 - y0), float(b.conf)))
    return out


# ------------------------------------------------------------------
# 追蹤
# ------------------------------------------------------------------
class Track:
    __slots__ = ("id", "pts", "last")

    def __init__(self, tid, f, x, y):
        self.id = tid
        self.pts = [(f, x, y)]
        self.last = f

    def predict(self, f):
        pts = self.pts[-6:]
        if len(pts) >= 3:
            fs = np.array([p[0] for p in pts], float)
            xs = np.array([p[1] for p in pts], float)
            ys = np.array([p[2] for p in pts], float)
            deg = 2 if len(pts) >= 4 else 1
            return float(np.polyval(np.polyfit(fs, xs, deg), f)), float(np.polyval(np.polyfit(fs, ys, deg), f))
        if len(pts) == 2:
            (f0, x0, y0), (f1, x1, y1) = pts
            k = (f - f1) / float(f1 - f0)
            return x1 + (x1 - x0) * k, y1 + (y1 - y0) * k
        return pts[0][1], pts[0][2]


def associate(tracks, cands, f, W, P, next_id):
    """把這一格的候選接到現有軌跡上；回傳新開的軌跡與下一個 id。"""
    pairs = []
    for ti, tr in enumerate(tracks):
        px, py = tr.predict(f)
        miss = f - tr.last - 1
        if len(tr.pts) >= 3:
            gate = (P["gate_pred"] + P["gate_grow"] * miss) * W
        elif len(tr.pts) == 2:
            gate = (2 * P["gate_pred"] + P["gate_grow"] * miss) * W
        else:
            gate = P["gate_init"] * W
        for ci, (x, y, _a, sc) in enumerate(cands):
            d = math.hypot(x - px, y - py)
            if d <= gate:
                pairs.append((d / gate - 0.2 * sc - 0.05 * min(len(tr.pts), 10), ti, ci))
    pairs.sort()
    used_t, used_c = set(), set()
    for _cost, ti, ci in pairs:
        if ti in used_t or ci in used_c:
            continue
        used_t.add(ti)
        used_c.add(ci)
        x, y = cands[ci][0], cands[ci][1]
        tracks[ti].pts.append((f, x, y))
        tracks[ti].last = f
    new = []
    for ci, c in enumerate(cands):
        if ci not in used_c:
            new.append(Track(next_id, f, c[0], c[1]))
            next_id += 1
    return new, next_id


def keep_track(tr, P, W):
    """球在空中是連續、穩定移動的；人身上的雜訊通常斷斷續續、在原地抖動。"""
    n = len(tr.pts)
    if n < P["min_track"]:
        return False
    span = tr.pts[-1][0] - tr.pts[0][0]
    if span <= 0 or n / float(span + 1) < P["min_dense"]:
        return False
    xs = [p[1] for p in tr.pts]
    ys = [p[2] for p in tr.pts]
    if max(max(xs) - min(xs), max(ys) - min(ys)) < P["min_extent"] * W:
        return False
    w = 5 if n > 5 else n - 1
    speeds = sorted(math.hypot(tr.pts[i + w][1] - tr.pts[i][1], tr.pts[i + w][2] - tr.pts[i][2]) / float(tr.pts[i + w][0] - tr.pts[i][0])
                    for i in range(n - w))
    return speeds[len(speeds) // 2] >= P["min_speed"] * W / 1280.0


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------
def run(video, start=0.0, end=None, params=None, model_path=None, debug_path=None, progress=True, imgsz=None):
    P = default_params()
    P.update(params or {})
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise SystemExit(f"打不開影片：{video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H0 = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    f_start = int(round(start * fps))
    f_end = nframes if end is None else min(nframes or 10 ** 9, int(round(end * fps)))
    if f_start:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_start)
    scale = min(1.0, P["max_width"] / float(W0))
    ws, hs = int(round(W0 * scale)), int(round(H0 * scale))
    k = P["gap"] or max(1, int(round(fps / 20.0)))

    model = None
    if model_path:
        try:
            from ultralytics import YOLO  # 延遲 import：基準版不需要
        except ImportError:
            raise SystemExit("用 --model 需要先 pip install ultralytics")
        model = YOLO(model_path)
        # 訓練用的是不縮放的小圖（make_dataset.py），偵測時也用原解析度，球的大小才一致
        imgsz = imgsz or int(math.ceil(W0 / 32.0) * 32)

    mog = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=16, detectShadows=False)
    dbg = None
    if debug_path:
        dbg = cv2.VideoWriter(debug_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (ws, hs))

    buf = deque()  # (frame_index, small_bgr, gray, fg)
    active, done, next_id = [], [], 0
    n_cands = 0
    f = f_start
    total = max(1, f_end - f_start)

    def process(fi, small, cands):
        nonlocal active, next_id, n_cands
        n_cands += len(cands)
        new, next_id = associate(active, cands, fi, W0, P, next_id)
        still = []
        for tr in active:
            if fi - tr.last > P["max_gap"]:
                if keep_track(tr, P, W0):
                    done.append(tr)
            else:
                still.append(tr)
        active = still + new
        if dbg is not None:
            vis = small.copy()
            for x, y, _a, _s in cands:
                cv2.circle(vis, (int(x * scale), int(y * scale)), 6, (0, 0, 255), 1)
            for tr in active:
                if len(tr.pts) >= 3:
                    pts = np.array([[p[1] * scale, p[2] * scale] for p in tr.pts[-30:]], np.int32)
                    cv2.polylines(vis, [pts], False, (0, 255, 0), 2)
            dbg.write(vis)

    while f < f_end:
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, (ws, hs), interpolation=cv2.INTER_AREA) if scale < 1 else frame
        if model is not None:
            process(f, small, yolo_candidates(model, frame, P["conf"], imgsz))
        else:
            g = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (3, 3), 0)
            buf.append((f, small, g, mog.apply(small)))
            if len(buf) > 2 * k + 1:
                buf.popleft()
            if len(buf) == 2 * k + 1:
                fi, sm, gc, fg = buf[k]
                c = classic_candidates(buf[0][2], gc, buf[-1][2], fg, sm, P)
                process(fi, sm, [(x / scale, y / scale, a / (scale * scale), sc) for x, y, a, sc in c])
        f += 1
        if progress and (f - f_start) % 600 == 0:
            print(f"  {100.0 * (f - f_start) / total:5.1f}%  已處理 {f - f_start} 格", file=sys.stderr)
    cap.release()
    if dbg is not None:
        dbg.release()
    for tr in active:
        if keep_track(tr, P, W0):
            done.append(tr)
    done.sort(key=lambda tr: tr.pts[0][0])
    tracks = []
    for i, tr in enumerate(done):
        tracks.append({
            "id": i + 1,
            # 時間取這一格的中間（跟網頁工具逐格跳轉的位置一樣），換回格數用 floor(t × fps)
            "points": [{"t": round((fi + 0.5) / fps, 6), "u": round(x, 2), "v": round(y, 2)} for fi, x, y in tr.pts],
        })
    processed = f - f_start
    return {
        "app": APP,
        "version": VERSION,
        "video": {"name": os.path.basename(video), "w": W0, "h": H0, "fps": fps, "frames": nframes},
        "range": {"start": f_start / fps, "end": f / fps},
        "method": "yolo" if model is not None else "classic",
        "params": P,
        "stats": {"frames": processed, "candidates_per_frame": round(n_cands / max(1, processed), 2), "tracks": len(tracks)},
        "tracks": tracks,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="自動找出影片裡的球，輸出給舉球軌跡網頁工具匯入。")
    ap.add_argument("video", help="影片檔")
    ap.add_argument("-o", "--output", default="detections.json", help="輸出 JSON（預設 detections.json）")
    ap.add_argument("--start", type=float, default=0.0, help="從第幾秒開始")
    ap.add_argument("--end", type=float, default=None, help="到第幾秒結束")
    ap.add_argument("--model", default=None, help="YOLO 模型（best.pt）；不給就用不需要訓練的基準方法")
    ap.add_argument("--color", choices=["none", "yellow"], default="none", help="yellow：黃色的球加分")
    ap.add_argument("--thr", type=int, default=None, help="差分門檻（預設 18；畫面雜訊多就調高）")
    ap.add_argument("--max-width", type=int, default=None, help="處理時的寬度（預設 960；球很小就調大）")
    ap.add_argument("--imgsz", type=int, default=None, help="YOLO 偵測時的影像大小（預設 = 影片寬度）")
    ap.add_argument("--debug", default=None, help="另外輸出一支標出候選與軌跡的影片")
    a = ap.parse_args(argv)
    params = {"color": a.color}
    if a.thr is not None:
        params["thr"] = a.thr
    if a.max_width is not None:
        params["max_width"] = a.max_width
    out = run(a.video, a.start, a.end, params, a.model, a.debug, imgsz=a.imgsz)
    with open(a.output, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    s = out["stats"]
    print(f"完成：{s['frames']} 格、平均每格 {s['candidates_per_frame']} 個候選、{s['tracks']} 條軌跡 → {a.output}")


if __name__ == "__main__":
    main()
