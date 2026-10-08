"""500 mg continuous closed-loop dispensing workflow (plan / run).

Consolidates the former standalone scripts into one entry point:

    python dispense_500mg.py plan <current_mass_mg>      ...  (was plan_500mg_state_dispense.py)
    python dispense_500mg.py run --execute               ...  (was execute_500mg_state_dispense.py)
    python dispense_500mg.py run --execute --serve       ...  executor + live monitor page

The `run` subcommand owns COM9 (AT8811C) and COM8 (LA10) for the whole task;
the dashboard must be stopped first. The vibration enable register is written
once at feed start and once at the final stop; during feeding only frequency
register 12 changes from live weighing feedback.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import threading
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from powder_sampling_control.device_adapters import (  # noqa: E402
    AT8811CConfig,
    AT8811CModbusRTU,
    LA10Config,
    LA10ModbusRTU,
)
from powder_sampling_control.dispensing_algorithm import (  # noqa: E402
    ActuationLimits,
    ActuationPolicy,
    DynamicRatePlanner,
    FourStagePlanner,
    L0Profile,
    MassMotionEstimator,
    MassMotionEstimatorSettings,
    MassObservation,
    PlannerContext,
    RatePlannerSettings,
    Recipe,
    StageParameters,
)


TARGET_MG = 500.0

POSITION_UNITS_PER_MM = 200
MOTION_UNITS_PER_MM = 100
POSITION_TOLERANCE_UNITS = 100
HARD_OVERWEIGHT_MG = 510.0
SLOW_ENTRY_MG = 420.0
FINE_ENTRY_MG = 470.0
PREDICTION_HORIZON_S = 0.75


# ── offline preview helpers (was plan_500mg_state_dispense.py) ───────────────


def calibration_profile() -> L0Profile:
    """Return the current measured 500 mg candidate profile.

    Coarse is based mainly on the completed 500 mg run:
    1200 / 60 Hz / duty 2000 / 8.594 s -> +362 mg (~42.12 mg/s).

    Only the initial coarse setting is applied directly. Slow/fine frequency
    values are open-loop seeds; the hardware executor keeps duty fixed at 20%
    and replaces those guesses with live 10/7/5 mg/s rate feedback.
    """

    return L0Profile(
        profile_id="stage1-500mg-window1200-dynamic-rate-candidate-v4",
        powder_type="unknown_from_a_data",
        powder_batch="unknown_from_a_data",
        feeder_head="la10_vibration_head",
        recipe_version="stage1-v0",
        target_mass_mg=TARGET_MG,
        # The hardware executor uses this profile only for its ILC/L0 initial
        # frequency and fixed duty. Live mass flow selects 10/7/5 mg/s targets.
        slow_entry_margin_mg=80.0,
        fine_entry_margin_mg=30.0,
        hard_overweight_margin_mg=10.0,
        coarse=StageParameters(
            window_position_units=1200,
            frequency_hz=60,
            duty_permyriad=2000,
            reference_mg_per_s=42.12,
            min_duration_ms=2500,
            max_duration_ms=8_500,
        ),
        slow=StageParameters(
            window_position_units=1200,
            frequency_hz=55,
            duty_permyriad=2000,
            reference_mg_per_s=7.82,
            min_duration_ms=1000,
            max_duration_ms=8_000,
        ),
        fine=StageParameters(
            window_position_units=1200,
            frequency_hz=40,
            duty_permyriad=2000,
            reference_mg_per_s=1.493978,
            min_duration_ms=500,
            max_duration_ms=12_000,
        ),
    )


def planner() -> FourStagePlanner:
    # Current calibration intentionally uses window 1200 and high duty values.
    # Keep these bounds local to this offline helper; production safety limits
    # should still be reviewed before machine release.
    limits = ActuationLimits(
        min_window_position_units=350,
        max_window_position_units=1300,
        min_frequency_hz=10,
        max_frequency_hz=80,
        min_duty_permyriad=1000,
        max_duty_permyriad=5000,
        noise_budget_hz_permyriad=1_000_000,
        min_duration_ms=80,
        max_duration_ms=12_000,
    )
    return FourStagePlanner(policy=ActuationPolicy(limits))


def decide(current_mass_mg: float, predicted_tail_mg: float = 0.0) -> dict:
    if current_mass_mg < 0:
        raise ValueError("current_mass_mg must be non-negative")
    if predicted_tail_mg < 0:
        raise ValueError("predicted_tail_mg must be non-negative")

    recipe = Recipe(
        recipe_id="stage1-500mg-preview",
        target_mass_mg=TARGET_MG,
        allowed_overweight_mg=10.0,
    )
    profile = calibration_profile()
    decision = planner().next_decision(
        PlannerContext(
            recipe=recipe,
            profile=profile,
            observation=MassObservation(current_mass_mg, stable=True, communication_ok=True),
            predicted_tail_mg=predicted_tail_mg,
        )
    )
    action = asdict(decision.action) if decision.action is not None else None
    return {
        "state": decision.stage.value.upper(),
        "decision": "FEED" if action is not None else "STOP",
        "action": action,
        "remaining_predicted_mg": decision.remaining_predicted_mg,
        "expected_mass_mg": decision.expected_mass_mg,
        "reason": decision.reason,
        "algorithm_thresholds": {
            "coarse_when_remaining_gt_mg": profile.slow_entry_margin_mg,
            "slow_when_remaining_gt_mg": profile.fine_entry_margin_mg,
            "fine_when_remaining_lte_mg": profile.fine_entry_margin_mg,
            "settle_when_remaining_lte_mg": 0.0,
            "hard_overweight_boundary_mg": TARGET_MG + min(recipe.allowed_overweight_mg, profile.hard_overweight_margin_mg),
        },
        "profile_id": profile.profile_id,
        "next_instruction": "保持振动使能和20%固定占空比，仅根据实时称重更新频率。" if action else "达到停机判据后关闭振动并等待最终稳定。",
    }


# ── monitor dashboard HTML (was dispense_500mg_dashboard.py) ─────────────────

DASHBOARD_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>500 mg 加粉控制</title>
<style>
:root{--bg:#eef2f4;--paper:#fff;--ink:#18232b;--muted:#61717c;--line:#d3dde2;--teal:#087f73;--green:#26734d;--amber:#a45d00;--red:#b42318;--blue:#176b96}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 "Microsoft YaHei",Arial,sans-serif;letter-spacing:0}
header{height:62px;background:var(--paper);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 24px}
h1{font-size:19px;margin:0}.connection{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:12px}.dot{width:9px;height:9px;border-radius:50%;background:#94a3b8}.dot.ok{background:var(--green)}.dot.bad{background:var(--red)}
main{max-width:1320px;margin:0 auto;padding:20px 24px 32px}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:16px}.toolbar p{margin:0;color:var(--muted)}
button{height:36px;border:1px solid var(--line);border-radius:5px;background:#fff;color:var(--ink);padding:0 14px;font-weight:600;cursor:pointer}button.primary{background:var(--teal);border-color:var(--teal);color:#fff}button.danger{color:var(--red);border-color:#e2aaa5}button:disabled{opacity:.45;cursor:not-allowed}
.layout{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(310px,.7fr);gap:16px}.panel{background:var(--paper);border:1px solid var(--line);border-radius:6px}.panel h2{font-size:14px;margin:0;padding:13px 15px;border-bottom:1px solid var(--line)}
.mass{padding:22px 18px 18px}.mass-line{display:flex;align-items:baseline;justify-content:space-between}.mass-value{font-size:46px;font-weight:700}.mass-value small{font-size:15px;color:var(--muted);font-weight:500}.target{color:var(--muted)}
.progress{height:12px;border-radius:3px;background:#e5ecef;overflow:hidden;margin-top:16px}.progress span{display:block;height:100%;background:var(--teal);width:0;transition:width .2s}.progress.over span{background:var(--red)}
.stats{display:grid;grid-template-columns:repeat(5,1fr);border-top:1px solid var(--line)}.stat{padding:14px;border-right:1px solid var(--line)}.stat:last-child{border-right:0}.label{font-size:11px;color:var(--muted);margin-bottom:5px}.number{font-size:19px;font-weight:650;min-height:28px}
.stage{padding:17px}.stage-name{font-size:26px;font-weight:700}.stage-reason{color:var(--muted);min-height:40px;margin-top:4px}.action-grid{display:grid;grid-template-columns:repeat(2,1fr);border-top:1px solid var(--line);margin:14px -17px -17px}.action-grid div{padding:12px 17px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.action-grid div:nth-child(2n){border-right:0}
.status-line{padding:12px 15px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:16px}.status-line:last-child{border-bottom:0}.status-line span:first-child{color:var(--muted)}.ok{color:var(--green)}.warn{color:var(--amber)}.bad{color:var(--red)}
.history{margin-top:16px;overflow:hidden}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:10px 12px;border-top:1px solid var(--line)}th{font-size:11px;color:var(--muted);background:#f7f9fa}td.num{font-family:Consolas,monospace}.empty{padding:22px;color:var(--muted)}
.error{margin-top:16px;border:1px solid #e3aaa5;background:#fff6f5;color:var(--red);padding:12px;border-radius:5px;display:none;word-break:break-word}
@media(max-width:850px){header{padding:0 14px}main{padding:14px}.toolbar{align-items:flex-start;flex-direction:column}.layout{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}.stat:nth-child(2n){border-right:0}.mass-value{font-size:38px}}
</style>
</head>
<body>
<header><h1>500 mg 加粉控制</h1><div class="connection"><i id="dot" class="dot"></i><span id="connection">等待后端</span><span id="updated"></span></div></header>
<main>
  <div class="toolbar"><p>连续闭环 · 目标流速 10/7/5 mg/s · 每次仅 ±1 Hz · 调频间隔约 2.5 s</p><div><button id="cancel" class="danger" disabled>取消任务</button> <button id="start" class="primary">开始 500 mg 任务</button></div></div>
  <div class="layout">
    <div>
      <section class="panel">
        <div class="mass"><div class="mass-line"><div class="mass-value"><span id="mass">--</span><small> mg</small></div><div class="target">目标 500 mg</div></div><div id="progress" class="progress"><span></span></div></div>
        <div class="stats"><div class="stat"><div class="label">当前阶段</div><div id="phase" class="number">空闲</div></div><div class="stat"><div class="label">剩余量</div><div id="remaining" class="number">--</div></div><div class="stat"><div class="label">调频次数</div><div id="step-count" class="number">0</div></div><div class="stat"><div class="label">任务总耗时</div><div id="elapsed" class="number">0.0 s</div></div><div class="stat"><div class="label">累计振动时间</div><div id="vibration-elapsed" class="number">0.000 s</div></div></div>
      </section>
      <section class="panel history"><h2>实时调频记录</h2><div id="empty" class="empty">尚未发生频率调整</div><table id="history" hidden><thead><tr><th>时间</th><th>阶段</th><th>重量</th><th>实测流速</th><th>目标流速</th><th>频率变化</th></tr></thead><tbody></tbody></table></section>
      <div id="error" class="error"></div>
    </div>
    <div>
      <section class="panel"><h2>当前反馈控制</h2><div class="stage"><div id="stage" class="stage-name">IDLE</div><div id="reason" class="stage-reason">等待启动</div><div class="action-grid"><div><div class="label">窗口位置</div><strong id="window">--</strong></div><div><div class="label">实时频率</div><strong id="frequency">--</strong></div><div><div class="label">固定占空比</div><strong id="duty">--</strong></div><div><div class="label">控制方式</div><strong id="duration">--</strong></div><div><div class="label">当前阶段持续</div><strong id="action-elapsed">0.000 s</strong></div><div><div class="label">滤波重量</div><strong id="filtered-mass">--</strong></div><div><div class="label">实时估计流速</div><strong id="flow-rate">--</strong></div><div><div class="label">阶段目标流速</div><strong id="target-flow">--</strong></div><div><div class="label">预测尾量</div><strong id="predicted-tail">--</strong></div></div></div></section>
      <section class="panel" style="margin-top:16px"><h2>设备状态</h2><div class="status-line"><span>任务状态</span><strong id="task-status">空闲</strong></div><div class="status-line"><span>超速保护</span><strong id="overspeed">--</strong></div><div class="status-line"><span>天平稳定</span><strong id="stable">--</strong></div><div class="status-line"><span>LA10 位置</span><strong id="position">--</strong></div><div class="status-line"><span>LA10 故障位</span><strong id="fault">--</strong></div><div class="status-line"><span>LA10 结果码</span><strong id="result-code">--</strong></div><div class="status-line"><span>震动使能</span><strong id="vibration">--</strong></div></section>
    </div>
  </div>
</main>
<script>
const $=id=>document.getElementById(id);let lastRunning=false;
function text(id,value){$(id).textContent=value}
function render(data){
  $('dot').className='dot ok';text('connection','后端在线');text('updated',new Date().toLocaleTimeString());
  const running=data.status==='running';lastRunning=running;$('start').disabled=running;$('cancel').disabled=!running;
  text('task-status',({idle:'空闲',running:'运行中',completed:'已完成',failed:'失败',cancelled:'已取消'})[data.status]||data.status);
  $('task-status').className=data.status==='completed'?'ok':data.status==='failed'?'bad':running?'warn':'';
  const mass=data.current_mass_mg;text('mass',mass==null?'--':Number(mass).toFixed(1));
  const ratio=mass==null?0:Math.max(0,Math.min(110,mass/500*100));$('progress').querySelector('span').style.width=ratio+'%';$('progress').className=mass>510?'progress over':'progress';
  const taskElapsed=data.task_elapsed_s??data.elapsed_s??0;const vibrationElapsed=data.vibration_elapsed_s??0;
  text('phase',data.phase_label||'空闲');text('remaining',data.remaining_mg==null?'--':Number(data.remaining_mg).toFixed(1)+' mg');text('step-count',data.frequency_update_count??0);text('elapsed',Number(taskElapsed).toFixed(1)+' s');text('vibration-elapsed',Number(vibrationElapsed).toFixed(3)+' s');
  text('stage',data.stage||'IDLE');text('reason',data.reason||'等待启动');const a=data.action||{};const actionElapsed=data.current_action_elapsed_s??0;text('window',a.window_position_units??'--');text('frequency',a.frequency_hz==null?'--':a.frequency_hz+' Hz');text('duty',a.duty_permyriad==null?'--':(a.duty_permyriad/100).toFixed(1)+'%');text('duration',a.control_mode==='continuous'?'仅调频率':'--');text('action-elapsed',Number(actionElapsed).toFixed(3)+' s');text('filtered-mass',data.filtered_mass_mg==null?'--':Number(data.filtered_mass_mg).toFixed(1)+' mg');text('flow-rate',data.estimated_flow_mg_s==null?'--':Number(data.estimated_flow_mg_s).toFixed(2)+' mg/s');text('target-flow',data.target_flow_mg_s==null?'--':Number(data.target_flow_mg_s).toFixed(2)+' mg/s');text('predicted-tail',data.predicted_tail_mg==null?'--':Number(data.predicted_tail_mg).toFixed(2)+' mg');
  text('overspeed',data.overspeed_active?'已触发，逐步降频':'未触发');$('overspeed').className=data.overspeed_active?'bad':'ok';text('stable',data.balance_stable==null?'--':data.balance_stable?'稳定':'未稳定');text('position',data.position_units==null?'--':data.position_units);text('fault',data.fault_bits==null?'--':'0x'+Number(data.fault_bits).toString(16).padStart(4,'0'));text('result-code',data.last_result??'--');text('vibration',data.vibration_enabled==null?'--':data.vibration_enabled?'运行中':'已停止');
  const updates=data.frequency_updates||[];$('empty').hidden=updates.length>0;$('history').hidden=updates.length===0;$('history').querySelector('tbody').innerHTML=updates.map(u=>`<tr><td class="num">${Number(u.elapsed_s).toFixed(2)} s</td><td>${u.stage}</td><td class="num">${Number(u.mass_mg).toFixed(1)} mg</td><td class="num">${Number(u.measured_rate_mg_s).toFixed(2)} mg/s</td><td class="num">${Number(u.target_rate_mg_s).toFixed(2)} mg/s</td><td class="num">${u.frequency_before_hz} -> ${u.frequency_after_hz} Hz</td></tr>`).join('');
  $('error').style.display=data.error?'block':'none';text('error',data.error?(data.error_type?data.error_type+': ':'')+data.error+(data.output_path?' · 已保存 '+data.output_path:''):'');
}
async function refresh(){try{const r=await fetch('/api/snapshot',{cache:'no-store'});render(await r.json())}catch(e){$('dot').className='dot bad';text('connection','后端断开')}}
async function post(path){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const d=await r.json();if(!r.ok)throw new Error(d.error||'请求失败');return d}
$('start').onclick=async()=>{try{await post('/api/start');refresh()}catch(e){alert(e.message)}};$('cancel').onclick=async()=>{try{await post('/api/cancel')}catch(e){alert(e.message)}};
refresh();setInterval(refresh,250);
</script>
<script>
/* Motion state comes from the executor snapshot; this page never opens a serial port. */
const motionPanel=document.createElement('section');
motionPanel.className='panel';
motionPanel.style.cssText='margin-top:16px;padding:13px 15px;display:flex;gap:24px;flex-wrap:wrap';
motionPanel.innerHTML='<strong>运动状态</strong><span>加速度 <b id="motion-accel">--</b> mg/s²</span><span>加加速度 <b id="motion-jerk">--</b> mg/s³</span><span>预测流速 <b id="motion-rate">--</b> mg/s</span><span>预测质量 <b id="motion-mass">--</b> mg</span>';
document.querySelector('main').appendChild(motionPanel);
const renderWithMotion=render;
render=function(data){
  renderWithMotion(data);
  const value=(key)=>data[key]==null?'--':Number(data[key]).toFixed(2);
  document.getElementById('motion-accel').textContent=value('estimated_acceleration_mg_s2');
  document.getElementById('motion-jerk').textContent=value('estimated_jerk_mg_s3');
  document.getElementById('motion-rate').textContent=value('predicted_flow_mg_s');
  document.getElementById('motion-mass').textContent=value('predicted_mass_mg');
};
</script>
</body>
</html>"""


