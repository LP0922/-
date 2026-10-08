# 任意质量闭环加粉 — 设计方案

**日期**：2026-08-10
**状态**：已批准

## 目标

在现有闭环加粉系统（仅支持 100/300/500 mg）上扩展为支持 50–1000 mg 任意整数质量，用户在粉末指纹选型后输入任意质量，程序自动匹配参数并执行加粉。

## 范围

### 范围内

- 闭环加粉目标质量从 {100, 300, 500} 扩展为 [50, 1000] 任意整数
- 非锚点目标的控制器参数通过线性插值生成
- 前端新增自定义质量输入框，三个固定目标按钮保留
- 验收容差从 `[-10, +15]` 改为 `[-10, +10]` mg
- 预设根据粉末指纹自动匹配，用户可手动覆盖
- 批量队列同步放宽 target_mg 限制
- 向后兼容：历史日志、固定目标按钮、兼容端点均不受影响

### 范围外

- 不新增 API 端点
- 不修改 ContinuousFeedbackController 核心算法
- 不修改粉末指纹探针/分类逻辑
- 不改变定速出粉、连续收敛、窗口 PID 等其他测试模式

## 架构

```
前端（device_dashboard.py）
  │
  │ 自定义输入框（50–1000 mg）或固定按钮（100/300/500）
  │ → selectedDispenseTarget（动态更新）
  │ → POST /api/dispense/start {target_mg, preset_id, initial}
  │
  ▼
后端（device_control_server.py）
  │
  │ start_dispense(payload):
  │   1. target_mg = int(payload["target_mg"])     # 50-1000 校验
  │   2. profile = interpolate_profile(target_mg)   # 新函数
  │   3. powder_overrides 从 _powder_session 获取   # 已有逻辑
  │   4. acceptance = target_mg ± 10 mg             # 对称容差
  │   5. 创建 ContinuousFeedbackController
  │
  ▼
插值引擎（feedback_profiles.py）
  │
  │ interpolate_profile(target_mg):
  │   锚点: 100, 300, 500 mg（DISPENSE_TARGET_PROFILES）
  │   方法: 相邻锚点间线性插值，边界外线性外推 + clamp
  │   返回: dict（coarse_rate, fine_rate, precision_rate, ...）
  │
  ▼
ContinuousFeedbackController（已有，不改动）
  │
  ▼
LA10 + AT8811C（已有，不改动）
```

## 参数插值策略

### 锚点

`DISPENSE_TARGET_PROFILES` 中现有的 100、300、500 mg 作为插值锚点，不做结构性变更。

### 插值公式

```
对每个标量参数 p（如 coarse_rate_mg_s）：

给定 target_mg = t，找到锚点中 ≤ t 的最大 key a 和 ≥ t 的最小 key b：

  if t < 100:  用 100→300 斜率从 100 向内插
      p(t) = p(100) - (p(300) - p(100)) / (300 - 100) * (100 - t)

  elif t == a:  p(t) = p(a)                              # 精确命中

  elif t > 500:  用 300→500 斜率外推
      p(t) = p(500) + (p(500) - p(300)) / (500 - 300) * (t - 500)

  else:  标准线性插值
      p(t) = p(a) + (p(b) - p(a)) / (b - a) * (t - a)
```

### 插值的参数

从 `DISPENSE_TARGET_PROFILES` 每个 entry 中取以下 6 个可插值字段：

| 字段 | 含义 |
|---|---|
| `coarse_rate_mg_s` | 粗加阶段目标速率 |
| `fine_rate_mg_s` | 精调阶段目标速率 |
| `precision_rate_mg_s` | 精度阶段目标速率 |
| `precision_start_remaining_mg` | 精度阶段起始剩余质量 |
| `tail_taper_start_remaining_mg` | 尾量收敛起始剩余质量 |
| `tail_taper_end_remaining_mg` | 尾量收敛结束剩余质量 |

不参与插值的参数（由粉末分类决定）：
- `maximum_flow_rate_mg_s` — 取自粉末分类参数
- `fixed_tail_mass_mg` — 取自粉末分类参数
- `force_stop_offset_mg` — 取自粉末分类参数

### 约束边界

| 参数 | 下限 | 上限 |
|---|---|---|
| `coarse_rate_mg_s` | 5.0 | 50.0 |
| `fine_rate_mg_s` | 3.0 | 30.0 |
| `precision_rate_mg_s` | 2.0 | 20.0 |
| `precision_start_remaining_mg` | 10.0 | 无上限 |
| `tail_taper_start_remaining_mg` | 15.0 | 无上限 |
| `tail_taper_end_remaining_mg` | 3.0 | 无上限 |

