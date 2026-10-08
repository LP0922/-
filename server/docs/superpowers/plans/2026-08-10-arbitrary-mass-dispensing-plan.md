# 任意质量闭环加粉 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 扩展闭环加粉系统，支持 50–1000 mg 任意整数质量，通过线性插值生成控制器参数。

**Architecture:** 在 `feedback_profiles.py` 新增 `interpolate_profile()` 函数替代 `dispense_plan()` 的硬编码限制；服务端 `start_dispense()` / `start_dispense_batch()` 调用新函数；前端新增自定义质量输入框，三个固定目标按钮保留。

**Tech Stack:** Python 3（pyserial, http.server）, vanilla JavaScript（无框架）

## Global Constraints

- 目标质量范围：50–1000 mg，整数
- 验收容差：±10 mg（DISPENSE_ALLOWED_UNDERWEIGHT_MG = DISPENSE_ALLOWED_OVERWEIGHT_MG = 10.0）
- 插值锚点：DISPENSE_TARGET_PROFILES 中 100/300/500 mg
- 不新增 API 端点
- 不修改 ContinuousFeedbackController 核心算法
- 不改动定速出粉、连续收敛、窗口 PID 等其他模式
- 向后兼容：`/api/dispense-500mg/start` 兼容端点保持不动

---

### Task 1: `interpolate_profile()` 函数

**Files:**
- Modify: `src/powder_sampling_control/dispensing_algorithm/feedback_profiles.py`（新增函数）
- Create: `tests/test_interpolate_profile.py`

**Interfaces:**
- Produces: `interpolate_profile(target_mg: int) -> dict` — 返回与 DISPENSE_TARGET_PROFILES entry 相同 key 的 profile dict
- Produces: `validate_dispense_target(target_mg: int) -> None` — 校验 50–1000，不在范围抛 ValueError

- [ ] **Step 1: 编写 `interpolate_profile()` 的单元测试**