# ── hardware executor (was execute_500mg_state_dispense.py) ──────────────────


class LiveState:
    """Thread-safe task state shared by the HTTP monitor and worker."""

    def __init__(self, args):
        self.args = args
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._snapshot = self._empty_snapshot()

    @staticmethod
    def _empty_snapshot():
        return {
            "status": "idle",
            "phase_label": "IDLE",
            "current_mass_mg": None,
            "filtered_mass_mg": None,
            "estimated_flow_mg_s": 0.0,
            "estimated_acceleration_mg_s2": 0.0,
            "estimated_jerk_mg_s3": 0.0,
            "predicted_flow_mg_s": 0.0,
            "predicted_mass_mg": None,
            "target_flow_mg_s": 10.0,
            "frequency_update_count": 0,
            "overspeed_active": False,
            "predicted_tail_mg": 0.0,
            "steps": [],
            "elapsed_s": 0.0,
            "task_elapsed_s": 0.0,
            "vibration_elapsed_s": 0.0,
            "current_action_elapsed_s": 0.0,
        }

    @property
    def cancel_event(self):
        return self._cancel

    def update(self, **values):
        with self._lock:
            self._snapshot.update(values)

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def start(self):
        with self._lock:
            if self._snapshot.get("status") == "running":
                raise RuntimeError("a 500 mg task is already running")
            if not self.args.execute:
                raise RuntimeError("server must be launched with --execute for physical control")
            self._cancel.clear()
            self._snapshot = self._empty_snapshot()
            self._snapshot.update(status="running", phase_label="STARTING")
        threading.Thread(target=self._run, daemon=True).start()
        return {"accepted": True, "monitor_url": f"http://{self.args.host}:{self.args.port}"}

    def cancel(self):
        self._cancel.set()
        return {"accepted": True}

    def _run(self):
        try:
            execute(args=self.args, monitor=self)
        except Exception as error:
            self.update(status="failed", phase_label="FAILED", error=str(error))


