# lab — 算法迭代试验台

一个**实验性目录**，用来放和「加粉控制算法」相关的想法、脚本与离线分析结果。
所有内容只针对一个问题：**手上这批数据够不够把算法改好，怎么改。**

## 范围（重要）

只处理 `../试验记录_20260923-20260924_含最终质量.xlsx` 里那张表——
**126 条**已落最终质量的 `feedback_dispense` 记录（20 / 30 mg 容差口径同表）。
全量日志有 2630 个 run，**默认不碰**；需要时才用 `--index none` 显式放开。

这 126 条的原始日志（配置 JSON + 逐拍遥测 CSV）都在 `../server/logs/`，
本目录通过 `run_id` 与它们关联（见 `data/runs_126.csv`）。

## 目录结构

```
lab/
├── README.md                 本文件
├── IDEAS.md                  ★ 想法文件：可迭代的方向清单（含依据与验证方式）
├── FEASIBILITY.md            ★ 可行性评估：结论 + 证据数字 + 边界
├── ideas/                    专题设想（单主题深挖）
│   └── stage-transition-smoothing.md   快加→慢加 平滑过渡方案
├── notes/
│   └── DATA_DICT.md          字段字典：日志里每个字段是什么
├── tools/                    测试文件（可复跑脚本）
│   ├── select_126.py         建立 126 条专属索引
│   ├── replay_stop.py        止损律离线回放 / 参数扫描
│   ├── audit_features.py     按粉末审计（残差、视界敏感度）
│   ├── transition_sag.py     过渡段速率瞬态：过冲 / 多喂量 / 恢复时间
│   ├── loop_authority.py     降速通道权限体检：duty 饱和 + 同 duty 产率散度
│   └── build_index.py        〔可选〕扫全量 2630 run 的扁平索引，仅探查时用
├── data/
│   └── runs_126.csv          126 条 × 标签 × 遥测可用性（唯一数据入口）
└── results/                  脚本产出（可随时重算删除）
    ├── replay_validate.csv
    ├── audit_by_powder.csv
    ├── sweep_126.txt
    ├── transition_sag.csv
    ├── loop_authority.csv / .txt
    └── ...
```

## 快速开始

```bash
PY="C:/Users/16218/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
cd "C:/Users/16218/Desktop/powder/powder/lab"

$PY tools/select_126.py         # 1) 重建 126 条索引（表格改了就跑）
$PY tools/replay_stop.py        # 2) 回放校验 + 预测残差分布
$PY tools/replay_stop.py --sweep        # 3) 止损参数网格扫描
$PY tools/audit_features.py     # 4) 按粉末看残差与视界敏感度
$PY tools/transition_sag.py     # 5) 过渡段：过冲 / 多喂量 / 恢复时间
$PY tools/loop_authority.py     # 6) 慢加段 duty 饱和 + 同 duty 产率散度
$PY tools/replay_stop.py --run-id <run_id>   # 单条明细
```

## 为什么这份分析可信

控制器每次停机决策是**纯函数**——输入只有当拍的 `mass_mg / control_rate_mg_s /
acceleration_mg_s2` 和一组常数参数，而这些**逐拍全部落盘**。所以把同一段遥测喂给
改过的参数，就能复现「那一次会停在哪」，不需要动设备。校验方式：用记录里的原参数
回放，停机点应与实际一致（实测 **81% 完全一致**，**91% 至少触发了止损**）。

反事实推算里有一步是保守假设：新落点 ≈ 新停机点的 `projected_stop_mass_mg` +
该粉末**历史残差中位数**。落粉尾巴对停机时刻不是线性的，所以这只能当**筛选器**用，
最终结论必须回到设备上跑 A/B。

## 注意

- `data/runs_126.csv` 是分析入口。改表格（加行/删行/改名）后要重跑 `select_126.py`，
  否则索引与「试验记录」会脱节。
- 表格里粉末名是人工口径（如「失水剂2」曾被手工改名为「失水剂1」），
  日志 JSON 里仍是原始 `powder_name`。分组一律用**索引里的显示名**。
