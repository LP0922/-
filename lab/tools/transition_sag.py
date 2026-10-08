"""量化「快加 -> 慢加」切换后的速率瞬态：同一个 duty 到底给不给同一个速率。

背景假设（待验证）：快加阶段的高速出粉会在物理上把粉体打散/流化，
使得切到低速率参数后，实际速率低于「低速配置在稳定状态下标定出来的值」。
若成立，则静态的 (duty -> rate) 表只在同一前史下有效，前馈/标定必须补一个瞬态项。

用法:
    python tools/transition_sag.py                 # 全 126 条
    python tools/transition_sag.py --powder 润滑剂1
    python tools/transition_sag.py --min-fine-s 6  # 只统计 fine 段够长的 run

输出:
    results/transition_sag.csv   每个 run 的过渡段指标（逐条）
    stdout                       按粉末汇总 + 同 duty 不同前史的对照表
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics as st
from collections import OrderedDict, defaultdict

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.normpath(os.path.join(LAB, "..", "server", "logs"))
INDEX = os.path.join(LAB, "data", "runs_126.csv")


def load_index() -> dict:
    rows = {}
    with open(INDEX, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            rows[r["run_id"]] = r
    return rows


def load_runs(ids: dict, powder: str | None = None) -> list:
    out = []
    for f in sorted(os.listdir(LOGS)):
        if not f.endswith(".json") or f.endswith("_samples.json"):
            continue
        try:
            with open(os.path.join(LOGS, f), encoding="utf-8-sig") as fh:
                j = json.load(fh)
        except Exception:
            continue
        meta = ids.get(j.get("run_id"))
        if not meta or not j.get("samples"):
            continue
        if powder and meta.get("powder") != powder:
            continue
        j["_powder"] = meta.get("powder")
        out.append(j)
    return out


def transitions(samples: list) -> list:
    out = []
    for i in range(1, len(samples)):
        a, b = samples[i - 1].get("stage"), samples[i].get("stage")
        if a != b:
            out.append((i, a, b))
    return out


def _rate(s):
    v = s.get("control_rate_mg_s")
    return None if v is None else float(v)


def fine_entry_metrics(samples: list, i0: int) -> dict:
    """切进 fine 的那一瞬间开始，量四个东西：过冲、质量多喂、恢复时间、后段稳态。"""
    t0 = float(samples[i0]["elapsed_s"])
    tgt = samples[i0].get("target_rate_mg_s") or 0.0
    tgt = float(tgt)
    mass0 = samples[i0].get("mass_mg")
    win2 = [s for s in samples[i0:] if t0 <= float(s["elapsed_s"]) <= t0 + 2.0]
    win4 = [s for s in samples[i0:] if float(s["elapsed_s"]) >= t0 + 4.0]
    r2 = [x for x in (_rate(s) for s in win2) if x is not None]
    d2 = [float(s["duty_permyriad"]) for s in win2 if s.get("duty_permyriad") is not None]
    r4 = [x for x in (_rate(s) for s in win4) if x is not None]
    d4 = [float(s["duty_permyriad"]) for s in win4 if s.get("duty_permyriad") is not None]

    # 2 s 后最接近的那个采样点，用来算质量增量
    tail = [s for s in samples[i0:] if float(s["elapsed_s"]) > t0 + 2.0]
    mass2 = tail[0].get("mass_mg") if tail else None

    m = dict(
        run_id=samples[0].get("_run_id"),
        t_switch=round(t0, 2),
        target_before=samples[i0 - 1].get("target_rate_mg_s"),
        target_after=tgt,
        duty_at_switch=samples[i0].get("duty_permyriad"),
        rate_at_switch=_rate(samples[i0]),
        mass_at_switch=mass0,
        rate_max_2s=(max(r2) if r2 else None),
        rate_mean_2s=(round(st.mean(r2), 2) if r2 else None),
        duty_mean_2s=(round(st.mean(d2), 1) if d2 else None),
        rate_mean_settled=(round(st.mean(r4), 2) if r4 else None),
        duty_mean_settled=(round(st.mean(d4), 1) if d4 else None),
        mass_gain_2s=(None if (mass0 is None or mass2 is None) else round(float(mass2) - float(mass0), 1)),
    )
    m["overshoot_2s"] = (None if m["rate_max_2s"] is None else round(m["rate_max_2s"] - tgt, 2))
    m["expect_gain_2s"] = round(2.0 * tgt, 1)
    m["excess_gain_2s"] = (None if m["mass_gain_2s"] is None
                           else round(m["mass_gain_2s"] - 2.0 * tgt, 1))

    # 恢复时间：|control_rate - tgt| 进 ±20% 并保持 0.5 s
    rec = None
    if tgt > 0:
        tol = 0.2 * tgt
        for k in range(i0, len(samples)):
            tk = float(samples[k]["elapsed_s"])
            cr = _rate(samples[k])
            if cr is None or abs(cr - tgt) > tol:
                continue
            hold = [x for x in samples[k:] if tk <= float(x["elapsed_s"]) <= tk + 0.5]
            if len(hold) >= 2 and all((_rate(x) is not None and abs(_rate(x) - tgt) <= tol) for x in hold):
                rec = round(tk - t0, 2)
                break
    m["t_recover_s"] = rec

    # fine 段里「跑不准」的占比（|rate - target| > 50% target），带方向
    far_over = far_under = tot = 0
    for s in samples[i0:]:
        if s.get("stage") != "fine":
            break
        cr = _rate(s)
        if cr is None or tgt <= 0:
            continue
        tot += 1
        if cr - tgt > 0.5 * tgt:
            far_over += 1
        elif tgt - cr > 0.5 * tgt:
            far_under += 1
    m["fine_n"] = tot
    m["fine_far_over"] = far_over
    m["fine_far_under"] = far_under

    # 控制器自己报的「低流量 / 堵转恢复」，在切换后 3 s 内触发次数
    def _flag(s, key):
        return bool(s.get(key))
    m["recovery_hits_3s"] = sum(
        1 for s in samples[i0:] if float(s["elapsed_s"]) <= t0 + 3.0
        and (_flag(s, "stall_recovery_active") or _flag(s, "large_low_flow_recovery")
             or _flag(s, "low_flow_recovery_monitoring"))
    )
    m["recovery_hits_all"] = sum(
        1 for s in samples if _flag(s, "stall_recovery_active") or _flag(s, "large_low_flow_recovery")
        or _flag(s, "low_flow_recovery_monitoring")
    )
    return m


def fine_duty_rate_pairs(samples: list, i0: int):
    """fine 段内 (duty, rate, dt)：dt<=2s 算「刚切完」，dt>=4s 算「稳定后」。"""
    t0 = float(samples[i0]["elapsed_s"])
    early, late = [], []
    for s in samples[i0:]:
        if s.get("stage") != "fine":
            break
        cr, d = _rate(s), s.get("duty_permyriad")
        if cr is None or d is None:
            continue
        dt = float(s["elapsed_s"]) - t0
        if dt <= 2.0:
            early.append((float(d), cr))
        elif dt >= 4.0:
            late.append((float(d), cr))
    return early, late


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--powder", default=None)
    ap.add_argument("--min-fine-s", type=float, default=0.0,
                    help="只统计 fine 段持续 >= 该秒数的 run（做同 duty 对照建议 6）")
    args = ap.parse_args()

    ids = load_index()
    runs = load_runs(ids, args.powder)
    print("载入 %d 条 run（索引 %d 条）\n" % (len(runs), len(ids)))

    rows = []
    bypow = defaultdict(list)
    pairs_early = defaultdict(list)   # powder -> [(duty, rate)]
    pairs_late = defaultdict(list)
    for j in runs:
        ss = j["samples"]
        rid = j["run_id"]
        for s in ss:
            s["_run_id"] = rid
        for i0, a, b in transitions(ss):
            if b != "fine":
                continue
            fine_dur = 0.0
            for s in ss[i0:]:
                if s.get("stage") != "fine":
                    break
                fine_dur = float(s["elapsed_s"]) - float(ss[i0]["elapsed_s"])
            if fine_dur < args.min_fine_s:
                continue
            m = fine_entry_metrics(ss, i0)
            m["run_id"] = rid
            m["powder"] = j["_powder"]
            m["prev_stage"] = a
            m["target_mass_mg"] = j.get("target_mass_mg")
            m["final_mass_mg"] = j.get("final_mass_mg")
            m["fine_dur_s"] = round(fine_dur, 2)
            rows.append(m)
            bypow[j["_powder"]].append(m)
            e, l = fine_duty_rate_pairs(ss, i0)
            pairs_early[j["_powder"]].extend(e)
            pairs_late[j["_powder"]].extend(l)

    if not rows:
        print("没有匹配的过渡段")
        return 1

    print("共 %d 个 coarse->fine 过渡段\n" % len(rows))

    def med(xs):
        xs = [x for x in xs if x is not None]
        return round(st.median(xs), 2) if xs else None

    print("%-16s %4s %10s %10s %10s %11s %10s"
          % ("粉末", "n", "切换时速率", "2s内峰值", "目标速率", "2s多喂mg", "恢复s"))
    print("-" * 82)
    for name, ms in sorted(bypow.items(), key=lambda kv: -len(kv[1])):
        print("%-16s %4d %10s %10s %10s %11s %10s"
              % (name, len(ms),
                 med([m["rate_at_switch"] for m in ms]),
                 med([m["rate_max_2s"] for m in ms]),
                 med([m["target_after"] for m in ms]),
                 med([m["excess_gain_2s"] for m in ms]),
                 med([m["t_recover_s"] for m in ms])))
    print("%-16s %4d %10s %10s %10s %11s %10s"
          % ("合计", len(rows),
             med([m["rate_at_switch"] for m in rows]),
             med([m["rate_max_2s"] for m in rows]),
             med([m["target_after"] for m in rows]),
             med([m["excess_gain_2s"] for m in rows]),
             med([m["t_recover_s"] for m in rows])))

    tot_fine = sum(m["fine_n"] for m in rows)
    over = sum(m["fine_far_over"] for m in rows)
    under = sum(m["fine_far_under"] for m in rows)
    print("\n慢加段跑不准情况：fine 段共 %d 拍，其中速率高于目标 50%% 以上 %d 拍(%.1f%%)，"
          "低于目标 50%% 以上 %d 拍(%.1f%%)"
          % (tot_fine, over, 100.0 * over / max(tot_fine, 1),
             under, 100.0 * under / max(tot_fine, 1)))
    nrec = sum(1 for m in rows if m["t_recover_s"] is None)
    print("切换后 8 s 内始终没能把速率拉回目标 ±20%% 的过渡段：%d / %d"
          % (nrec, len(rows)))
    print("控制器自身「低流量/堵转恢复」在切换后 3 s 内触发的过渡段：%d / %d"
          % (sum(1 for m in rows if m["recovery_hits_3s"] > 0), len(rows)))

    # ---- 同 duty、不同前史 的对照 ----
    print("\n== 同一个 duty 档位，「刚切完(<=2s)」vs「稳定后(>=4s)」的中位速率 ==")
    print("（若被控对象是静态的，两列应相等；差异即前史依赖）")
    print("%-16s %8s %8s %8s %8s %8s" % ("粉末", "duty档", "刚切完", "稳定后", "差值", "n前/n后"))
    print("-" * 66)
    overall = []
    for name in sorted(bypow, key=lambda k: -len(bypow[k])):
        be, bl = defaultdict(list), defaultdict(list)
        for d, r in pairs_early[name]:
            be[int(d // 100) * 100].append(r)
        for d, r in pairs_late[name]:
            bl[int(d // 100) * 100].append(r)
        for b in sorted(set(be) & set(bl)):
            if len(be[b]) >= 3 and len(bl[b]) >= 3:
                me, ml = st.median(be[b]), st.median(bl[b])
                overall.append((me, ml))
                print("%-16s %8d %8.1f %8.1f %+8.1f %5d/%d"
                      % (name, b, me, ml, me - ml, len(be[b]), len(bl[b])))
    if overall:
        me = st.median([a for a, _ in overall])
        ml = st.median([b for _, b in overall])
        print("-" * 66)
        print("跨粉末中位：刚切完 %.1f mg/s  稳定后 %.1f mg/s  差 %+.1f mg/s"
              % (me, ml, me - ml))

    out = os.path.join(LAB, "results", "transition_sag.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    cols = ["run_id", "powder", "prev_stage", "target_mass_mg", "final_mass_mg",
            "t_switch", "target_before", "target_after", "duty_at_switch",
            "rate_at_switch", "rate_max_2s", "rate_mean_2s", "duty_mean_2s",
            "rate_mean_settled", "duty_mean_settled", "mass_at_switch",
            "mass_gain_2s", "expect_gain_2s", "excess_gain_2s", "overshoot_2s",
            "t_recover_s", "fine_dur_s", "fine_n", "fine_far_over", "fine_far_under",
            "recovery_hits_3s", "recovery_hits_all"]
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print("\n明细已写入 %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