```python
"""Tests for arbitary-mass profile interpolation."""
import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from powder_sampling_control.dispensing_algorithm.feedback_profiles import (
    DISPENSE_TARGET_PROFILES,
    interpolate_profile,
    validate_dispense_target,
)

# ── anchor points: exact matches ──

def test_interpolate_exact_100():
    profile = interpolate_profile(100)
    for key in DISPENSE_TARGET_PROFILES[100]:
        assert profile[key] == pytest.approx(DISPENSE_TARGET_PROFILES[100][key])

def test_interpolate_exact_300():
    profile = interpolate_profile(300)
    for key in DISPENSE_TARGET_PROFILES[300]:
        assert profile[key] == pytest.approx(DISPENSE_TARGET_PROFILES[300][key])

def test_interpolate_exact_500():
    profile = interpolate_profile(500)
    for key in DISPENSE_TARGET_PROFILES[500]:
        assert profile[key] == pytest.approx(DISPENSE_TARGET_PROFILES[500][key])

# ── interpolation between anchors ──

def test_interpolate_200_midpoint():
    """200 is halfway between 100 and 300."""
    profile = interpolate_profile(200)
    p100 = DISPENSE_TARGET_PROFILES[100]
    p300 = DISPENSE_TARGET_PROFILES[300]
    for key in ("coarse_rate_mg_s", "fine_rate_mg_s", "precision_rate_mg_s",
                "precision_start_remaining_mg", "tail_taper_start_remaining_mg",
                "tail_taper_end_remaining_mg"):
        expected = p100[key] + (p300[key] - p100[key]) * (200 - 100) / (300 - 100)
        assert profile[key] == pytest.approx(expected)

def test_interpolate_400_between_300_500():
    profile = interpolate_profile(400)
    p300 = DISPENSE_TARGET_PROFILES[300]
    p500 = DISPENSE_TARGET_PROFILES[500]
    for key in ("coarse_rate_mg_s", "fine_rate_mg_s", "precision_rate_mg_s",
                "precision_start_remaining_mg", "tail_taper_start_remaining_mg",
                "tail_taper_end_remaining_mg"):
        expected = p300[key] + (p500[key] - p300[key]) * (400 - 300) / (500 - 300)
        assert profile[key] == pytest.approx(expected)

# ── extrapolation below 100 ──

def test_interpolate_75_below_100():
    """Extrapolate downward using 100→300 slope."""
    profile = interpolate_profile(75)
    p100 = DISPENSE_TARGET_PROFILES[100]
    p300 = DISPENSE_TARGET_PROFILES[300]
    slope = (p300["coarse_rate_mg_s"] - p100["coarse_rate_mg_s"]) / (300 - 100)
    expected_coarse = p100["coarse_rate_mg_s"] - slope * (100 - 75)
    assert profile["coarse_rate_mg_s"] == pytest.approx(expected_coarse)

# ── extrapolation above 500 ──

def test_interpolate_750_above_500():
    """Extrapolate upward using 300→500 slope."""
    profile = interpolate_profile(750)
    p300 = DISPENSE_TARGET_PROFILES[300]
    p500 = DISPENSE_TARGET_PROFILES[500]
    slope = (p500["coarse_rate_mg_s"] - p300["coarse_rate_mg_s"]) / (500 - 300)
    expected_coarse = p500["coarse_rate_mg_s"] + slope * (750 - 500)
    assert profile["coarse_rate_mg_s"] == pytest.approx(expected_coarse)

# ── boundary values ──

def test_interpolate_50_minimum():
    profile = interpolate_profile(50)
    assert profile["coarse_rate_mg_s"] >= 5.0
    assert profile["fine_rate_mg_s"] >= 3.0
    assert profile["precision_rate_mg_s"] >= 2.0

def test_interpolate_1000_maximum():
    profile = interpolate_profile(1000)
    assert profile["coarse_rate_mg_s"] <= 50.0
    assert profile["fine_rate_mg_s"] <= 30.0
    assert profile["precision_rate_mg_s"] <= 20.0

# ── clamp guard: tail_taper_end < tail_taper_start ──

def test_tail_taper_constraint():
    """If interpolation makes tail_taper_end >= tail_taper_start, clamp it."""
    profile = interpolate_profile(50)
    assert profile["tail_taper_end_remaining_mg"] < profile["tail_taper_start_remaining_mg"]

# ── validate_dispense_target ──

def test_validate_valid_targets():
    validate_dispense_target(50)
    validate_dispense_target(500)
    validate_dispense_target(1000)

def test_validate_below_range():
    with pytest.raises(ValueError, match="50"):
        validate_dispense_target(49)

def test_validate_above_range():
    with pytest.raises(ValueError, match="1000"):
        validate_dispense_target(1001)

def test_validate_not_integer():
    with pytest.raises(ValueError):
        validate_dispense_target("abc")
```

- [ ] **Step 2: 运行测试确认全部失败**

```powershell
py -3 -m pytest tests/test_interpolate_profile.py -v
```

预期：全部 FAIL（函数尚未定义）

- [ ] **Step 3: 在 `feedback_profiles.py` 中实现 `interpolate_profile()` 和 `validate_dispense_target()`**

在 `feedback_profiles.py` 文件末尾、`dispense_plan()` 函数之后添加：

