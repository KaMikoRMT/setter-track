#!/usr/bin/env python3
"""檢查 make_dataset.py：用合成影片＋網頁工具匯出的 labels.json（tests/ui-check.mjs 產生）。

用法：python3 detector/tests/test_dataset.py <合成影片資料夾>
"""
import glob
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import make_dataset  # noqa: E402


def main():
    syn = sys.argv[1]
    labels = os.path.join(syn, "labels.json")
    if not os.path.exists(labels):
        raise SystemExit("找不到 labels.json：先跑 node tests/ui-check.mjs " + syn)
    L = json.load(open(labels, encoding="utf-8"))
    out = os.path.join(syn, "dataset")
    st = make_dataset.build([(os.path.join(syn, "synthetic.mp4"), labels)], out, crop=640)
    failed = 0

    def check(cond, msg):
        nonlocal failed
        print(("  ✓ " if cond else "  ✗ ") + msg)
        if not cond:
            failed += 1

    check(st["images"] == len({make_dataset.frame_index(l["t"], 60) for l in L["labels"]}), f"每個有標註的格一張圖（{st['images']} 張）")
    check(st["val"] > 0 and st["train"] > 0, f"訓練 {st['train']}、驗證 {st['val']}")
    # 1. 標註跟答案對得上（格數換算正確）：每個標註點的那一格，真正的球就在附近
    truth = json.load(open(os.path.join(syn, "truth.json"), encoding="utf-8"))
    by_frame = {b["frame"]: b for b in truth["ballPx"]}
    near = 0
    for lab in L["labels"]:
        b = by_frame.get(make_dataset.frame_index(lab["t"], truth["video"]["fps"]))
        if b and np.hypot(b["u"] - lab["u"], b["v"] - lab["v"]) <= max(3.0, b["r"]):
            near += 1
    check(near >= 0.95 * len(L["labels"]), f"標註點對得上那一格的球（{near}/{len(L['labels'])}）")
    # 2. 切出來的小圖裡，框住的地方真的有球（合成影片的球是黃色）
    imgs = sorted(glob.glob(os.path.join(out, "images", "*", "*.jpg")))
    inside = 0
    for ip in imgs:
        img = cv2.imread(ip).astype(int)
        h, w = img.shape[:2]
        lp = ip.replace(os.sep + "images" + os.sep, os.sep + "labels" + os.sep)[:-4] + ".txt"
        c, cx, cy, bw, bh = [float(v) for v in open(lp).read().splitlines()[0].split()]
        assert c == 0 and 0 <= cx <= 1 and 0 <= cy <= 1 and 0 < bw <= 1 and 0 < bh <= 1
        x0, x1 = int(max(0, (cx - bw / 2) * w)), int(min(w, (cx + bw / 2) * w + 1))
        y0, y1 = int(max(0, (cy - bh / 2) * h)), int(min(h, (cy + bh / 2) * h + 1))
        box = img[y0:y1, x0:x1].reshape(-1, 3)
        if np.any((box[:, 2] > 150) & (box[:, 1] > 120) & (box[:, 0] < 110)):
            inside += 1
    check(inside >= 0.95 * len(imgs), f"框裡真的有球（{inside}/{len(imgs)}）")
    check(os.path.exists(os.path.join(out, "data.yaml")), "data.yaml")
    print(f"\n{'全部通過' if not failed else f'{failed} 項失敗'}；資料集：{out}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
