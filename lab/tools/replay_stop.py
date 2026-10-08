#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""止损律离线回放：用历史 run 的逐拍遥测，重算「换个参数会在哪一刻停、最终落点多少」。

为什么能这么干（可行性核心）：
控制器每次决策的停机投影是纯函数——
    estimated_tail = fixed_tail + control_rate*horizon + 0.5*max(0,accel)*horizon**2
    projected      = mass_mg + estimated_tail
而 control_rate / acceleration / mass_mg 这些输入**逐拍都落盘了**（samples 数组或
*_samples.csv）。因此把同一段遥测喂给改过的 (horizon, target_offset, confirmations)
就能复现「那一次会停在哪」，不需要动设备。

可信度校验：用**记录里的原参数**回放，停机点应与实际记录一致；
     残差 = final_mass_mg − 停机时 projected_mass（落粉尾巴的物理误差）应集中在 0 附近。
     残差越集中，反事实推算越可信。

用法:
    # 0) 先锁定范围（只针对「试验记录」那 126 条）
    python tools/select_126.py

    # 1) 校验 + 残差分布（默认就在 126 条上跑）
    python tools/replay_stop.py

    # 2) 只看某种粉末
    python tools/replay_stop.py --powder bentonite

    # 3) 参数扫描（找更优的止损参数）
    python tools/replay_stop.py --sweep

    # 4) 单条 run 明细
    python tools/replay_stop.py --run-id large-dispense-8000mg-20260924_140543-1e9100

    # 5) 想看全量 2630 个 run 时才需要显式放开
    python tools/replay_stop.py --index none
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics as st
import sys

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOGS = os.path.join(LAB, "..", "server", "logs")


def est_tail(sample: dict, horizon: float, fixed_tail: float) -> float:
    """复刻控制器的停机投影尾巴（feedback_controller._stop_projection）。"""
    rate = float(sample.get("control_rate_mg_s") or 0.0)
    accel = max(0.0, float(sample.get("acceleration_mg_s2") or 0.0))
    return fixed_tail + rate * horizon + 0.5 * accel * horizon * horizon


def replay(samples, target, horizon, target_offset, confirmations, fixed_tail,
           *, safety_offset=None, measured_safety_mass=None, prediction_start_mass=None,
           force_stop_mass=None):
    """在给定遥测上重跑停机判定。

    返回 dict(stop_index, kind, elapsed_s, projected_mg, mass_mg, tail_mg)；
    永不触发时 stop_index = len(samples)-1、kind='no_stop'。
    """
    if not samples:
        return None
    count = 0
    for i, s in enumerate(samples):
        mass = float(s.get("mass_mg") or 0.0)
        valid = bool(s.get("rate_valid")) or float(s.get("control_rate_mg_s") or 0.0) > 0.0
        tail = est_tail(s, horizon, fixed_tail)
        proj = mass + tail
        if force_stop_mass is not None and mass >= force_stop_mass:
            return dict(stop_index=i, kind="force_stop", elapsed_s=s.get("elapsed_s"),
                        projected_mg=proj, mass_mg=mass, tail_mg=tail)
        if measured_safety_mass is not None and mass >= measured_safety_mass:
            return dict(stop_index=i, kind="measured_safety", elapsed_s=s.get("elapsed_s"),
                        projected_mg=proj, mass_mg=mass, tail_mg=tail)
        if safety_offset is not None and proj >= target + safety_offset:
            return dict(stop_index=i, kind="safety_stop", elapsed_s=s.get("elapsed_s"),
                        projected_mg=proj, mass_mg=mass, tail_mg=tail)
        if not valid:
            count = 0
            continue
        if prediction_start_mass is not None and mass < prediction_start_mass:
            count = 0
            continue
        if proj >= target - target_offset:
            count += 1
            # 用**当拍遥测里的实际生效值**，而不是配置里的 confirmation_samples：
            # 设备在窗口/快停路径上会把要求降到 1，配置值会高估所需连续确认数。
            req = int(s.get("stop_confirmation_required") or confirmations or 1)
            if count >= max(1, req):
                return dict(stop_index=i, kind="predictive_tail", elapsed_s=s.get("elapsed_s"),
                            projected_mg=proj, mass_mg=mass, tail_mg=tail)
        else:
            count = 0
    s = samples[-1]
    tail = est_tail(s, horizon, fixed_tail)
    return dict(stop_index=len(samples) - 1, kind="no_stop", elapsed_s=s.get("elapsed_s"),
                projected_mg=float(s.get("mass_mg") or 0.0) + tail,
                mass_mg=s.get("mass_mg"), tail_mg=tail)