```python
# ── arbitrary-mass interpolation ──

# Interpolatable scalar fields within DISPENSE_TARGET_PROFILES entries.
_INTERPOLATABLE_KEYS = (
    "coarse_rate_mg_s",
    "fine_rate_mg_s",
    "precision_rate_mg_s",
    "precision_start_remaining_mg",
    "tail_taper_start_remaining_mg",
    "tail_taper_end_remaining_mg",
)

# Per-field clamp bounds (min, max).
_INTERPOLATION_CLAMPS = {
    "coarse_rate_mg_s": (5.0, 50.0),
    "fine_rate_mg_s": (3.0, 30.0),
    "precision_rate_mg_s": (2.0, 20.0),
    "precision_start_remaining_mg": (10.0, None),
    "tail_taper_start_remaining_mg": (15.0, None),
    "tail_taper_end_remaining_mg": (3.0, None),
}

# Sorted anchor masses from DISPENSE_TARGET_PROFILES.
_ANCHOR_MASSES = sorted(DISPENSE_TARGET_PROFILES.keys())


def _linear_interpolate(target, anchors, values):
    """Linearly interpolate *values* at *target* between *anchors*.

    If *target* is below the smallest anchor, extrapolate downward using
    the slope of the first anchor pair.  If above the largest anchor,
    extrapolate upward using the slope of the last anchor pair.
    """
    if target in anchors:
        idx = anchors.index(target)
        return values[idx]

    if target < anchors[0]:
        # extrapolate below: use slope between anchors[0] and anchors[1]
        slope = (values[1] - values[0]) / (anchors[1] - anchors[0])
        return values[0] - slope * (anchors[0] - target)

    if target > anchors[-1]:
        # extrapolate above: use slope between anchors[-2] and anchors[-1]
        slope = (values[-1] - values[-2]) / (anchors[-1] - anchors[-2])
        return values[-1] + slope * (target - anchors[-1])

    # interior interpolation
    for i in range(len(anchors) - 1):
        if anchors[i] <= target <= anchors[i + 1]:
            frac = (target - anchors[i]) / (anchors[i + 1] - anchors[i])
            return values[i] + (values[i + 1] - values[i]) * frac

    raise RuntimeError(f"unexpected interpolation state for target={target}")  # unreachable


def interpolate_profile(target_mg):
    """Return a feedback profile dict for *target_mg* (50–1000).

    Fields from ``DISPENSE_TARGET_PROFILES`` that vary by target are
    linearly interpolated between the 100 / 300 / 500 mg anchors.
    ``maximum_flow_rate_mg_s`` is NOT interpolated — the caller must
    supply it from powder-classification parameters.
    """
    try:
        target = int(target_mg)
    except (TypeError, ValueError) as error:
        raise ValueError("target_mg must be an integer") from error

    if target < 50 or target > 1000:
        raise ValueError(
            f"target_mg must be between 50 and 1000, got {target}"
        )

    profile = {}
    for key in _INTERPOLATABLE_KEYS:
        anchor_values = [DISPENSE_TARGET_PROFILES[m][key] for m in _ANCHOR_MASSES]
        val = _linear_interpolate(target, _ANCHOR_MASSES, anchor_values)
        lo, hi = _INTERPOLATION_CLAMPS.get(key, (None, None))
        if lo is not None:
            val = max(lo, val)
        if hi is not None:
            val = min(hi, val)
        profile[key] = float(val)

    # Guard: tail_taper_end must be strictly less than tail_taper_start.
    tts = profile["tail_taper_start_remaining_mg"]
    tte = profile["tail_taper_end_remaining_mg"]
    if tte >= tts:
        profile["tail_taper_end_remaining_mg"] = tts * 0.3

    # maximum_flow_rate_mg_s is not interpolated — use a safe default.
    # The caller (start_dispense) overrides this from powder session.
    profile["maximum_flow_rate_mg_s"] = 30.0

    return profile


def validate_dispense_target(target_mg):
    """Raise ValueError if *target_mg* is not a valid dispense target."""
    try:
        target = int(target_mg)
    except (TypeError, ValueError) as error:
        raise ValueError("target_mg must be an integer between 50 and 1000") from error
    if target < 50 or target > 1000:
        raise ValueError(
            f"target_mg must be between 50 and 1000, got {target}"
        )
```

- [ ] **Step 4: 运行测试确认全部通过**

```powershell
py -3 -m pytest tests/test_interpolate_profile.py -v
```

预期：全部 PASS

- [ ] **Step 5: 提交**

```bash
git add tests/test_interpolate_profile.py src/powder_sampling_control/dispensing_algorithm/feedback_profiles.py
git commit -m "feat: add interpolate_profile() for arbitrary-mass dispense targets"
```

---

### Task 2: 更新验收容差常量

**Files:**
- Modify: `src/powder_sampling_control/dispensing_algorithm/feedback_profiles.py`

