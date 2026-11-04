#!/usr/bin/env python3
"""把網頁工具匯出的訓練標註（labels.json）轉成 YOLO 資料集（docs/ARCHITECTURE.md 9.2）。

球在 1080p／4K 畫面裡很小，整張縮到 640 會看不到球，所以預設在球附近切 640×640 的小圖（不縮放），
球的位置在小圖裡隨機，訓練完用原解析度偵測（detect.py --model 會自動用影片寬度當 imgsz）。

用法：
  python3 detector/make_dataset.py 影片.mp4 影片-labels.json -o datasets/ball
  python3 detector/make_dataset.py a.mp4 a-labels.json b.mp4 b-labels.json -o datasets/ball   # 多支影片
"""
import argparse
import json
import os
import random
import sys

import cv2


def frame_index(t, fps):
    # 網頁工具與 detect.py 的時間都是「這一格的中間」(n + 0.5) / fps
    return int(t * fps)


def build(pairs, out_dir, crop=640, val_frac=0.15, pad=1.25, min_box=6, seed=1):
    rng = random.Random(seed)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        os.makedirs(os.path.join(out_dir, sub), exist_ok=True)
    stats = {"images": 0, "train": 0, "val": 0, "skipped": 0}
    for vi, (video, labels_path) in enumerate(pairs):
        L = json.load(open(labels_path, encoding="utf-8"))
        if L.get("app") != "setter-track-labels":
            raise SystemExit(f"{labels_path} 不是網頁工具匯出的訓練標註")
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            raise SystemExit(f"打不開影片：{video}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if L["video"].get("w") and (L["video"]["w"] != W or L["video"]["h"] != H):
            raise SystemExit(f"{labels_path} 的解析度 {L['video']['w']}×{L['video']['h']} 跟影片 {W}×{H} 不一樣")
        by_frame = {}
        for lab in L["labels"]:
            by_frame.setdefault(frame_index(lab["t"], fps), []).append(lab)
        # 同一顆舉球的連續幾格長得很像，分 train/val 時以「一段」為單位，避免 val 太簡單
        frames = sorted(by_frame)
        groups, cur = [], []
        for f in frames:
            if cur and f - cur[-1] > int(fps):
                groups.append(cur)
                cur = []
            cur.append(f)
        if cur:
            groups.append(cur)
        rng.shuffle(groups)
        n_val = max(1, int(round(len(groups) * val_frac))) if len(groups) > 1 else 0
        split = {f: ("val" if gi < n_val else "train") for gi, g in enumerate(groups) for f in g}
        base = os.path.splitext(os.path.basename(video))[0]
        for f in frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            ok, img = cap.read()
            if not ok:
                stats["skipped"] += 1
                continue
            labs = by_frame[f]
            if crop and (W > crop or H > crop):
                cw, ch = min(crop, W), min(crop, H)
                main = labs[0]
                x0 = int(min(max(0, main["u"] - rng.uniform(0.15, 0.85) * cw), W - cw))
                y0 = int(min(max(0, main["v"] - rng.uniform(0.15, 0.85) * ch), H - ch))
                img = img[y0:y0 + ch, x0:x0 + cw]
            else:
                x0, y0, cw, ch = 0, 0, W, H
            lines = []
            for lab in labs:
                cx, cy = lab["u"] - x0, lab["v"] - y0
                s = max(min_box, 2 * lab["r"] * pad)
                if not (0 <= cx < cw and 0 <= cy < ch):
                    continue
                lines.append(f"0 {cx / cw:.6f} {cy / ch:.6f} {min(s, cw) / cw:.6f} {min(s, ch) / ch:.6f}")
            if not lines:
                stats["skipped"] += 1
                continue
            part = split[f]
            name = f"{base}_{vi}_{f:07d}"
            cv2.imwrite(os.path.join(out_dir, "images", part, name + ".jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            with open(os.path.join(out_dir, "labels", part, name + ".txt"), "w") as fh:
                fh.write("\n".join(lines) + "\n")
            stats["images"] += 1
            stats[part] += 1
        cap.release()
    with open(os.path.join(out_dir, "data.yaml"), "w", encoding="utf-8") as fh:
        fh.write(f"path: {os.path.abspath(out_dir)}\ntrain: images/train\nval: images/val\nnames:\n  0: ball\n")
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description="網頁工具的訓練標註 → YOLO 資料集")
    ap.add_argument("pairs", nargs="+", help="影片 標註 影片 標註 …（兩兩一組）")
    ap.add_argument("-o", "--out", default="datasets/ball", help="輸出資料夾")
    ap.add_argument("--crop", type=int, default=640, help="在球附近切多大的小圖（0 = 整張）")
    ap.add_argument("--val", type=float, default=0.15, help="驗證集比例（以一段舉球為單位）")
    a = ap.parse_args(argv)
    if len(a.pairs) % 2:
        ap.error("影片和標註要兩兩一組")
    pairs = list(zip(a.pairs[0::2], a.pairs[1::2]))
    st = build(pairs, a.out, crop=a.crop, val_frac=a.val)
    print(f"完成：{st['images']} 張（訓練 {st['train']}、驗證 {st['val']}，略過 {st['skipped']}）→ {os.path.join(a.out, 'data.yaml')}")
    if st["val"] == 0:
        print("提醒：驗證集是空的（標註的舉球太少），多標幾顆再訓練比較準。", file=sys.stderr)


if __name__ == "__main__":
    main()
