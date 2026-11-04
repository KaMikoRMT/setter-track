#!/usr/bin/env python3
"""用合成影片（已知每一格球的位置）檢查 detect.py。

用法：python3 detector/tests/test_synthetic.py [合成影片資料夾]
沒給資料夾就先用 node tests/make-synthetic.mjs 產生一份到暫存資料夾。
結果的 detections.json 會寫在同一個資料夾，tests/ui-check.mjs 會拿去測匯入。
"""
import json
import math
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "detector"))
import detect  # noqa: E402


def main():
    syn = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="setter-syn-")
    if not os.path.exists(os.path.join(syn, "truth.json")):
        subprocess.run(["node", os.path.join(ROOT, "tests", "make-synthetic.mjs"), syn], check=True)
    truth = json.load(open(os.path.join(syn, "truth.json"), encoding="utf-8"))
    out = detect.run(os.path.join(syn, "synthetic.mp4"), progress=False)
    with open(os.path.join(syn, "detections.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)

    fps = truth["video"]["fps"]
    by_frame = {b["frame"]: b for b in truth["ballPx"]}
    pts = [(int(p["t"] * fps), p["u"], p["v"]) for tr in out["tracks"] for p in tr["points"]]
    tol = lambda b: max(3.0, 0.6 * b["r"])  # noqa: E731
    good = [p for p in pts if p[0] in by_frame and math.hypot(p[1] - by_frame[p[0]]["u"], p[2] - by_frame[p[0]]["v"]) <= tol(by_frame[p[0]])]
    hit = {p[0] for p in good}
    visible = [b for b in truth["ballPx"] if 0 <= b["u"] < truth["video"]["w"] and 0 <= b["v"] < truth["video"]["h"]]
    recall = len([b for b in visible if b["frame"] in hit]) / max(1, len(visible))
    precision = len(good) / max(1, len(pts))
    errs = sorted(math.hypot(p[1] - by_frame[p[0]]["u"], p[2] - by_frame[p[0]]["v"]) for p in good)
    med = errs[len(errs) // 2] if errs else float("nan")

    failed = 0

    def check(cond, msg):
        nonlocal failed
        print(("  ✓ " if cond else "  ✗ ") + msg)
        if not cond:
            failed += 1

    check(recall >= 0.9, f"找回球的格數比例 {recall:.1%}（{len(hit)}/{len(visible)}）")
    # 剩下的雜訊（人身上的）交給網頁工具用物理條件過濾；最後找不找得到舉球由 tests/ui-check.mjs 檢查
    check(precision >= 0.6, f"輸出的點是球的比例 {precision:.1%}（{len(good)}/{len(pts)}）")
    check(med <= 1.5, f"位置誤差中位數 {med:.2f} px")
    check(out["stats"]["tracks"] <= 30, f"軌跡數 {out['stats']['tracks']}")
    print(f"\n{'全部通過' if not failed else f'{failed} 項失敗'}（{out['stats']['frames']} 格，平均每格 {out['stats']['candidates_per_frame']} 個候選）")
    print(f"偵測結果：{os.path.join(syn, 'detections.json')}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