- [ ] **Step 1: 将 `DISPENSE_ALLOWED_OVERWEIGHT_MG` 从 15.0 改为 10.0**

在 `feedback_profiles.py` 第 84 行：

```python
# 旧：
DISPENSE_ALLOWED_OVERWEIGHT_MG = 15.0
# 新：
DISPENSE_ALLOWED_OVERWEIGHT_MG = 10.0
```

使 `DISPENSE_ALLOWED_UNDERWEIGHT_MG = 10.0` 保持不变。

- [ ] **Step 2: 更新 `device_dashboard.py` 中前端的 `DISPENSE_TARGET_LIMITS`**

在 `device_dashboard.py` 第 340 行：

```javascript
// 旧：
const DISPENSE_TARGET_LIMITS={100:[90,115],300:[290,315],500:[490,515]};
// 新：
const DISPENSE_TARGET_LIMITS={100:[90,110],300:[290,310],500:[490,510]};
```

- [ ] **Step 3: 提交**

```bash
git add src/powder_sampling_control/dispensing_algorithm/feedback_profiles.py scripts/device_dashboard.py
git commit -m "fix: change dispense overweight tolerance from +15 to +10 mg"
```

---

### Task 3: 更新 `start_dispense()` 支持任意目标

**Files:**
- Modify: `scripts/device_control_server.py`

**Interfaces:**
- Consumes: `interpolate_profile()` from `feedback_profiles.py` (Task 1)
- Consumes: `validate_dispense_target()` from `feedback_profiles.py` (Task 1)

- [ ] **Step 1: 更新 import 语句**

在 `device_control_server.py` 第 42–49 行，将 `dispense_plan` 替换为 `interpolate_profile, validate_dispense_target`：

```python
# 旧（第 42-49 行）:
from powder_sampling_control.dispensing_algorithm.feedback_profiles import (
    DISPENSE_ALLOWED_OVERWEIGHT_MG,
    DISPENSE_ALLOWED_UNDERWEIGHT_MG,
    DISPENSE_PRESETS,
    DISPENSE_TARGET_PROFILES,
    dispense_plan,
    powder_classification_params,
)

# 新:
from powder_sampling_control.dispensing_algorithm.feedback_profiles import (
    DISPENSE_ALLOWED_OVERWEIGHT_MG,
    DISPENSE_ALLOWED_UNDERWEIGHT_MG,
    DISPENSE_PRESETS,
    DISPENSE_TARGET_PROFILES,
    interpolate_profile,
    powder_classification_params,
    validate_dispense_target,
)
```

- [ ] **Step 2: 重写 `start_dispense()` 方法（第 197–257 行）**

将第 199 行的 `dispense_plan()` 替换为 `validate_dispense_target()` + `interpolate_profile()`，并添加 `maximum_flow_rate_mg_s` 从粉末分类覆盖：

