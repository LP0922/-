#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 server/logs 下的全部 run 扫成一张扁平索引表，供离线分析 / 回放使用。

用法:
    python tools/build_index.py                     # 默认扫 ../server/logs
    python tools/build_index.py --logs D:/x/logs --out data/runs_index.csv

设计要点:
- 数据源是**设备跑完落盘的日志**（不是数据库，也不是前端接口），字段最全。
- 每个 run 有三件套: {prefix}_{run_id}.json（配置+结果）、
  ..._samples.csv（逐拍遥测）、..._post_stop_samples.csv（停后沉降）。
- 日期/时间从 run_id 里的日期时间戳（8 位日期 + 6 位时间）提取，
  与前端「试验记录」口径一致。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys

RUN_TS = re.compile(r"(\d{8})_(\d{6})")


def _g(d, *path, default=None):
    """安全取嵌套值 a.b.c"""
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def classify_stop(reason: str) -> str:
    """把 stop_reason 归成有限的几类，便于分组统计。"""
    r = (reason or "").lower()
    if "projected safety stop" in r:
        return "safety_stop"
    if "predicted tail confirmed" in r:
        return "predictive_tail"
    if "force stop" in r:
        return "force_stop"
    if "acceptance lower bound" in r:
        return "lower_bound"
    if "stall" in r:
        return "stall"
    if "settle" in r or "stable" in r:
        return "settle"
    return "other" if r else "none"


def flatten(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8-sig") as fh:
            j = json.load(fh)
    except Exception:
        return None

    rid = str(j.get("run_id") or "")
    m = RUN_TS.search(rid)
    init = j.get("initial_parameters") or {}
    prof = j.get("profile") or {}
    pred = j.get("predictive_stop_config") or {}
    hold = j.get("flow_hold_config") or {}
    stall = j.get("stall_recovery_config") or {}
    pulse = j.get("tail_pulse_config") or {}

    tgt = j.get("target_mass_mg")
    fin = j.get("final_mass_mg")
    dev = None if (tgt is None or fin is None) else round(float(fin) - float(tgt), 3)
    lo, hi = j.get("acceptance_min_mg"), j.get("acceptance_max_mg")
    passed = None
    if fin is not None and lo is not None and hi is not None:
        passed = bool(float(lo) <= float(fin) <= float(hi))

    samples = j.get("samples") or []
    return {
        "run_id": rid,
        "date": m.group(1) if m else "",
        "time": m.group(2) if m else "",
        "test_type": j.get("test_type") or "",
        "powder_id": j.get("powder_id") or "",
        "powder_name": j.get("powder_name") or "",
        "target_mass_mg": tgt,
        "final_mass_mg": fin,
        "deviation_mg": dev,
        "acceptance_min_mg": lo,
        "acceptance_max_mg": hi,
        "passed": "" if passed is None else int(passed),
        "actual_duration_s": j.get("actual_duration_s"),
        "stop_reason": j.get("stop_reason") or "",
        "stop_kind": classify_stop(j.get("stop_reason")),
        "result": j.get("result") or "",
        "algorithm_version": j.get("algorithm_version") or "",
        "preset_id": j.get("preset_id") or "",
        # 设备/执行器初始设定
        "frequency_hz": init.get("frequency_hz"),
        "duty_permyriad": init.get("duty_permyriad"),
        "window_position_units": init.get("window_position_units"),
        # 速率档（算法 profile）
        "coarse_rate_mg_s": prof.get("coarse_rate_mg_s"),
        "fine_rate_mg_s": prof.get("fine_rate_mg_s"),
        "precision_rate_mg_s": prof.get("precision_rate_mg_s"),
        "precision_start_remaining_mg": prof.get("precision_start_remaining_mg"),
        "tail_taper_start_remaining_mg": prof.get("tail_taper_start_remaining_mg"),
        "tail_taper_end_remaining_mg": prof.get("tail_taper_end_remaining_mg"),
        "maximum_flow_rate_mg_s": prof.get("maximum_flow_rate_mg_s"),
        # 止损预测参数（迭代主战场）
        "pred_enabled": _g(pred, "enabled"),
        "pred_horizon_s": _g(pred, "prediction_horizon_s"),
        "pred_target_offset_mg": _g(pred, "target_offset_mg"),
        "pred_fixed_tail_mg": _g(pred, "fixed_tail_mass_mg"),
        "pred_confirmations": _g(pred, "confirmation_samples"),
        "pred_fast_stop": _g(pred, "fast_stop_enabled"),
        "pred_safety_stop": _g(pred, "projected_safety_stop_enabled"),
        "pred_safety_offset_mg": _g(pred, "projected_safety_stop_offset_mg"),
        "pred_start_mass_mg": _g(pred, "prediction_start_mass_mg"),
        "measured_safety_mass_mg": _g(pred, "measured_safety_stop_mass_mg"),
        "flow_hold_enabled": hold.get("enabled"),
        "flow_hold_ceiling": hold.get("duty_ceiling_permyriad"),
        "stall_recovery_enabled": stall.get("configured_enabled"),
        "stall_recovery_active_flag": stall.get("enabled"),
        "tail_pulse_enabled": pulse.get("enabled"),
        # 大重量
        "large_reserve_mg": _g(j, "large_prefeed_handoff", "reserve_mg"),
        "large_handoff_mass_mg": _g(j, "large_prefeed_handoff", "vibration_stopped_at_mass_mg"),
        # 遥测规模
        "n_samples": len(samples),
        "n_post_stop": len(j.get("post_stop_samples") or []),
        "window_before": _g(j, "window_before", "position_units"),
        "window_after": _g(j, "window_after", "position_units"),
        "finished_at_utc": j.get("finished_at_utc") or "",
        "json_file": os.path.basename(path),
    }


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    lab = os.path.dirname(here)
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default=os.path.join(lab, "..", "server", "logs"))
    ap.add_argument("--out", default=os.path.join(lab, "data", "runs_index.csv"))
    args = ap.parse_args()

    logs = os.path.abspath(args.logs)
    if not os.path.isdir(logs):
        print("找不到日志目录:", logs, file=sys.stderr)
        return 2

    files = sorted(f for f in os.listdir(logs) if f.endswith(".json"))
    rows, bad = [], 0
    for f in files:
        r = flatten(os.path.join(logs, f))
        if r is None:
            bad += 1
            continue
        rows.append(r)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    if not rows:
        print("没有解析到任何记录", file=sys.stderr)
        return 1
    cols = list(rows[0].keys())
    with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    with_tel = sum(1 for r in rows if (r["n_samples"] or 0) > 0)
    print("日志目录: %s" % logs)
    print("扫描 json: %d（解析失败 %d）" % (len(files), bad))
    print("写入索引: %s（%d 行 × %d 列）" % (args.out, len(rows), len(cols)))
    print("其中带逐拍遥测: %d 条（%.1f%%）" % (with_tel, 100.0 * with_tel / len(rows)))
    d = sorted(r["date"] for r in rows if r["date"])
    if d:
        print("日期跨度: %s -> %s" % (d[0], d[-1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
