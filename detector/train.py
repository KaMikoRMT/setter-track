#!/usr/bin/env python3
"""用 make_dataset.py 產生的資料集微調 YOLO 球偵測模型（docs/ARCHITECTURE.md 9.2）。

需要：pip install ultralytics（會一起裝 PyTorch）。筆電 CPU 很慢，建議用有 GPU 的電腦或 Google Colab。

用法：
  python3 detector/train.py datasets/ball/data.yaml
  python3 detector/train.py datasets/ball/data.yaml --epochs 150 --model yolo11s.pt --device 0
訓練完會印出 best.pt 的位置，接著：
  python3 detector/detect.py 影片.mp4 --model runs/detect/ball/weights/best.pt -o detections.json
"""
import argparse
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(description="微調 YOLO 球偵測模型")
    ap.add_argument("data", help="data.yaml（make_dataset.py 的輸出）")
    ap.add_argument("--model", default="yolo11n.pt", help="起始模型（預設 yolo11n.pt；可以換成更大的或更新版的 ultralytics 模型）")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640, help="訓練圖大小（要跟 make_dataset.py 的 --crop 一樣）")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--device", default=None, help="0 = 第一張 GPU；cpu；不給就自動")
    ap.add_argument("--name", default="ball", help="輸出在 runs/detect/<name>")
    a = ap.parse_args(argv)
    try:
        from ultralytics import YOLO
    except ImportError:
        raise SystemExit("需要先 pip install ultralytics")
    if not os.path.exists(a.data):
        raise SystemExit(f"找不到 {a.data}；先跑 make_dataset.py")
    model = YOLO(a.model)
    kw = dict(data=a.data, epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, name=a.name, exist_ok=True,
              # 球很小、會模糊：關掉會把球裁掉或變形太多的增強
              mosaic=0.5, scale=0.3, fliplr=0.5, degrees=0.0, mixup=0.0)
    if a.device is not None:
        kw["device"] = a.device
    res = model.train(**kw)
    save_dir = getattr(res, "save_dir", None) or getattr(model.trainer, "save_dir", "runs/detect/" + a.name)
    best = os.path.join(str(save_dir), "weights", "best.pt")
    print(f"\n完成。模型：{best}")
    print(f"接著：python3 detector/detect.py 影片.mp4 --model {best} -o detections.json")


if __name__ == "__main__":
    sys.exit(main())
