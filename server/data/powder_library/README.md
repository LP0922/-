# 粉体工作空间库 (Powder–Head Operating Space Library)

开放式粉末特征档案库，每种粉末一个 `.json` 文件。方法生成器
(`method_generator.py`) 从这里生成 `data/control_profiles` 下的运行时草稿配置。

## 档案格式

```json
{
  "powder_name": "粉末名称",
  "head_type": "gravity-cone-vibration",    // 加粉头类型
  "created_at": "ISO 8601",
  "updated_at": "ISO 8601",

  // ── 单点探针摘要（快速特征） ──
  "probe_40hz": {
    "frequency_hz": 40, "duty_permyriad": 2000, "window_units": 250,
    "startup_delay_s": 1.1,
    "steady_rate_mg_s": 35.5,
    "rate_cv_pct": 24.3,
    "tail_mass_mg": 34.0,
    "settling_time_s": 2.2,
    "source": "fingerprint|manual|estimated"
  },

  // ── 多点扫描网格（工作空间核心） ──
  "scan_grid": [
    {
      "frequency_hz": 40, "duty_permyriad": 2000, "window_units": 250,
      "status": "measured",          // measured | pending | unreliable
      "mean_rate_mg_s": 35.5,
      "cv_pct": 24.3,
      "startup_delay_s": 1.13,
      "is_stable": true,
      "notes": ""
    }
  ],

  // ── 安全／危险区域（由扫描数据推导） ──
  "safe_coarse_region": {
    "frequency_hz": [40, 65], "duty_permyriad": [1600, 2400],
    "window_units": [200, 300],
    "expected_rate_range_mg_s": [20, 50],
    "max_cv_pct": 30
  },
  "safe_fine_region": {
    "frequency_hz": [40, 55], "duty_permyriad": [1000, 1600],
    "window_units": [200, 300],
    "expected_rate_range_mg_s": [5, 15],
    "max_cv_pct": 25
  },
  "danger_zones": [
    {"frequency_hz": [70, 80], "reason": "共振区，振动剧烈不稳定"}
  ],
  "path_dependency": {
    "high_to_low_stable": true,
    "stationary_to_low_possible": true,
    "notes": "从高频切回低频无异常"
  },

  // ── 尾量特性 ──
  "tail_behavior": {
    "mean_tail_mg": 34.0,
    "tail_stdev_mg": 5.0,
    "correlates_with_stop_rate": false,
    "notes": "尾量基本恒定"
  },

  // ── 推荐参数映射 ──
  "recommended_preset_id": "60hz-p150",
  "recommended_controller": {
    "duty_step_per_update": 30,
    "emergency_duty_step_per_update": 80,
    "position_feedback_enabled": false,
    "maximum_flow_rate_mg_s": 120.0
  },
  "recommended_profiles": {
    "100": { "coarse_rate_mg_s": 25, "fine_rate_mg_s": 15, "precision_rate_mg_s": 10,
             "precision_start_remaining_mg": 40, "tail_taper_start_remaining_mg": 70,
             "tail_taper_end_remaining_mg": 15 },
    "300": { "coarse_rate_mg_s": 30, "fine_rate_mg_s": 18, "precision_rate_mg_s": 12,
             "precision_start_remaining_mg": 60, "tail_taper_start_remaining_mg": 90,
             "tail_taper_end_remaining_mg": 15 },
    "500": { "coarse_rate_mg_s": 35, "fine_rate_mg_s": 20, "precision_rate_mg_s": 14,
             "precision_start_remaining_mg": 70, "tail_taper_start_remaining_mg": 110,
             "tail_taper_end_remaining_mg": 15 }
  },

  // ── 失效模式标签 ──
  "failure_modes": ["clogging", "startup_delay_long"],
  "classification_tags": ["sticky"]
}
```

## 数据来源标注

| source 值 | 含义 |
|---|---|
| `fingerprint` | 粉末指纹探针（40Hz 单点）正式采集 |
| `constant_rate` | 定速出粉测试采集 |
| `dispense_trace` | 从闭环加粉日志反推 |
| `manual` | 手工标注（工程师经验判断） |
| `estimated` | 从相似粉体估算 |
| `pending` | 待扫描补测 |

## 工作流程

1. **建库**：对4种参考粉逐一执行多点扫描（计划第2周 D6-D9）
2. **新粉匹配**：新粉跑快速探针（3-5频点×2占空比）→ 提取特征向量 →
   与库内所有粉体计算欧氏距离 → 继承最近邻的推荐参数
3. **持续扩充**：每加入一种新粉，其工作空间写入库，丰富匹配基础
4. **生成草稿**：运行 `python scripts/generate_control_profile.py POWDER_ID`
   预览候选配置；确认后使用 `--write --force` 更新草稿
5. **实验验证**：按 `docs/control-profile-experiment-steps.md` 验证锚点和插值目标