若 `tail_taper_start` ≤ `tail_taper_end`，自动调整 `tail_taper_end = tail_taper_start * 0.3`。

## 验收容差

`DISPENSE_ALLOWED_UNDERWEIGHT_MG` 和 `DISPENSE_ALLOWED_OVERWEIGHT_MG` 统一为 **10.0 mg**。

对于 50 mg 的小目标，10 mg 的容差占比偏大（±20%），但基于当前硬件精度不做更紧约束，保持安全保守。

硬上限（触发 runtime error）：`acceptance_max_mg + 5 mg`。

## 前端 UI 改动

### 布局

```
┌─ 500 mg 闭环加粉 ─────────────────────────────────────┐
│ 粉末：小苏打 (High-flow)  [探针]  [分类切换]            │
│────────────────────────────────────────────────────────│
│ 目标质量                                                │
│ [100 mg] [300 mg] [500 mg]                              │  ← 保留
│ 自定义质量 [___423___] mg                               │  ← 新增
│────────────────────────────────────────────────────────│
│ 起始参数（预设按钮 + 手动微调输入框）                      │  ← 保留
│ [+ 添加到批量队列]                                       │  ← 保留
│────────────────────────────────────────────────────────│
│ [天平标零]  [启动 423 mg 加粉]  [停止任务]              │  ← 文本动态更新
│ 验收 413–433 mg                                         │  ← 动态更新
└────────────────────────────────────────────────────────┘
```

### 交互行为

1. **固定目标按钮**：点击 100/300/500，同步更新输入框的 value，按钮高亮
2. **自定义输入框**：手动输入任意值 → 三个固定按钮取消 selected 状态 → 按钮文本和验收范围实时更新
3. **输入框校验**：空或 < 50 或 > 1000 → 启动按钮变灰，提示"请输入 50–1000 mg 之间的质量"
4. **启动按钮文本**：显示为 `启动 ${target} mg 加粉`
5. **面板标题**：显示为 `${target} mg 闭环加粉`

### 预设自动匹配

- 已加载粉末指纹 → 使用粉末分类指定的 preset_id → 高亮对应预设按钮
- 未加载指纹 → 默认 `fast-80hz-p200`，提示用户先选择粉末类型
- 用户可手动点击其他预设覆盖自动选择
- 自定义目标时不过滤预设按钮（全部显示）

### CSS 新增

- 自定义质量输入框样式：`.dispense-custom-target input`，宽度 80px，高度 32px
- 与固定按钮同行的 label 样式

## 批量队列兼容

### 服务端校验放宽

`start_dispense_batch()` 中：
```python
# 旧：if target_mg not in (100, 300, 500):
# 新：
if not isinstance(target_mg, int) or target_mg < 50 or target_mg > 1000:
    raise ValueError(...)
```

### 前端批量队列

`add-dispense-to-batch` 按钮的 `target_mg` 已从 `selectedDispenseTarget` 读取，自定义输入框更新该变量即可适用。

## 涉及修改的文件

| 文件 | 改动 |
|---|---|
| `src/powder_sampling_control/dispensing_algorithm/feedback_profiles.py` | 新增 `interpolate_profile()`；修改容差常量；保留 `DISPENSE_TARGET_PROFILES` 不变 |
| `scripts/device_control_server.py` | `start_dispense()` 改用 `interpolate_profile()`；`start_dispense_batch()` 放宽校验；容差常量引用更新 |
| `scripts/device_dashboard.py` | 新增自定义质量输入框；`selectedDispenseTarget` 同步逻辑；预设匹配扩展；验收范围动态更新；面板标题/按钮文本动态更新 |
| `scripts/device_control_server.py`（HTTP 路由） | 无需新增端点 |

## 测试要点

1. **插值正确性**：验证 50/75/150/200/400/750/1000 mg 的插值结果在预期范围内
2. **边界行为**：50 mg 和 1000 mg 不抛异常，< 50 和 > 1000 正确报错
3. **固定目标按钮**：点击 100/300/500 行为与改造前一致
4. **自定义输入框**：输入 423 → 按钮文本变为「启动 423 mg 加粉」→ 验收范围 413–433
5. **粉末指纹联动**：加载 High-flow 粉末 → 自动选 slow-10hz-p100 → 输入 423 不报错
6. **批量队列**：自定义目标加入队列 → 批量执行不报错
7. **向后兼容**：`/api/dispense-500mg/start` 仍然可用；历史日志列表正常显示

## 非目标

- 不改动 `ContinuousFeedbackController` 算法逻辑
- 不新增 MQTT/WebSocket 等通信协议
- 不引入新 Python 依赖
- 1000 mg 以上目标暂不支持（超出当前硬件/算法验证范围）
