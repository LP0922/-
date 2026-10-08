# 字段字典 — server/logs 里的 run 数据

每个 run 三件套（`run_id` 为例子 `large-dispense-8000mg-20260924_110528-3e6dd9`）：

| 文件 | 内容 |
|---|---|
| `feedback_dispense_<run_id>.json` | 配置 + 结果 + **内嵌逐拍遥测** `samples` |
| `feedback_dispense_<run_id>_samples.csv` | 与 `samples` 同源的逐拍遥测（表格版） |
| `feedback_dispense_<run_id>_post_stop_samples.csv` | 停机后的沉降采样 |

> `run_id` 内含 `YYYYMMDD_HHMMSS`，日期口径与前端「试验记录」一致。
> 表格里的 `Run ID` 列就是它（如 `dispense-200mg-20260923_104956-bf7c51`）。

---

## 1. 配置 JSON 顶层字段

### 标识与目标
| 字段 | 说明 |
|---|---|
| `run_id` | 运行唯一标识 |
| `test_type` | `feedback_dispense`（本目录只处理这种） |
| `powder_id` / `powder_name` | 粉末标识 / 显示名（**显示名可能与表格人工口径不同，分组用表格名**） |
| `target_mass_mg` | 目标质量 |
| `hard_limit_mg` | 硬上限（到即强停） |
| `preset_id` | 预设档位（如 `large-80hz`） |

### 初始与轮廓参数
| 字段 | 说明 |
|---|---|
| `initial_parameters` | `frequency_hz` / `duty_permyriad` / `window_position_units` |
| `profile` | `coarse_rate_mg_s`、`fine_rate_mg_s`、`precision_rate_mg_s`、<br>`precision_start_remaining_mg`、`tail_taper_start_remaining_mg`、<br>`tail_taper_end_remaining_mg`、`maximum_flow_rate_mg_s` |

### 控制律配置（改算法主要动这里）
| 字段 | 说明 |
|---|---|
| `algorithm_version` | 算法版本（本例 `predictive-stop-v3-water-loss-agent-2-fast-tail`） |
| `predictive_stop_config` | `enabled`、**`prediction_horizon_s`**、`fixed_tail_mass_mg`、<br>**`target_offset_mg`**、`confirmation_samples`、`fast_stop_enabled`、<br>`fast_stop_rate_mg_s`、`fast_stop_confirmation_samples` |
| `flow_hold_config` | 流量保持：`duty_ceiling_permyriad`、`mass_gain_window_s`、<br>`minimum_gain_mg`、`response_check_s`、`minimum_rate_improvement_mg_s` |
| `stall_recovery_config` | 卡粉恢复：`observation_window_s`、`minimum_gain_mg`、<br>`rate_threshold_mg_s`、`resume_rate_mg_s`、`retry_s` |
| `tail_pulse_config` | 尾脉冲：`start_remaining_mg`、窗口步进与上下限等 |
| `final_settle_rule` | 终值判定：`minimum_wait_s`、`continuous_stable_s`、`max_spread_mg` |

### 设备快照与结果
| 字段 | 说明 |
|---|---|
| `window_before` / `window_after` | 闸门位置、温度、电流、故障位等前后快照 |
| `tare_before` / `tare_after` | 去皮前后天平读数 |
| `vibration_started` | 振动启停记录 |
| `large_prefeed_handoff` | **大重量专用**：`reserve_mg`、`vibration_stopped_at_mass_mg`、<br>`settled_mass_mg`、`closed_loop_initial`、窗口单位等 |
| `stop_sample` | 停机那一拍的摘要 |
| `stop_reason` | 停机原因文本（`predictive_tail` / `safety_stop` / `force_stop` 等） |
| `final_mass_mg` | **最终稳定质量**（分析主指标） |
| `acceptance_min_mg` / `acceptance_max_mg` | 验收窗口（10 mg 口径 = 目标 ±10） |
| `acceptance_error` | 未通过时的说明 |
| `actual_duration_s` | 实际耗时（秒） |
| `result` | `passed` / `failed` |
| `finished_at_utc` | 结束时间 |

---

## 2. 逐拍遥测字段（`samples[]` / `_samples.csv` 每行）

| 字段 | 说明 |
|---|---|
| `elapsed_s` | 已运行秒数 |
| `measurement_read_s` | 本次称重读取耗时 |
| `mass_mg` | 当前**原始**质量读数 |
| `filtered_mass_mg` | 滤波后质量 |
| `predicted_mass_mg` | 预测质量 |
| `rate_mg_s` | 实测速率 |
| `predicted_rate_mg_s` | 预测速率 |
| `control_rate_mg_s` | **控制用速率**（停机投影的输入之一） |
| `acceleration_mg_s2` | 加速度（**投影输入之一**） |
| `jerk_mg_s3` | 加加速度 |
| `estimated_tail_mg` | **估计尾巴质量** = `fixed_tail + rate·H + ½·accel·H²` |
| `projected_stop_mass_mg` | **预测停机落点** = `mass + estimated_tail` |
| `predictive_stop_candidate` | 是否已满足预测停候选条件 |
| `stop_confirmation_count` / `stop_confirmation_required` | 连续确认计数 / **当拍实际要求的确认数**（回放要用这个，不是配置值） |
| `rate_valid` | 速率是否有效 |
| `stall_recovery_active` / `stall_recovery_attempt` | 是否在卡粉恢复中 / 第几次尝试 |
| `large_low_flow_recovery` / `large_closed_loop_low_flow_recovery` | 大重量低流量恢复标记 |
| `stage` | 当前阶段（如 `coarse` / `fine` / `settle`） |
| `target_rate_mg_s` | 目标速率 |
| `frequency_hz` / `duty_permyriad` / `window_position_units` | 当拍执行器参数（占空比为**万分值**，2000 = 20%） |
| `stable` / `status_word` | 天平稳定标志 / 状态字 |
| `reason` | 当拍触发说明 |

---

## 3. 复现停机判定所需的最小输入

只用遥测里的这几列就能离线重算「换个参数会停在哪」：

```
mass_mg, control_rate_mg_s, acceleration_mg_s2,
rate_valid, stop_confirmation_required, elapsed_s
```

配合常数：`prediction_horizon_s`、`fixed_tail_mass_mg`、`target_offset_mg`。
投影公式与控制器一致：

```
estimated_tail = fixed_tail + control_rate·H + 0.5·max(0, accel)·H²
projected      = mass_mg + estimated_tail
```

见 `tools/replay_stop.py` 的 `est_tail()` / `replay()`。