def load_index_ids(path: str) -> set[str]:
    """从 select_126.py 产出的索引里读出被选中的 run_id 集合。"""
    with open(path, encoding="utf-8-sig") as fh:
        return {r["run_id"] for r in csv.DictReader(fh) if r.get("run_id")}


def iter_records(logs_dir, powder=None, limit=None, min_samples=10, run_ids=None):
    """迭代可回放的 run。

    min_samples 过滤掉只落了几拍的残 run——否则它们会因为「只有 1 拍、
    回放索引必然等于末索引」而污染命中率。
    run_ids 给定后只回放这些 run（用于把分析范围锁死在「试验记录」那 126 条上）。
    """
    files = sorted(f for f in os.listdir(logs_dir)
                   if f.endswith(".json") and not f.endswith("_samples.json"))
    n = 0
    for f in files:
        p = os.path.join(logs_dir, f)
        try:
            with open(p, encoding="utf-8-sig") as fh:
                j = json.load(fh)
        except Exception:
            continue
        if j.get("test_type") != "feedback_dispense":
            continue
        if run_ids is not None and j.get("run_id") not in run_ids:
            continue
        if powder and (j.get("powder_id") != powder and j.get("powder_name") != powder):
            continue
        if len(j.get("samples") or []) < min_samples:
            continue
        if j.get("target_mass_mg") is None or j.get("final_mass_mg") is None:
            continue
        yield j
        n += 1
        if limit and n >= limit:
            return


def cfg_of(j: dict) -> dict:
    pred = j.get("predictive_stop_config") or {}
    prof = j.get("profile") or {}
    start = pred.get("prediction_start_mass_mg")
    tgt = j.get("target_mass_mg")
    if start is None and tgt is not None and prof.get("precision_start_remaining_mg") is not None:
        start = float(tgt) - float(prof["precision_start_remaining_mg"])
    return dict(
        horizon=float(pred.get("prediction_horizon_s") or 1.0),
        target_offset=float(pred.get("target_offset_mg") or 0.0),
        confirmations=int(pred.get("confirmation_samples") or 1),
        fixed_tail=float(pred.get("fixed_tail_mass_mg") or 0.0),
        safety_offset=(float(pred["projected_safety_stop_offset_mg"])
                       if pred.get("projected_safety_stop_enabled") else None),
        measured_safety=pred.get("measured_safety_stop_mass_mg"),
        prediction_start=start,
        hard_limit=j.get("hard_limit_mg"),
    )


def run_replay(j: dict, c: dict, *, horizon=None, offset=None):
    """按 cfg（可被 horizon/offset 覆盖）回放一条 run。"""
    return replay(j["samples"], j["target_mass_mg"],
                  c["horizon"] if horizon is None else horizon,
                  c["target_offset"] if offset is None else offset,
                  c["confirmations"], c["fixed_tail"],
                  safety_offset=c["safety_offset"],
                  measured_safety_mass=c["measured_safety"],
                  prediction_start_mass=c["prediction_start"],
                  force_stop_mass=c["hard_limit"])