```python
    def start_dispense(self, payload):
        """Start one dispense run with a common feedback controller (50–1000 mg)."""
        raw_target = payload.get("target_mg", DISPENSE_TARGET_MG)
        validate_dispense_target(raw_target)
        target_mg = int(raw_target)
        profile = interpolate_profile(target_mg)
        # If powder session is loaded, override profile params
        powder_overrides = {}
        if self._powder_session:
            profile = dict(profile)
            for key in ("maximum_flow_rate_mg_s",):
                if key in self._powder_session:
                    profile[key] = float(self._powder_session[key])
            # Apply category-specific target profile overrides
            cat_overrides = self._powder_session.get("profile_overrides", {})
            # Try exact target match first, fall back to nearest anchor
            target_overrides = cat_overrides.get(target_mg)
            if target_overrides is None:
                # find nearest anchor for overrides
                anchors = sorted(DISPENSE_TARGET_PROFILES.keys())
                nearest = min(anchors, key=lambda a: abs(a - target_mg))
                target_overrides = cat_overrides.get(nearest, {})
            for key in ("coarse_rate_mg_s", "fine_rate_mg_s",
                        "precision_start_remaining_mg", "tail_taper_start_remaining_mg",
                        "tail_taper_end_remaining_mg"):
                if key in target_overrides:
                    profile[key] = float(target_overrides[key])
            powder_overrides = {
                "fixed_tail_mass_mg": self._powder_session.get("fixed_tail_mass_mg", 3.0),
                "settle_confirmations_delta": self._powder_session.get("settle_confirmations_delta", 0),
                "dead_zone_multiplier": self._powder_session.get("dead_zone_multiplier", 1.0),
                "duty_step_per_update": self._powder_session.get("duty_step_per_update", 50),
                "emergency_duty_step_per_update": self._powder_session.get("emergency_duty_step_per_update", 200),
                "position_feedback_enabled": self._powder_session.get("position_feedback_enabled", False),
                "force_stop_offset_mg": self._powder_session.get("force_stop_offset_mg", 10.0),
            }
        preset_id = str(payload.get("preset_id", "fast-80hz-p200"))
        if preset_id in DISPENSE_PRESETS:
            initial = dict(DISPENSE_PRESETS[preset_id])
        else:
            initial = {"frequency_hz": 80, "duty_permyriad": 2000, "window_position_units": 200}
        requested_initial = payload.get("initial", {})
        if requested_initial is not None:
            if not isinstance(requested_initial, dict):
                raise ValueError("initial must be an object when supplied")
            for key in initial:
                if key in requested_initial:
                    initial[key] = int(requested_initial[key])
        validate_dispense_initial(initial)
        with self._test_lock:
            if self.snapshot()["test"].get("status") == "running":
                raise RuntimeError("a device task is already running")
            run_id = f"dispense-{target_mg}mg-{datetime.now().strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:6]}"
            self._cancel_event.clear()
            submitted = {
                "target_mg": target_mg,
                "preset_id": preset_id,
                "initial": initial,
                "acceptance_min_mg": target_mg - DISPENSE_ALLOWED_UNDERWEIGHT_MG,
                "acceptance_max_mg": target_mg + DISPENSE_ALLOWED_OVERWEIGHT_MG,
                "profile": profile,
            }
            self._set_test({"status": "running", "run_id": run_id, "submitted": submitted})
            worker = threading.Thread(
                target=self._run_feedback_dispense,
                args=(run_id, target_mg, preset_id, initial, profile, powder_overrides),
                daemon=True,
            )
            worker.start()
            return {"accepted": True, "run_id": run_id, "submitted": submitted}
```

- [ ] **Step 3: 提交**

```bash
git add scripts/device_control_server.py
git commit -m "feat: support arbitrary 50-1000mg targets in start_dispense()"
```

---

### Task 4: 更新批量接口

**Files:**
- Modify: `scripts/device_control_server.py`

- [ ] **Step 1: 放宽 `start_dispense_batch()` 的 target_mg 校验（第 541–543 行）**

```python
# 旧（第 541-543 行）：
            target_mg = int(params.get("target_mg", 500))
            if target_mg not in (100, 300, 500):
                raise ValueError(f"set [{idx}]: target_mg must be 100, 300, or 500, got {target_mg}")

# 新：
            target_mg = int(params.get("target_mg", 500))
            if not 50 <= target_mg <= 1000:
                raise ValueError(f"set [{idx}]: target_mg must be 50–1000, got {target_mg}")
```

- [ ] **Step 2: 更新 `_run_dispense_batch()` 中的 `dispense_plan` 调用（第 2292 行）**

```python
# 旧（第 2292 行）：
                _target_mg, profile = dispense_plan(target_mg)

# 新：
                profile = interpolate_profile(target_mg)
```

注意此处不再需要 `_target_mg` 变量（原 `dispense_plan` 返回 tuple，新函数只返回 dict），后续引用 `target_mg` 的地方不变。

- [ ] **Step 3: 提交**

```bash
git add scripts/device_control_server.py
git commit -m "feat: relax batch dispense target validation to 50-1000mg"
```

---

### Task 5: 前端自定义质量输入框