def make_handler(state: LiveState):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, payload, content_type="application/json; charset=utf-8"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self._send(200, DASHBOARD_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/snapshot":
                self._send(200, state.snapshot())
            else:
                self.send_error(404)

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                if path == "/api/start":
                    self._send(202, state.start())
                elif path == "/api/cancel":
                    self._send(202, state.cancel())
                else:
                    self.send_error(404)
            except Exception as error:
                self._send(409, {"error": str(error)})

        def log_message(self, _format, *_args):
            return

    return Handler


def measurement_record(measurement) -> dict:
    record = asdict(measurement)
    record["captured_at"] = measurement.captured_at.isoformat()
    return record


def wait_for_stable(balance, timeout_s, *, on_sample=None, cancel_event=None):
    deadline = time.monotonic() + timeout_s
    stable_samples = []
    latest = None
    while time.monotonic() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("task cancelled by operator")
        latest = balance.read_measurement()
        if on_sample is not None:
            on_sample(latest)
        if latest.stable:
            stable_samples.append(latest)
            stable_samples = stable_samples[-3:]
            if len(stable_samples) == 3:
                masses = [sample.mass_mg for sample in stable_samples]
                if None not in masses and max(masses) - min(masses) <= 2.0:
                    return stable_samples[-1]
        else:
            stable_samples.clear()
        time.sleep(0.25)
    raise TimeoutError(f"balance stability timeout; latest={latest}")


def ensure_window(la10: LA10ModbusRTU, target_units: int, timeout_s: float = 30.0):
    before = la10.read_status()
    if before.fault_bits:
        raise RuntimeError(f"LA10 fault bits before motion: 0x{before.fault_bits:04X}")
    if before.is_running:
        raise RuntimeError("LA10 is already moving")
    error_units = abs(target_units - before.position_units)
    distance_register = round(error_units / POSITION_UNITS_PER_MM * MOTION_UNITS_PER_MM)
    if error_units <= POSITION_TOLERANCE_UNITS:
        return before, before, 0
    la10.enable()
    la10.move_relative(
        extend=target_units > before.position_units,
        distance_mm=distance_register / MOTION_UNITS_PER_MM,
        speed_mm_s=1.0,
    )
    after = la10.wait_until_stopped(timeout_s=timeout_s, require_running_transition=True)
    if after.fault_bits:
        raise RuntimeError(f"LA10 fault bits after motion: 0x{after.fault_bits:04X}")
    if after.last_result != 0:
        raise RuntimeError(f"LA10 motion result code: {after.last_result}")
    if abs(after.position_units - target_units) > POSITION_TOLERANCE_UNITS:
        raise RuntimeError(f"LA10 window outside tolerance: actual={after.position_units}, target={target_units}")
    return before, after, distance_register


def stage_action(profile, stage: str) -> dict:
    parameters = profile.coarse
    return {
        "window_position_units": parameters.window_position_units,
        "frequency_hz": parameters.frequency_hz,
        "duty_permyriad": parameters.duty_permyriad,
        "duration_ms": None,
        "control_mode": "continuous",
    }


def dashboard_steps(steps: list[dict]) -> list[dict]:
    return [
        {
            "index": step["index"],
            "state": step["state"],
            "action": step["action"],
            "mass_before_mg": step["mass_before_mg"],
            "mass_after_mg": step.get("mass_after_mg"),
            "actual_mass_gain_mg": step.get("actual_mass_gain_mg"),
            "actual_duration_s": step.get("actual_duration_s"),
            "outcome": step.get("outcome", "running"),
        }
        for step in steps
    ]


def execute(args: argparse.Namespace, monitor: LiveState | None = None) -> dict:
    if not args.execute:
        raise PermissionError("physical dispensing requires --execute")
    if min(args.task_timeout_s, args.stable_timeout_s, args.sample_interval_s, args.no_flow_timeout_s) <= 0:
        raise ValueError("timeouts and sample interval must be positive")

    profile = calibration_profile()
    rate_planner = DynamicRatePlanner(
        RatePlannerSettings(
            coarse_end_mg=SLOW_ENTRY_MG,
            slow_end_mg=FINE_ENTRY_MG,
            coarse_target_mg_s=10.0,
            slow_target_mg_s=7.0,
            fine_target_mg_s=5.0,
            min_frequency_hz=10,
            max_frequency_hz=80,
            # Keep one-hertz commands, but let severe predictive overspeed
            # unwind at roughly one command per balance sample.
            severe_update_interval_s=0.25,
            medium_update_interval_s=0.5,
            small_update_interval_s=1.0,
            near_target_update_interval_s=1.5,
        )
    )
    motion_estimator = MassMotionEstimator(
        MassMotionEstimatorSettings(prediction_horizon_s=PREDICTION_HORIZON_S)
    )
    balance = AT8811CModbusRTU(
        AT8811CConfig(port=args.at_port, scale_mg_per_count=1.0, timeout_s=1.0, retries=2)
    )
    la10 = LA10ModbusRTU(LA10Config(port=args.la10_port, timeout_s=1.0, retries=2))
    result = {
        "run_id": f"dispense-500mg-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "control_mode": "continuous_vibration",
        "target_mass_mg": TARGET_MG,
        "hard_overweight_mg": HARD_OVERWEIGHT_MG,
        "profile_id": profile.profile_id,
        "rate_planner": asdict(rate_planner.settings),
        "mass_motion_estimator": asdict(motion_estimator.settings),
        "frequency_updates": [],
        "steps": [],
        "samples": [],
    }
    started = time.monotonic()
    vibration_started_at = None
    stage_started_at = None
    vibration_enabled = False
    failure = None
    last_measurement_mg = None

    def publish(**values):
        if monitor is None:
            return
        now = time.monotonic()
        task_elapsed = round(now - started, 3)
        vibration_elapsed = round(now - vibration_started_at, 3) if vibration_started_at is not None else 0.0
        action_elapsed = round(now - stage_started_at, 3) if stage_started_at is not None else 0.0
        values.setdefault("elapsed_s", task_elapsed)
        values.setdefault("task_elapsed_s", task_elapsed)
        values.setdefault("vibration_elapsed_s", vibration_elapsed)
        values.setdefault("current_action_elapsed_s", action_elapsed)
        monitor.update(**values)

    def publish_measurement(measurement):
        publish(current_mass_mg=measurement.mass_mg, balance_stable=measurement.stable)

    cancel_event = monitor.cancel_event if monitor is not None else None

    try:
        publish(status="running", phase_label="CONNECTING", reason="Connecting to COM9 and COM8")
        vibration = la10.read_vibration_settings()
        if vibration.enabled:
            la10.stop_vibration()
            raise RuntimeError("vibration was already enabled and has been stopped; inspect before retrying")

        publish(phase_label="WINDOW", reason="Moving and verifying the LA10 window")
        window_before, window_after, distance_register = ensure_window(
            la10, profile.coarse.window_position_units
        )
        result["window_before"] = asdict(window_before)
        result["window_after"] = asdict(window_after)
        result["window_distance_register"] = distance_register
        publish(
            position_units=window_after.position_units,
            fault_bits=window_after.fault_bits,
            last_result=window_after.last_result,
            vibration_enabled=False,
        )

        publish(phase_label="TARE", reason="Taring before the single continuous vibration run")
        balance.zero(authorized=True)
        tare_after = wait_for_stable(
            balance, args.stable_timeout_s, on_sample=publish_measurement, cancel_event=cancel_event
        )
        result["tare_after"] = measurement_record(tare_after)

        initial_mass = max(0.0, float(tare_after.mass_mg))
        current_stage = "COARSE"
        current_action = stage_action(profile, current_stage)
        current_step = {
            "index": 1,
            "state": current_stage,
            "action": current_action,
            "mass_before_mg": initial_mass,
        }
        result["steps"].append(current_step)

        status = la10.read_status()
        if status.fault_bits or status.is_running:
            raise RuntimeError(
                f"LA10 unsafe before vibration: fault=0x{status.fault_bits:04X}, running={status.is_running}"
            )
        la10.start_vibration(
            frequency_hz=current_action["frequency_hz"],
            duty_permyriad=current_action["duty_permyriad"],
        )
        vibration_enabled = True
        vibration_started_at = time.monotonic()
        stage_started_at = vibration_started_at
        publish(
            phase_label="COARSE FEED",
            stage=current_stage,
            reason="ILC initial frequency applied; live flow controls frequency only",
            action=current_action,
            vibration_enabled=True,
            steps=dashboard_steps(result["steps"]),
        )

        peak_mass = initial_mass
        last_flow_at = vibration_started_at
        last_device_check = vibration_started_at
        last_frequency_update = vibration_started_at
        stop_votes = 0

        while True:
            now = time.monotonic()
            if now - started >= args.task_timeout_s:
                raise TimeoutError("500 mg continuous dispense task timeout")
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("task cancelled by operator")

            measurement = balance.read_measurement()
            raw_mass = max(0.0, float(measurement.mass_mg))
            last_measurement_mg = raw_mass
            motion = motion_estimator.update(now, raw_mass)
            filtered_mass = motion.filtered_mass_mg
            flow_mg_s = motion.rate_mg_s
            predicted_tail_mg = max(0.0, motion.predicted_mass_mg - filtered_mass)
            projected_mass = motion.predicted_mass_mg

            if raw_mass >= peak_mass + 1.0:
                peak_mass = raw_mass
                last_flow_at = now
            if now - last_flow_at >= args.no_flow_timeout_s:
                raise RuntimeError(f"no powder flow detected for {args.no_flow_timeout_s:.1f} s")
            if raw_mass > HARD_OVERWEIGHT_MG:
                raise RuntimeError(f"hard overweight boundary exceeded: {raw_mass:.1f} mg")

            rate_decision = rate_planner.decide(
                filtered_mass_mg=filtered_mass,
                measured_rate_mg_s=flow_mg_s,
                current_frequency_hz=current_action["frequency_hz"],
                acceleration_mg_s2=motion.acceleration_mg_s2,
                jerk_mg_s3=motion.jerk_mg_s3,
                predicted_mass_mg=motion.predicted_mass_mg,
                predicted_rate_mg_s=motion.predicted_rate_mg_s,
                seconds_since_frequency_change=now - last_frequency_update,
                rate_valid=motion.valid,
            )
            overspeed_active = (
                motion.valid
                and max(flow_mg_s, motion.predicted_rate_mg_s)
                > rate_decision.target_rate_mg_s * rate_planner.settings.overspeed_multiple
            )
            next_stage = rate_decision.stage.value
            stage_changed = next_stage != current_stage
            adjustment_due = (
                stage_changed
                or now - last_frequency_update >= rate_decision.next_update_interval_s
            )
            if adjustment_due and rate_decision.frequency_changed:
                previous_frequency = current_action["frequency_hz"]
                la10.update_vibration_frequency(rate_decision.next_frequency_hz)
                current_action = {
                    **current_action,
                    "frequency_hz": rate_decision.next_frequency_hz,
                }
                result["frequency_updates"].append(
                    {
                        "elapsed_s": round(now - vibration_started_at, 3),
                        "stage": next_stage,
                        "mass_mg": round(filtered_mass, 3),
                        "measured_rate_mg_s": round(flow_mg_s, 3),
                        "predicted_rate_mg_s": round(motion.predicted_rate_mg_s, 3),
                        "acceleration_mg_s2": round(motion.acceleration_mg_s2, 3),
                        "jerk_mg_s3": round(motion.jerk_mg_s3, 3),
                        "predicted_mass_mg": round(motion.predicted_mass_mg, 3),
                        "target_rate_mg_s": rate_decision.target_rate_mg_s,
                        "frequency_before_hz": previous_frequency,
                        "frequency_after_hz": rate_decision.next_frequency_hz,
                        "duty_permyriad": current_action["duty_permyriad"],
                        "reason": rate_decision.reason,
                    }
                )
                last_frequency_update = time.monotonic()

            sample = {
                "elapsed_s": round(now - vibration_started_at, 3),
                "mass_mg": raw_mass,
                "filtered_mass_mg": round(filtered_mass, 3),
                "stable": measurement.stable,
                "estimated_flow_mg_s": round(flow_mg_s, 3),
                "estimated_acceleration_mg_s2": round(motion.acceleration_mg_s2, 3),
                "estimated_jerk_mg_s3": round(motion.jerk_mg_s3, 3),
                "predicted_flow_mg_s": round(motion.predicted_rate_mg_s, 3),
                "target_flow_mg_s": rate_decision.target_rate_mg_s,
                "rate_valid": motion.valid,
                "overspeed_active": overspeed_active,
                "predicted_tail_mg": round(predicted_tail_mg, 3),
                "projected_mass_mg": round(projected_mass, 3),
                "predicted_mass_mg": round(motion.predicted_mass_mg, 3),
                "innovation_mg": round(motion.innovation_mg, 3),
                "stage": current_stage,
                "frequency_hz": current_action["frequency_hz"],
                "duty_permyriad": current_action["duty_permyriad"],
            }
            result["samples"].append(sample)

            if stage_changed:
                current_step["mass_after_mg"] = filtered_mass
                current_step["actual_mass_gain_mg"] = filtered_mass - current_step["mass_before_mg"]
                current_step["actual_duration_s"] = round(now - stage_started_at, 3)
                current_step["outcome"] = "parameters_changed"

                current_stage = next_stage
                stage_started_at = time.monotonic()
                current_step = {
                    "index": len(result["steps"]) + 1,
                    "state": current_stage,
                    "action": current_action,
                    "mass_before_mg": filtered_mass,
                }
                result["steps"].append(current_step)

            # Tail prediction slows the feeder early, but never authorizes an
            # under-target stop. Two filtered samples at/above target suppress
            # a one-sample vibration spike without waiting for hardware stable.
            stop_candidate = filtered_mass >= TARGET_MG
            stop_votes = stop_votes + 1 if stop_candidate else 0

            publish(
                phase_label=f"{current_stage} FEED",
                stage=current_stage,
                reason=rate_decision.reason,
                action=current_action,
                current_mass_mg=raw_mass,
                filtered_mass_mg=round(filtered_mass, 3),
                estimated_flow_mg_s=round(flow_mg_s, 3),
                estimated_acceleration_mg_s2=round(motion.acceleration_mg_s2, 3),
                estimated_jerk_mg_s3=round(motion.jerk_mg_s3, 3),
                predicted_flow_mg_s=round(motion.predicted_rate_mg_s, 3),
                predicted_mass_mg=round(motion.predicted_mass_mg, 3),
                target_flow_mg_s=rate_decision.target_rate_mg_s,
                planner_reason=rate_decision.reason,
                frequency_update_count=len(result["frequency_updates"]),
                frequency_updates=result["frequency_updates"][-50:],
                overspeed_active=overspeed_active,
                predicted_tail_mg=round(predicted_tail_mg, 3),
                remaining_mg=round(TARGET_MG - projected_mass, 3),
                balance_stable=measurement.stable,
                vibration_enabled=True,
                steps=dashboard_steps(result["steps"]),
            )

            if stop_votes >= 2:
                current_step["mass_after_mg"] = filtered_mass
                current_step["actual_mass_gain_mg"] = filtered_mass - current_step["mass_before_mg"]
                current_step["actual_duration_s"] = round(time.monotonic() - stage_started_at, 3)
                current_step["outcome"] = "stop_threshold_reached"
                result["stop_control"] = sample
                break

            if now - last_device_check >= 2.0:
                device_status = la10.read_status()
                if device_status.fault_bits:
                    raise RuntimeError(f"LA10 fault during feed: 0x{device_status.fault_bits:04X}")
                settings = la10.read_vibration_settings()
                if not settings.enabled:
                    raise RuntimeError("vibration enable unexpectedly cleared during continuous feed")
                last_device_check = time.monotonic()

            time.sleep(args.sample_interval_s)

        publish(phase_label="STOPPING", reason="Final stop threshold reached; disabling vibration")
        la10.stop_vibration()
        vibration_enabled = False
        stopped_at = time.monotonic()
        result["vibration_elapsed_s"] = round(stopped_at - vibration_started_at, 3)
        publish(
            phase_label="SETTLING",
            reason="Vibration stopped once; waiting for final stable mass",
            vibration_enabled=False,
            steps=dashboard_steps(result["steps"]),
        )

        final = wait_for_stable(
            balance, args.stable_timeout_s, on_sample=publish_measurement, cancel_event=cancel_event
        )
        result["final_measurement"] = measurement_record(final)
        result["final_mass_mg"] = float(final.mass_mg)
        if not TARGET_MG <= result["final_mass_mg"] <= HARD_OVERWEIGHT_MG:
            raise RuntimeError(f"final mass outside acceptance range: {result['final_mass_mg']:.1f} mg")
        result["result"] = "completed"
        publish(
            status="completed",
            phase_label="ACCEPTED",
            stage="SETTLE",
            reason="Final stable mass is within 500-510 mg",
            current_mass_mg=result["final_mass_mg"],
            filtered_mass_mg=result["final_mass_mg"],
            remaining_mg=TARGET_MG - result["final_mass_mg"],
            action=None,
            steps=dashboard_steps(result["steps"]),
        )
    except Exception as error:
        result["result"] = "failed"
        result["error"] = str(error)
        result["error_type"] = type(error).__name__
        result["error_traceback"] = traceback.format_exc()
        if last_measurement_mg is not None:
            result["last_measurement_mg"] = last_measurement_mg
        failure = error
        publish(status="failed", phase_label="FAILED", reason="Task stopped", error=str(error))
    finally:
        if vibration_enabled:
            try:
                la10.stop_vibration()
                vibration_enabled = False
            except Exception as stop_error:
                result["stop_error"] = str(stop_error)
        try:
            result["vibration_final"] = asdict(la10.read_vibration_settings())
        except Exception as read_error:
            result["vibration_final_read_error"] = str(read_error)
        result["elapsed_s"] = round(time.monotonic() - started, 3)
        result["task_elapsed_s"] = result["elapsed_s"]
        if vibration_started_at is not None and "vibration_elapsed_s" not in result:
            result["vibration_elapsed_s"] = round(time.monotonic() - vibration_started_at, 3)
        result["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        output_dir = PROJECT_ROOT / "data" / "processed"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{result['run_id']}.json"
            output_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            result["output_path"] = str(output_path)
        except OSError as output_error:
            result["output_error"] = str(output_error)
        balance.close()
        la10.close()

    publish(
        status=result["result"],
        current_mass_mg=result.get("final_mass_mg", result.get("last_measurement_mg")),
        vibration_enabled=result.get("vibration_final", {}).get("enabled", False),
        steps=dashboard_steps(result["steps"]),
        elapsed_s=result["elapsed_s"],
        task_elapsed_s=result["task_elapsed_s"],
        vibration_elapsed_s=result.get("vibration_elapsed_s", 0.0),
        error=result.get("error"),
        error_type=result.get("error_type"),
        output_path=result.get("output_path"),
    )
    try:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except OSError:
        pass
    if failure is not None:
        raise failure
    return result


# ── CLI ──────────────────────────────────────────────────────────────────────


def cmd_plan(args: argparse.Namespace) -> int:
    result = decide(args.current_mass_mg, args.predicted_tail_mg)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"当前稳定重量: {args.current_mass_mg:.1f} mg")
    print(f"状态: {result['state']}")
    print(f"决策: {result['decision']}")
    print(f"原因: {result['reason']}")
    if "remaining_predicted_mg" in result:
        print(f"预测剩余: {result['remaining_predicted_mg']:.1f} mg")
        print(f"本次计划加粉: {result['expected_mass_mg']:.1f} mg")
        thresholds = result["algorithm_thresholds"]
        print("算法判断阈值:")
        print(f"  remaining > {thresholds['coarse_when_remaining_gt_mg']:.1f} mg -> COARSE")
        print(
            f"  {thresholds['fine_when_remaining_lte_mg']:.1f} mg < remaining <= "
            f"{thresholds['coarse_when_remaining_gt_mg']:.1f} mg -> SLOW"
        )
        print(f"  0 < remaining <= {thresholds['fine_when_remaining_lte_mg']:.1f} mg -> FINE")
        print(f"  remaining <= 0 或达到硬超量边界 {thresholds['hard_overweight_boundary_mg']:.1f} mg -> SETTLE")
    if result["action"] is not None:
        action = result["action"]
        print("下一步动作:")
        print(f"  window_position_units = {action['window_position_units']}")
        print(f"  frequency_hz = {action['frequency_hz']}")
        print(f"  duty_permyriad = {action['duty_permyriad']}")
        print(f"  duration_ms = {action['duration_ms']}")
        print(f"  duration_s = {action['duration_ms'] / 1000:.3f}")
    print(f"执行说明: {result['next_instruction']}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if args.serve:
        state = LiveState(args)
        server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
        print(f"500 mg continuous monitor: http://{args.host}:{args.port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            state.cancel()
        finally:
            server.server_close()
        return 0
    execute(args)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="preview the next 500 mg continuous-control parameter set (offline)")
    p_plan.add_argument("current_mass_mg", type=float, help="latest stable mass in mg")
    p_plan.add_argument(
        "--predicted-tail-mg",
        type=float,
        default=0.0,
        help="optional predicted falling tail mass in mg",
    )
    p_plan.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON instead of Chinese text",
    )
    p_plan.set_defaults(func=cmd_plan)

    p_run = sub.add_parser("run", help="run continuous closed-loop dispensing to 500 mg on COM9 and COM8")
    p_run.add_argument("--execute", action="store_true", help="authorize physical movement, tare, and vibration")
    p_run.add_argument("--at-port", default="COM9")
    p_run.add_argument("--la10-port", default="COM8")
    p_run.add_argument("--task-timeout-s", type=float, default=240.0)
    p_run.add_argument("--stable-timeout-s", type=float, default=15.0)
    p_run.add_argument("--sample-interval-s", type=float, default=0.25)
    p_run.add_argument("--no-flow-timeout-s", type=float, default=15.0)
    p_run.add_argument("--serve", action="store_true", help="serve the live monitor and wait for its Start button")
    p_run.add_argument("--host", default="127.0.0.1")
    p_run.add_argument("--port", type=int, default=8766)
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