def cmd_validate(args) -> int:
    rows, nofire = [], 0
    for j in iter_records(args.logs, args.powder, args.limit, args.min_samples, args.run_ids):
        c = cfg_of(j)
        r = run_replay(j, c)
        n = len(j["samples"])
        # 命中 = 回放真的触发了停机，且停机点与记录末拍一致
        fired = r["kind"] != "no_stop"
        if not fired:
            nofire += 1
        rows.append(dict(
            run_id=j["run_id"], powder=j.get("powder_name") or j.get("powder_id"),
            target=j["target_mass_mg"], final=j.get("final_mass_mg"),
            n_samples=n, recorded_stop_idx=n - 1, replay_stop_idx=r["stop_index"],
            hit=int(fired and r["stop_index"] == n - 1), fired=int(fired), kind=r["kind"],
            projected=r["projected_mg"],
            residual=(float(j["final_mass_mg"]) - r["projected_mg"]),
            stop_reason=(j.get("stop_reason") or "")[:48],
        ))
    if not rows:
        print("没有可回放的 run（需要 feedback_dispense 且样本 ≥ %d 拍）" % args.min_samples,
              file=sys.stderr)
        return 1

    hit = sum(r["hit"] for r in rows)
    fired = sum(r["fired"] for r in rows)
    res = [r["residual"] for r in rows]
    ares = [abs(x) for x in res]
    print("有效回放 run: %d 条（已剔除样本 < %d 拍的残 run）" % (len(rows), args.min_samples))
    print("止损律触发且停机点一致: %d / %d = %.1f%%" % (hit, len(rows), 100.0 * hit / len(rows)))
    print("仅「触发」(不看索引): %d / %d = %.1f%%；未触发 %d 条"
          % (fired, len(rows), 100.0 * fired / len(rows), nofire))
    print("残差 final_mass − projected_at_stop: 均值 %+.2f mg  中位 %+.2f mg" % (st.mean(res), st.median(res)))
    print("|残差|: 均值 %.2f mg  中位 %.2f mg  P90 %.2f mg" % (st.mean(ares), st.median(ares), sorted(ares)[int(0.9 * (len(ares) - 1))]))
    print("|残差| ≤ 10 / 20 / 30 mg 占比: %.1f%% / %.1f%% / %.1f%%"
          % (100.0 * sum(1 for x in ares if x <= 10) / len(ares),
             100.0 * sum(1 for x in ares if x <= 20) / len(ares),
             100.0 * sum(1 for x in ares if x <= 30) / len(ares)))

    miss = [r for r in rows if not r["hit"]]
    if miss:
        print("\n未命中 %d 条，前 5 条:" % len(miss))
        for r in miss[:5]:
            print("   %-46s kind=%-14s idx %d vs %d | %s"
                  % (r["run_id"][:46], r["kind"], r["replay_stop_idx"], r["recorded_stop_idx"],
                     r["stop_reason"]))

    out = os.path.join(LAB, "results", "replay_validate.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("\n明细已写入 %s" % out)
    return 0


def cmd_sweep(args) -> int:
    """网格搜索：对每条历史遥测换一组止损参数，看落点会变成多少。

    反事实口径: 新落点 ≈ 新停机点的 projected + 该粉末历史残差中位数。
    这是**筛选级**估计（落粉尾巴对停机时刻是非线性的），用于把候选参数从一大片
    砍到几个，再由设备 A/B 定论。
    """
    recs = list(iter_records(args.logs, args.powder, args.limit, args.min_samples, args.run_ids))
    if not recs:
        print("没有可用的 run", file=sys.stderr)
        return 1

    res = [float(j["final_mass_mg"]) - run_replay(j, cfg_of(j))["projected_mg"] for j in recs]
    bias = st.median(res)
    print("样本 %d 条 | 残差中位数 %+.2f mg（反事实偏置）" % (len(recs), bias))
    print("目标质量: %s\n" % sorted({j["target_mass_mg"] for j in recs}))

    grid_h = [0.6, 0.8, 1.0, 1.2, 1.5]
    grid_o = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
    best = []
    print("%-8s %-7s %10s %9s %7s %7s %7s" % ("horizon", "offset", "均|偏差|", "中位|偏差|", "≤10mg", "≤20mg", "≤30mg"))
    for h in grid_h:
        for o in grid_o:
            devs = []
            for j in recs:
                c = cfg_of(j)
                r = run_replay(j, c, horizon=h, offset=o)
                devs.append(abs(r["projected_mg"] + bias - float(j["target_mass_mg"])))
            if not devs:
                continue
            row = (h, o, st.mean(devs), st.median(devs),
                   100.0 * sum(1 for d in devs if d <= 10) / len(devs),
                   100.0 * sum(1 for d in devs if d <= 20) / len(devs),
                   100.0 * sum(1 for d in devs if d <= 30) / len(devs))
            best.append(row)
            print("%-8.2f %-7.1f %10.2f %9.2f %6.1f%% %6.1f%% %6.1f%%" % row)

    best.sort(key=lambda r: (r[3], -r[4]))
    print("\n按「中位|偏差|」最优的前 5 组（中位数比均值更抗离群）:")
    for r in best[:5]:
        print("   horizon=%.2f offset=%.1f → 中位|偏差| %.2f mg，≤10mg 通过率 %.1f%%，≤20mg %.1f%%"
              % (r[0], r[1], r[3], r[4], r[5]))
    print("\n注意：这只是离线筛选。落粉尾巴对停机时刻是非线性的，"
          "最终必须用设备跑 A/B（batch_test 通道）确认。")
    return 0


def cmd_one(args) -> int:
    rec = None
    for j in iter_records(args.logs, None, None, 1, args.run_ids):
        if j["run_id"] == args.run_id:
            rec = j
            break
    if rec is None:
        print("未找到 run（或样本不足）:", args.run_id, file=sys.stderr)
        return 1
    j = rec
    c = cfg_of(j)
    print("run_id      :", j["run_id"])
    print("粉末/目标   : %s / %s mg" % (j.get("powder_name"), j.get("target_mass_mg")))
    print("记录结果    : final=%s mg  duration=%ss" % (j.get("final_mass_mg"), j.get("actual_duration_s")))
    print("            reason=%s" % j.get("stop_reason"))
    print("记录参数    : %s" % {k: (round(v, 3) if isinstance(v, float) else v) for k, v in c.items()})
    print("遥测拍数    : %d" % len(j["samples"]))
    r = run_replay(j, c)
    resid = float(j["final_mass_mg"]) - r["projected_mg"]
    print("回放停机    : kind=%s  idx %d/%d  elapsed=%ss  projected=%.1f mg  残差=%+.1f mg"
          % (r["kind"], r["stop_index"], len(j["samples"]) - 1, r["elapsed_s"], r["projected_mg"], resid))
    print("\n敏感度（残差按记录值不变，仅看停机点平移）:")
    for o in (0.0, 3.0, 6.0, 10.0):
        r2 = run_replay(j, c, offset=o)
        print("   offset=%-5.1f → idx %-4d projected %8.1f mg → 估计落点 %8.1f mg"
              % (o, r2["stop_index"], r2["projected_mg"], r2["projected_mg"] + resid))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default=DEFAULT_LOGS)
    ap.add_argument("--index", default=os.path.join(LAB, "data", "runs_126.csv"),
                    help="只回放该索引里的 run（默认锁定「试验记录」那 126 条）；传 none 表示扫全量")
    ap.add_argument("--powder", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-samples", type=int, default=10,
                    help="最少遥测拍数，过滤只落了几拍的残 run（默认 10）")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args()
    args.run_ids = None
    if args.index and args.index.lower() != "none" and os.path.isfile(args.index):
        args.run_ids = load_index_ids(args.index)
        print("已锁定索引 %s：%d 条 run" % (args.index, len(args.run_ids)))
    if args.run_id:
        return cmd_one(args)
    if args.sweep:
        return cmd_sweep(args)
    return cmd_validate(args)


if __name__ == "__main__":
    raise SystemExit(main())