**Files:**
- Modify: `scripts/device_dashboard.py`

- [ ] **Step 1: 在 `dispenseConfig` HTML 中添加自定义质量输入框**

在 `device_dashboard.py` 第 343 行，修改 `dispenseConfig.innerHTML`，在目标按钮和起始参数之间插入自定义输入行：

将：
```javascript
dispenseConfig.innerHTML='<div class="label">目标质量</div><div id="dispense-target-control" ...></div><div class="label" style="margin-top:12px">本次起始参数</div>...'
```

改为：
```javascript
dispenseConfig.innerHTML='<div class="label">目标质量</div><div id="dispense-target-control" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px"><button class="preset-button" data-dispense-target="100">100 mg</button><button class="preset-button" data-dispense-target="300">300 mg</button><button class="preset-button selected" data-dispense-target="500">500 mg</button></div><div style="display:flex;align-items:center;gap:8px;margin-top:8px"><label style="font-size:12px;color:var(--muted)">自定义质量</label><input id="dispense-custom-target" type="number" min="50" max="1000" step="1" placeholder="50–1000" style="width:80px;height:32px;padding:0 8px;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--ink);font:inherit"><span style="font-size:12px;color:var(--muted)">mg</span></div><div class="label" style="margin-top:12px">本次起始参数</div><div class="dispense-inputs"><label>频率 Hz<input id="dispense-frequency" type="number" min="10" max="80" step="1" value="80"></label><label>占空比<input id="dispense-duty-input" type="number" min="1000" max="5000" step="50" value="2000"></label><label>窗口位置<input id="dispense-window-input" type="number" min="100" max="750" step="1" value="200"></label><label>重复次数<input id="dispense-repeats" type="number" min="1" max="20" step="1" value="1"></label></div><div style="display:flex;gap:8px;margin-top:8px"><button id="add-dispense-to-batch" class="command-button" style="width:auto">+ 添加到批量队列</button></div>';
```

- [ ] **Step 2: 更新 `updateDispensePanelLabels()` 使用动态验收范围**

修改 `updateDispensePanelLabels()`（第 353–358 行），处理非标准目标时动态计算验收范围：

```javascript
function updateDispensePanelLabels(){
  const target=selectedDispenseTarget;
  const minAccept=target-10;
  const maxAccept=target+10;
  dispensePanel.querySelector('h2').textContent=target+' mg 闭环加粉';
  el('start-500mg').textContent='启动 '+target+' mg 加粉';
  el('dispense-message').textContent='验收 '+minAccept+'–'+maxAccept+' mg；可在启动前调整起始参数';
}
```

- [ ] **Step 3: 更新 `filterPresetsByTarget()` — 自定义目标时显示全部预设并自动匹配**

修改 `filterPresetsByTarget()`（第 370–385 行）：

```javascript
function filterPresetsByTarget(target){
  const standardTargets=[100,300,500];
  let firstVisible=null;
  if(standardTargets.includes(target)){
    // Standard target: filter presets matching this target
    document.querySelectorAll('[data-preset]').forEach(btn=>{
      const pv=DISPENSE_PRESET_VALUES[btn.dataset.preset];
      const match=pv&&pv.target_mg===target;
      btn.style.display=match?'':'none';
      if(match&&!firstVisible)firstVisible=btn;
    });
  }else{
    // Custom target: show all presets, highlight the closest by target_mg
    let bestPreset=null;
    let bestDiff=Infinity;
    document.querySelectorAll('[data-preset]').forEach(btn=>{
      btn.style.display='';
      const pv=DISPENSE_PRESET_VALUES[btn.dataset.preset];
      if(pv&&pv.target_mg){
        const diff=Math.abs(pv.target_mg-target);
        if(diff<bestDiff){bestDiff=diff;bestPreset=btn;}
      }
    });
    firstVisible=bestPreset||document.querySelector('[data-preset]');
  }
  if(firstVisible){
    selectDispensePreset(firstVisible.dataset.preset);
  }else{
    document.querySelectorAll('[data-preset]').forEach(item=>item.classList.remove('selected'));
    selectedDispensePreset='fast-80hz-p200';
  }
}
```

