#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按粉末维度审计这 126 条：遥测质量、预测残差、止损视界敏感度。

用法:
    python tools/audit_features.py
    python tools/audit_features.py --index data/runs_126.csv --json

产出:
    results/audit_by_powder.csv   每粉末一行

回答的问题:
    1. 这批数据「够不够」迭代算法（样本量 / 遥测完整性 / 参数覆盖）？
    2. 现有预测器在各粉末上的残差有多大（哪几种最该优先改）？
    3. 单纯调 prediction_horizon 能把这批数据的通过率抬到多少（上界参考）？
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from replay_stop import cfg_of, load_index_ids, run_replay, est_tail  # noqa: E402

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOGS = os.path.join(LAB, "..", "server", "logs")
GRID_H = [0.6, 0.8, 1.0, 1.2, 1.5]


def load_runs(index: str, logs: str) -> list[tuple[dict, dict]]:
    """返回 [(索引行, 日志对象)]。用索引里的显示名分组，与「试验记录」口径一致。"""
    meta = {}
    with open(index, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            meta[r["run_id"]] = r
    out = []
    for f in os.listdir(logs):
        if not f.endswith(".json") or f.endswith("_samples.json"):
            continue
        try:
            j = json.load(open(os.path.join(logs, f), encoding="utf-8-sig"))
        except Exception:
            continue
        rid = j.get("run_id")
        if rid in meta and j.get("samples"):
            out.append((meta[rid], j))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=os.path.join(LAB, "data", "runs_126.csv"))
    ap.add_argument("--logs", default=DEFAULT_LOGS)
    ap.add_argument("--out", default=os.path.join(LAB, "results", "audit_by_powder.csv"))
    args = ap.parse_args()

    pairs = load_runs(args.index, args.logs)
    print("载入 %d 条（索引 %d 条）" % (len(pairs), len(load_index_ids(args.index))))

    groups: dict[str, list] = {}
    for meta, j in pairs:
        groups.setdefault(meta.get("powder") or j.get("powder_name"), []).append((meta, j))

    rows = []
    print("\n%-18s %4s %24s %6s %10s %10s %8s %11s"
          % ("粉末", "n", "目标质量", "拍/条", "残差中位", "残差P90", "当前≤10", "最优H→≤10"))
    for name, grp in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        js = [j for _, j in grp]
        res, ares = [], []
        for j in js:
            c = cfg_of(j)
            r = run_replay(j, c)
            d = float(j["final_mass_mg"]) - r["projected_mg"]
            res.append(d)
            ares.append(abs(d))
        # 当前实际通过率：直接取表格口径 |最终 − 目标| ≤ 10 mg
        devs_act = [abs(float(m["dev_mg"])) for m, _ in grp if m.get("dev_mg") not in (None, "")]
        cur_hit10 = 100.0 * sum(1 for d in devs_act if d <= 10) / len(devs_act) if devs_act else 0
        bias = st.median(res)
        # 扫描 horizon 找最优
        best = (None, -1.0)
        for h in GRID_H:
            devs = []
            for j in js:
                c = cfg_of(j)
                r = run_replay(j, c, horizon=h)
                devs.append(abs(r["projected_mg"] + bias - float(j["target_mass_mg"])))
            hit10 = 100.0 * sum(1 for d in devs if d <= 10) / len(devs)
            if hit10 > best[1]:
                best = (h, hit10)
        tgts = sorted({j["target_mass_mg"] for j in js})
        rows.append(dict(
            powder=name, n=len(js),
            targets="/".join(str(int(t)) for t in tgts),
            samples_per_run=round(sum(len(j["samples"]) for j in js) / len(js), 1),
            residual_median_mg=round(st.median(res), 2),
            residual_p90_abs_mg=round(sorted(ares)[int(0.9 * (len(ares) - 1))], 2),
            current_pass_10mg_pct=round(cur_hit10, 1),
            best_horizon=best[0], best_pass_10mg_pct=round(best[1], 1),
        ))
        print("%-18s %4d %24s %6.0f %10.2f %10.2f %7.1f%% %6.2f→%5.1f%%"
              % (name, len(js), " ".join(str(int(t)) for t in tgts),
                 sum(len(j["samples"]) for j in js) / len(js),
                 st.median(res), sorted(ares)[int(0.9 * (len(ares) - 1))],
                 cur_hit10, best[0], best[1]))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("\n写入", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
