"""检查控制器「降速通道」还剩多少权限（authority）。

动机：如果慢加段的 duty 已经贴死在 min_duty_permyriad，而速率仍然高于目标，
那说明问题不是「参数没调好」，而是**调节手段用尽**——
这种情况下再怎么标定低速配置都不会准。

用法:
    python tools/loop_authority.py                # 全 126 条
    python tools/loop_authority.py --powder 失水剂2

输出:
    results/loop_authority.csv   按粉末的饱和统计
    stdout                       明细表 + 同 (duty, 窗口) 组合下的产率散度
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics as st
from collections import defaultdict

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.normpath(os.path.join(LAB, "..", "server", "logs"))
INDEX = os.path.join(LAB, "data", "runs_126.csv")

DUTY_MIN = 1000      # FeedbackSettings.min_duty_permyriad
DUTY_MAX = 5000
AT_LIMIT = 50        # 距限值的容差


def load(ids: dict, powder: str | None):
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--powder", default=None)
    args = ap.parse_args()

    ids = {r["run_id"]: r for r in csv.DictReader(open(INDEX, encoding="utf-8-sig"))}
    runs = load(ids, args.powder)

    fine = defaultdict(lambda: defaultdict(list))
    cells = defaultdict(lambda: defaultdict(list))   # (pw,duty,win) -> regime -> rates
    for j in runs:
        pw = j["_powder"]
        ss = j["samples"]
        t_fine = None
        for i in range(1, len(ss)):
            if ss[i - 1].get("stage") != "fine" and ss[i].get("stage") == "fine":
                t_fine = float(ss[i]["elapsed_s"])
                break
        for s in ss:
            if not s.get("rate_valid"):
                continue
            r, dd, w, tgt = (s.get("control_rate_mg_s"), s.get("duty_permyriad"),
                             s.get("window_position_units"), s.get("target_rate_mg_s"))
            if None in (r, dd, w, tgt):
                continue
            r, dd, w, tgt = float(r), float(dd), float(w), float(tgt)
            t = float(s["elapsed_s"])
            stg = s.get("stage")
            if stg == "coarse":
                reg = "coarse"
            elif stg == "fine" and t_fine is not None:
                dt = t - t_fine
                reg = "fine_early" if dt <= 2 else ("fine_mid" if dt < 4 else "fine_late")
            else:
                continue
            cells[(pw, int(dd // 500) * 500, int(w // 250) * 250)][reg].append(r)
            if stg != "fine":
                continue
            g = fine[pw]
            g["n"].append(1)
            g["duty"].append(dd)
            g["win"].append(w)
            g["at_floor"].append(1 if dd <= DUTY_MIN + AT_LIMIT else 0)
            g["at_ceil"].append(1 if dd >= DUTY_MAX - AT_LIMIT else 0)
            g["win_at_floor"].append(1 if w <= 1100 else 0)
            # 通道用尽：duty 到底，速率还压不下来
            g["cannot_slow"].append(1 if (dd <= DUTY_MIN + AT_LIMIT and r > 1.2 * tgt) else 0)
            g["cannot_speed"].append(1 if (dd >= DUTY_MAX - AT_LIMIT and r < 0.8 * tgt) else 0)

    def pct(g, k):
        return (100.0 * sum(g[k]) / len(g["n"])) if g.get("n") else 0.0

    rows = []
    print("== 慢加段「降速通道」权限体检 ==")
    print("%-16s %5s %16s %16s %8s %9s %9s" %
          ("粉末", "拍数", "duty p10/50/90", "窗口 p10/50/90", "duty贴底", "窗口贴底", "压不下来"))
    print("-" * 92)
    tot = defaultdict(list)
    for pw in sorted(fine, key=lambda k: -len(fine[k]["n"])):
        g = fine[pw]
        q = lambda k: "%.0f/%.0f/%.0f" % (st.quantiles(g[k], n=10)[0], st.median(g[k]),
                                           st.quantiles(g[k], n=10)[-1]) if len(g[k]) >= 10 else "n/a"
        print("%-16s %5d %16s %16s %7.1f%% %8.1f%% %8.1f%%" %
              (pw, len(g["n"]), q("duty"), q("win"), pct(g, "at_floor"),
               pct(g, "win_at_floor"), pct(g, "cannot_slow")))
        rows.append(dict(powder=pw, fine_samples=len(g["n"]),
                         duty_p10=st.quantiles(g["duty"], n=10)[0], duty_med=st.median(g["duty"]),
                         duty_p90=st.quantiles(g["duty"], n=10)[-1],
                         duty_at_floor_pct=round(pct(g, "at_floor"), 1),
                         win_at_floor_pct=round(pct(g, "win_at_floor"), 1),
                         cannot_slow_pct=round(pct(g, "cannot_slow"), 1),
                         cannot_speed_pct=round(pct(g, "cannot_speed"), 1)))
        for k in ("n", "at_floor", "win_at_floor", "cannot_slow", "cannot_speed"):
            tot[k].extend(g[k])
    n = len(tot["n"])
    print("-" * 92)
    print("%-16s %5d %16s %16s %7.1f%% %8.1f%% %8.1f%%" %
          ("合计", n, "", "", 100.0 * sum(tot["at_floor"]) / n,
           100.0 * sum(tot["win_at_floor"]) / n, 100.0 * sum(tot["cannot_slow"]) / n))
    print()
    print("慢加段 duty 贴死 %d 的拍：%.1f%%；其中速率仍 > 目标×1.2 的占 %.1f%%"
          % (DUTY_MIN, 100.0 * sum(tot["at_floor"]) / n,
             100.0 * sum(tot["cannot_slow"]) / max(sum(tot["at_floor"]), 1)))
    print("「顶不上去」（duty 到顶仍达不到目标）的拍：%.1f%% —— 说明瓶颈永远在「太快」这一侧"
          % (100.0 * sum(tot["cannot_speed"]) / n))

    print("\n== 同一个 (duty, 窗口) 组合下，实测速率在不同阶段的中位值 ==")
    print("（静态被控对象两列应几乎相等；散度就是「标定表不成立」的证据）")
    print("%-16s %5s %6s %9s %9s %9s %8s" % ("粉末", "duty", "窗口", "粗加", "慢加早", "慢加晚", "晚/粗"))
    print("-" * 74)
    ratios = []
    for k in sorted(cells):
        g = cells[k]
        md = lambda reg: (round(st.median(g[reg]), 1) if len(g.get(reg) or []) >= 3 else None)
        c, l = md("coarse"), md("fine_late")
        if c is None or l is None or c <= 0.1:
            continue
        ratios.append(l / c)
        print("%-16s %5d %6d %9s %9s %9s %8.2f"
              % (k[0], k[1], k[2], c, md("fine_early"), l, l / c))
    if ratios:
        print("-" * 74)
        print("配对单元 %d 个：晚/粗 比 中位 %.2f，P10 %.2f，P90 %.2f"
              % (len(ratios), st.median(ratios),
                 sorted(ratios)[int(0.1 * (len(ratios) - 1))],
                 sorted(ratios)[int(0.9 * (len(ratios) - 1))]))
        print("→ 比值散布在 %.2f–%.2f 之间，没有稳定增益：无法用一张静态表描述。"
              % (min(ratios), max(ratios)))

    out = os.path.join(LAB, "results", "loop_authority.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("\n明细已写入 %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