- [ ] **Step 4: 添加自定义输入框的事件监听**

在三个固定目标按钮的事件绑定之后（第 387–392 行之后）添加：

```javascript
// Custom target input: sync selectedDispenseTarget on change
el('dispense-custom-target').addEventListener('input',()=>{
  const raw=el('dispense-custom-target').value.trim();
  if(raw===''){
    el('start-500mg').disabled=true;
    el('dispense-message').textContent='请输入 50–1000 mg 之间的质量';
    return;
  }
  const value=Number(raw);
  if(Number.isNaN(value)||!Number.isInteger(value)||value<50||value>1000){
    el('start-500mg').disabled=true;
    el('dispense-message').textContent='请输入 50–1000 mg 之间的质量';
    return;
  }
  selectedDispenseTarget=value;
  // Deselect fixed target buttons
  document.querySelectorAll('[data-dispense-target]').forEach(item=>item.classList.remove('selected'));
  updateDispensePanelLabels();
  filterPresetsByTarget(value);
  el('start-500mg').disabled=false;
});

// When fixed target button is clicked, sync input box
document.querySelectorAll('[data-dispense-target]').forEach(button=>{
  const origClick=button.onclick;
  button.addEventListener('click',()=>{
    el('dispense-custom-target').value=selectedDispenseTarget;
  });
});
```

- [ ] **Step 5: 提交**

```bash
git add scripts/device_dashboard.py
git commit -m "feat: add custom mass input for arbitrary dispense targets"
```

---

### Task 6: 集成验证

**Files:**
- 无新建文件

- [ ] **Step 1: 运行插值单元测试确认全部通过**

```powershell
py -3 -m pytest tests/test_interpolate_profile.py -v
```

- [ ] **Step 2: 语法检查所有修改文件**

```powershell
py -3 -c "import py_compile; py_compile.compile('scripts/device_control_server.py', doraise=True)"
py -3 -c "import py_compile; py_compile.compile('scripts/device_dashboard.py', doraise=True)"
py -3 -c "import sys; sys.path.insert(0,'src'); from powder_sampling_control.dispensing_algorithm.feedback_profiles import interpolate_profile, validate_dispense_target; print('OK')"
```

- [ ] **Step 3: 手动验证插值边界值**

```powershell
py -3 -c "
import sys; sys.path.insert(0,'src')
from powder_sampling_control.dispensing_algorithm.feedback_profiles import interpolate_profile
for t in (50, 100, 150, 200, 300, 400, 500, 750, 1000):
    p = interpolate_profile(t)
    print(f'{t:>4} mg: coarse={p[\"coarse_rate_mg_s\"]:5.1f} fine={p[\"fine_rate_mg_s\"]:5.1f} prec={p[\"precision_rate_mg_s\"]:5.1f} p_start={p[\"precision_start_remaining_mg\"]:5.1f} tts={p[\"tail_taper_start_remaining_mg\"]:5.1f} tte={p[\"tail_taper_end_remaining_mg\"]:5.1f}')
"
```

预期输出：所有值在合理范围，不抛异常。

- [ ] **Step 4: 确认 `dispense_plan()` 向后兼容（保留原函数）**

```powershell
py -3 -c "
import sys; sys.path.insert(0,'src')
from powder_sampling_control.dispensing_algorithm.feedback_profiles import dispense_plan
# Verify dispense_plan still works for the three standard targets
t100, p100 = dispense_plan(100)
assert t100 == 100
assert p100['coarse_rate_mg_s'] == 15.0
t500, p500 = dispense_plan(500)
assert t500 == 500
assert p500['coarse_rate_mg_s'] == 30.0
# Verify dispense_plan still REJECTS non-standard targets
try:
    dispense_plan(200)
    assert False, 'should have raised'
except ValueError:
    pass
print('dispense_plan backward compat OK')
"
```

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "chore: integration verification notes for arbitrary-mass dispensing"
```
