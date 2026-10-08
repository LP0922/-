"""Run a read-only local dashboard for the AT8811C and LA10 devices."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from powder_sampling_control.device_adapters import (
    AT8811CConfig,
    AT8811CModbusRTU,
    BalanceCalibration,
    LA10Config,
    LA10ModbusRTU,
    load_balance_calibration,
)


LA10_REGISTER_META = (
    (0, "控制命令", "1=工作，2=暂停，3=急停，4=清故障", "控制命令"),
    (1, "运动方向", "0=缩回，1=伸出", "方向"),
    (2, "运动距离", "0.01 mm", "距离"),
    (3, "运动速度", "0.01 mm/s", "速度"),
    (4, "运动使能", "写 1 启动相对运动", "使能"),
    (5, "当前位置", "约 200 单位/mm", "位置"),
    (6, "当前目标", "约 200 单位/mm", "目标位置"),
    (7, "温度", "int16，degC", "温度"),
    (8, "电流", "mA", "电流"),
    (9, "故障位", "bit0 堵转，bit1 过温，bit2 过流，bit3 电机异常", "故障"),
    (10, "运行状态", "0=停止，1=运行", "运行状态"),
    (11, "最后结果", "0=成功；非 0 为网关错误码", "执行结果"),
    (12, "振动频率", "Hz，允许 10-80", "频率"),
    (13, "占空比", "1000-5000 对应 10%-50%", "占空比"),
    (14, "振动使能", "0=停止，1=振动", "振动状态"),
)


def signed16(word: int) -> int:
    return word - 0x10000 if word & 0x8000 else word


def signed32(high: int, low: int) -> int:
    value = (high << 16) | low
    return value - 0x100000000 if value & 0x80000000 else value


def fault_text(value: int) -> str:
    names = []
    for mask, name in ((1, "堵转"), (2, "过温"), (4, "过流"), (8, "电机异常")):
        if value & mask:
            names.append(name)
    return "正常" if not names else "、".join(names)


class DeviceReader:
    """Owns both serial connections and exposes only read-only snapshots."""

    def __init__(
        self,
        at_port: str,
        la10_port: str,
        at_address: int,
        la10_address: int,
        balance_calibration: BalanceCalibration | None = None,
    ):
        self._lock = threading.Lock()
        self._balance_calibration = balance_calibration
        self._at = AT8811CModbusRTU(
            AT8811CConfig(
                port=at_port,
                slave_address=at_address,
                timeout_s=0.5,
                retries=1,
                scale_mg_per_count=(
                    balance_calibration.scale_mg_per_count
                    if balance_calibration is not None
                    else None
                ),
                offset_mg=(
                    balance_calibration.offset_mg
                    if balance_calibration is not None
                    else 0.0
                ),
            )
        )
        self._la10 = LA10ModbusRTU(
            LA10Config(port=la10_port, slave_address=la10_address, timeout_s=0.5, retries=1)
        )
        self._at_config = None
        self._at_config_at = 0.0
        self._at_config_error = None

    def close(self):
        self._at.close()
        self._la10.close()

    def snapshot(self):
        with self._lock:
            return {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "at8811c": self._read_at8811c(),
                "la10": self._read_la10(),
            }

    def _read_at8811c(self):
        try:
            measurement = self._at.read_measurement()
            if time.monotonic() - self._at_config_at >= 10:
                self._at_config_at = time.monotonic()
                try:
                    self._at_config = self._read_at_config()
                    self._at_config_error = None
                except Exception as error:
                    # Diagnostics must not make a valid live measurement offline.
                    self._at_config_error = str(error)
            return {
                "online": True,
                # raw_weight_mg is retained for the existing dashboard.  When
                # calibrated it now contains engineering-unit mass; raw_count
                # remains separately available for diagnostics.
                "raw_weight_mg": (
                    measurement.mass_mg
                    if measurement.mass_mg is not None
                    else measurement.raw_count
                ),
                "raw_count": measurement.raw_count,
                "mass_mg": measurement.mass_mg,
                "calibration": self.calibration_summary(),
                "status_word": measurement.status_word,
                "stable": measurement.stable,
                "in_zero_band": measurement.in_zero_band,
                "configuration": self._at_config,
                "configuration_error": self._at_config_error,
            }
        except Exception as error:
            # A transient timeout must not permanently latch the driver offline.
            # The next idle poll reconnects the balance port with a clean failure counter.
            self._at.reset_connection()
            return {
                "online": False,
                "error": str(error),
                "configuration": self._at_config,
                "calibration": self.calibration_summary(),
            }

    def calibration_summary(self) -> dict:
        calibration = self._balance_calibration
        if calibration is None:
            return {
                "configured": False,
                "valid": False,
                "warning": "raw_count 尚未通过标准砝码换算为 mg",
            }
        return {
            "configured": True,
            "valid": calibration.valid,
            "calibration_id": calibration.calibration_id,
            "created_at_utc": calibration.created_at_utc,
            "device_id": calibration.device_id,
            "scale_mg_per_count": calibration.scale_mg_per_count,
            "offset_mg": calibration.offset_mg,
            "max_abs_residual_mg": calibration.max_abs_residual_mg,
            "r_squared": calibration.r_squared,
        }

    def _read_at_config(self):
        primary = self._at.read_holding_registers(14, 7)
        tracking = self._at.read_holding_registers(21, 7)
        stable_range = self._at.read_holding_registers(40, 1)[0]
        tare_range = self._at.read_holding_registers(42, 1)[0]
        return {
            "division_mg": primary[0],
            "full_scale_mg": signed32(primary[1], primary[2]),
            "zero_range": signed32(primary[3], primary[4]),
            "startup_zero_range": signed32(primary[5], primary[6]),
            "zero_tracking_range": tracking[0],
            "zero_tracking_time": tracking[1],
            "ad_conversion": {"code": tracking[2], "label": "快" if tracking[2] == 2 else "慢"},
            "filter_level": tracking[3],
            "configured_address": tracking[4],
            "baudrate": {1: 1200, 2: 2400, 3: 4800, 4: 9600}.get(tracking[5], tracking[5]),
            "protocol_format": {0: "8-N-1", 1: "8-O-1", 2: "8-E-1", 3: "7-E-1"}.get(tracking[6], str(tracking[6])),
            "stable_range": stable_range,
            "tare_range_percent": tare_range,
        }

    def _read_la10(self):
        try:
            raw = self._la10.read_holding_registers(0, 15)
            values = [int.from_bytes(raw[index : index + 2], "big") for index in range(0, len(raw), 2)]
            rows = []
            for address, name, unit, key in LA10_REGISTER_META:
                value = signed16(values[address]) if address == 7 else values[address]
                display = self._la10_display(address, value)
                rows.append(
                    {
                        "address": address,
                        "name": name,
                        "value": value,
                        "unit": unit,
                        "display": display,
                    }
                )
            return {
                "online": True,
                "position_units": values[5],
                "position_mm": round(values[5] / 200.0, 3),
                "target_units": values[6],
                "target_mm": round(values[6] / 200.0, 3),
                "running": values[10] == 1,
                "fault_bits": values[9],
                "fault_text": fault_text(values[9]),
                "vibration_enabled": values[14] == 1,
                "registers": rows,
            }
        except Exception as error:
            self._la10.close()
            return {"online": False, "error": str(error), "registers": []}

    @staticmethod
    def _la10_display(address: int, value: int) -> str:
        if address == 1:
            return "伸出" if value == 1 else "缩回" if value == 0 else f"未知 ({value})"
        if address == 2:
            return f"{value / 100.0:.2f} mm"
        if address == 3:
            return f"{value / 100.0:.2f} mm/s"
        if address in (5, 6):
            return f"{value / 200.0:.3f} mm"
        if address == 7:
            return f"{value} degC"
        if address == 8:
            return f"{value} mA"
        if address == 9:
            return fault_text(value)
        if address == 10:
            return "运行" if value == 1 else "停止" if value == 0 else f"未知 ({value})"
        if address == 12:
            return f"{value} Hz"
        if address == 13:
            return f"{value / 100.0:.1f}%"
        if address == 14:
            return "振动中" if value == 1 else "已停止" if value == 0 else f"未知 ({value})"
        return str(value)


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>加粉设备监控</title>
<style>
  :root { --ink:#1f2937; --muted:#64748b; --line:#d9e1e8; --paper:#fff; --canvas:#f3f6f8; --blue:#1976a8; --teal:#0f766e; --red:#b42318; --amber:#a15c00; --green:#237a4b; }
  * { box-sizing:border-box; } body { margin:0; font-family:"Microsoft YaHei", Arial, sans-serif; color:var(--ink); background:var(--canvas); font-size:14px; }
  header { height:64px; padding:0 28px; display:flex; align-items:center; justify-content:space-between; background:var(--paper); border-bottom:1px solid var(--line); }
  h1 { margin:0; font-size:20px; letter-spacing:0; } .sub { color:var(--muted); margin-left:12px; font-size:12px; }
  .right { display:flex; gap:14px; align-items:center; color:var(--muted); font-size:12px; } button { border:1px solid var(--line); width:32px; height:32px; background:#fff; cursor:pointer; font-size:18px; border-radius:4px; color:var(--ink); } button:hover { background:#edf5f8; }
  main { max-width:1500px; margin:0 auto; padding:22px 28px 34px; } .grid { display:grid; grid-template-columns:minmax(360px, .9fr) minmax(560px, 1.4fr); gap:18px; align-items:start; }
  .panel { background:var(--paper); border:1px solid var(--line); border-radius:6px; overflow:hidden; } .panel-head { display:flex; justify-content:space-between; align-items:center; padding:14px 16px; border-bottom:1px solid var(--line); } .panel-head h2 { font-size:15px; margin:0; } .status { display:inline-flex; gap:6px; align-items:center; font-size:12px; color:var(--muted); } .dot { width:8px; height:8px; border-radius:50%; background:#94a3b8; } .dot.ok { background:var(--green); } .dot.bad { background:var(--red); }
  .metrics { display:grid; grid-template-columns:repeat(2, 1fr); border-bottom:1px solid var(--line); } .metric { padding:16px; min-height:93px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); } .metric:nth-child(2n) { border-right:0; } .label { color:var(--muted); font-size:12px; } .value { font-size:25px; font-weight:600; line-height:1.4; margin-top:5px; letter-spacing:0; } .unit { font-size:12px; color:var(--muted); font-weight:400; margin-left:3px; }
  .chips { display:flex; gap:6px; flex-wrap:wrap; padding:14px 16px; } .chip { border:1px solid var(--line); border-radius:4px; padding:4px 8px; font-size:12px; color:var(--muted); background:#f8fafc; } .chip.ok { color:var(--green); border-color:#9ad3b1; background:#f1fbf5; } .chip.warn { color:var(--amber); border-color:#e8c17c; background:#fff9ec; } .chip.bad { color:var(--red); border-color:#e4a7a2; background:#fff4f3; }
  .section-title { font-size:12px; font-weight:600; color:var(--muted); padding:14px 16px 8px; text-transform:uppercase; } table { border-collapse:collapse; width:100%; } th { color:var(--muted); font-weight:600; background:#f7f9fb; font-size:12px; } th, td { text-align:left; padding:9px 12px; border-top:1px solid var(--line); vertical-align:top; } td.num { font-family:Consolas, monospace; color:#0f3d56; } .config td:first-child { width:48%; color:var(--muted); } .error { margin:14px 16px; padding:10px; color:var(--red); border:1px solid #efb5b1; background:#fff4f3; border-radius:4px; word-break:break-all; } .offline { opacity:.55; }
  @media (max-width:980px) { main { padding:14px; } .grid { grid-template-columns:1fr; } header { padding:0 14px; } .sub { display:none; } }
</style>
</head>
<body>
<header><div><h1>加粉设备监控 <span class="sub">AT8811C / LA10 只读寄存器视图</span></h1></div><div class="right"><span id="updated">等待连接</span><button id="refresh" title="立即刷新" aria-label="立即刷新">&#x21bb;</button></div></header>
<main><div class="grid">
  <section class="panel" id="at-panel"><div class="panel-head"><h2>AT8811C 称量模块</h2><span class="status"><i class="dot"></i><span>连接中</span></span></div><div class="metrics"><div class="metric"><div class="label">实时重量</div><div class="value" id="at-weight">--<span class="unit">mg</span></div></div><div class="metric"><div class="label">状态字</div><div class="value" id="at-status">--</div></div><div class="metric"><div class="label">稳定标志</div><div class="value" id="at-stable">--</div></div><div class="metric"><div class="label">零区标志</div><div class="value" id="at-zero">--</div></div></div><div class="chips" id="at-chips"></div><div id="at-error"></div><div class="section-title">调试配置寄存器</div><table class="config"><tbody id="at-config"></tbody></table></section>
  <section class="panel" id="la-panel"><div class="panel-head"><h2>LA10 / 振动模块</h2><span class="status"><i class="dot"></i><span>连接中</span></span></div><div class="metrics"><div class="metric"><div class="label">当前位置</div><div class="value" id="la-position">--<span class="unit">mm</span></div></div><div class="metric"><div class="label">当前目标</div><div class="value" id="la-target">--<span class="unit">mm</span></div></div><div class="metric"><div class="label">运行状态</div><div class="value" id="la-running">--</div></div><div class="metric"><div class="label">振动状态</div><div class="value" id="la-vibration">--</div></div></div><div class="chips" id="la-chips"></div><div id="la-error"></div><div class="section-title">保持寄存器 0 - 14</div><table><thead><tr><th>地址</th><th>名称</th><th>原始值</th><th>解析值</th><th>单位 / 含义</th></tr></thead><tbody id="la-registers"></tbody></table></section>
</div>
<section class="panel" id="feed-panel" style="margin-top:18px"><div class="panel-head"><h2>震粉实时数据</h2><span id="feed-state" class="status">空闲</span></div><div class="metrics"><div class="metric"><div class="label">每秒震粉量</div><div class="value" id="feed-rate">--<span class="unit">mg/s</span></div></div><div class="metric"><div class="label">加速度</div><div class="value" id="feed-acceleration">--<span class="unit">mg/s²</span></div></div><div class="metric"><div class="label">加加速度</div><div class="value" id="feed-jerk">--<span class="unit">mg/s³</span></div></div><div class="metric"><div class="label">当前震粉质量</div><div class="value" id="feed-mass">--<span class="unit">mg</span></div></div></div><div class="chips"><span id="manual-state" class="chip">读取设备状态中</span></div></section>
</main>
<script>
const el = id => document.getElementById(id);
function state(panel, data) { const node=el(panel+'-panel'); const dot=node.querySelector('.dot'); const text=node.querySelector('.status span'); node.classList.toggle('offline', !data.online); dot.className='dot '+(data.online?'ok':'bad'); text.textContent=data.online?'在线':'离线'; }
function setError(id, error) { el(id).innerHTML=error?'<div class="error">'+error+'</div>':''; }
function chip(text, cls='') { return '<span class="chip '+cls+'">'+text+'</span>'; }
function renderAt(data) { state('at', data); setError('at-error',data.error); if(!data.online) return; el('at-weight').innerHTML=data.raw_weight_mg+'<span class="unit">mg</span>'; el('at-status').textContent='0x'+data.status_word.toString(16).toUpperCase().padStart(4,'0'); el('at-stable').textContent=data.stable?'稳定':'不稳定'; el('at-zero').textContent=data.in_zero_band?'在零区':'非零区'; el('at-chips').innerHTML=chip(data.stable?'硬件稳定位=1':'硬件稳定位=0',data.stable?'ok':'warn')+chip(data.in_zero_band?'零区位=1':'零区位=0',data.in_zero_band?'ok':'warn'); const c=data.configuration; if(!c) return; const rows=[['分度值',c.division_mg+' mg'],['满量程',c.full_scale_mg+' mg'],['置零范围',c.zero_range],['启动置零范围',c.startup_zero_range],['零点跟踪范围',c.zero_tracking_range],['零点跟踪时间',c.zero_tracking_time],['AD 转换频率',c.ad_conversion.label+'（代码 '+c.ad_conversion.code+'）'],['滤波等级',c.filter_level],['模块地址',c.configured_address],['波特率',c.baudrate],['协议格式',c.protocol_format],['硬件判稳范围',c.stable_range],['去皮范围',c.tare_range_percent+'%']]; el('at-config').innerHTML=rows.map(r=>'<tr><td>'+r[0]+'</td><td class="num">'+r[1]+'</td></tr>').join(''); }
function renderLa(data) { state('la',data); setError('la-error',data.error); if(!data.online) return; el('la-position').innerHTML=data.position_mm.toFixed(3)+'<span class="unit">mm</span>'; el('la-target').innerHTML=data.target_mm.toFixed(3)+'<span class="unit">mm</span>'; el('la-running').textContent=data.running?'运行':'停止'; el('la-vibration').textContent=data.vibration_enabled?'振动中':'已停止'; el('la-chips').innerHTML=chip('故障：'+data.fault_text,data.fault_bits?'bad':'ok')+chip(data.running?'执行器运行中':'执行器停止',data.running?'warn':'')+chip(data.vibration_enabled?'振动已使能':'振动已停止',data.vibration_enabled?'warn':''); el('la-registers').innerHTML=data.registers.map(r=>'<tr><td class="num">'+r.address+'</td><td>'+r.name+'</td><td class="num">'+r.value+'</td><td>'+r.display+'</td><td>'+r.unit+'</td></tr>').join(''); }
async function refresh() { try { const response=await fetch('/api/snapshot',{cache:'no-store'}); const data=await response.json(); renderAt(data.at8811c); renderDispenseBalance(data.at8811c); renderContinuousTaperBalance(data.at8811c); renderLa(data.la10); el('updated').textContent='更新 '+new Date(data.timestamp_utc).toLocaleTimeString(); } catch(error) { el('updated').textContent='连接失败'; } }
el('refresh').addEventListener('click',refresh); refresh(); setInterval(refresh,200);
</script>
<script>
const manualWritableRegisters=new Set([0,1,2,3,4,12,13,14]);
let manualWriteAllowed=false;
const legacyRenderLa=renderLa;
const manualStyle=document.createElement('style');
manualStyle.textContent='.manual-register-control{display:flex;gap:6px;align-items:center}.manual-register-control input{width:88px;height:28px;border:1px solid #d9e1e8;border-radius:4px;padding:0 6px;font-family:Consolas,monospace}.manual-register-control button{width:auto;height:28px;padding:0 8px;font-size:12px}.manual-register-control button:disabled{opacity:.45;cursor:not-allowed}';
document.head.appendChild(manualStyle);

function refreshManualWriteState(){
  document.querySelectorAll('[data-register-write]').forEach(button=>button.disabled=!manualWriteAllowed);
}
function renderLaControls(data){
  const body=el('la-registers');
  const table=body.closest('table');
  const header=table.querySelector('thead tr');
  if(header.children.length===5)header.insertAdjacentHTML('beforeend','<th>写入</th>');
  [...body.rows].forEach((row,index)=>{
    const register=data.registers[index];
    const cell=document.createElement('td');
    if(manualWritableRegisters.has(register.address)){
      cell.innerHTML='<div class="manual-register-control"><input data-register-input="'+register.address+'" type="number" step="1" value="'+register.value+'" id="register-value-'+register.address+'"><button data-register-write="'+register.address+'">写入</button></div>';
      cell.querySelector('button').addEventListener('click',()=>writeManualRegister(register.address));
    }else{
      cell.textContent='只读';
    }
    row.appendChild(cell);
  });
  refreshManualWriteState();
}
renderLa=function(data){
  // Keep an operator's partially typed value intact until the input loses focus.
  if(document.activeElement&&document.activeElement.matches('[data-register-input]'))return;
  legacyRenderLa(data);
  if(data.online)renderLaControls(data);
};

async function writeManualRegister(address){
  if(!manualWriteAllowed)return;
  const input=el('register-value-'+address);
  const value=Number(input.value);
  if(!Number.isInteger(value)){alert('请输入整数');return}
  const response=await fetch('/api/la10/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({address,value})});
  const result=await response.json();
  if(!response.ok){alert(result.error||'写入失败');return}
  // Immediately show the server-confirmed value so a concurrent poll
  // refresh cannot flash the old value back before the HTTP round-trip.
  input.value=result.value;
  refresh();
}
function showFeedState(test){
  const running=test&&test.status==='running';
  const sample=running?test.latest_sample:null;
  const value=(number,digits=2)=>number==null?'--':Number(number).toFixed(digits);
  el('feed-state').textContent=running?'测试运行中':'无任务';
  el('feed-rate').innerHTML=value(sample&&sample.rate_mg_s)+'<span class="unit">mg/s</span>';
  el('feed-acceleration').innerHTML=value(sample&&sample.acceleration_mg_s2)+'<span class="unit">mg/s²</span>';
  el('feed-jerk').innerHTML=value(sample&&sample.jerk_mg_s3)+'<span class="unit">mg/s³</span>';
  el('feed-mass').innerHTML=value(sample&&sample.mass_mg,1)+'<span class="unit">mg</span>';
  manualWriteAllowed=!running;
  el('manual-state').textContent=running?'任务运行中，寄存器写入已锁定':'无任务，可写 LA10 地址 0-4、12-14';
  el('manual-state').className='chip '+(running?'warn':'ok');
  refreshManualWriteState();
}
async function refreshFeedState(){
  try{const response=await fetch('/api/snapshot',{cache:'no-store'});const data=await response.json();showFeedState(data.test||{status:'idle'})}catch(error){el('manual-state').textContent='后台连接失败'}
}
const taskPanel=document.createElement('section');
taskPanel.className='panel';
taskPanel.style.marginTop='18px';
taskPanel.innerHTML='<div class="panel-head"><h2>测试与控制计划</h2><span id="sweep-state" class="status">待命</span></div><div class="metrics"><div class="metric"><div class="label">窗口位置扫描</div><div class="value" style="font-size:17px">100 至 750</div><div class="label">步长 50；80 Hz；20%；每点 10 s</div><button id="start-sweep" style="margin-top:12px;width:auto;padding:0 10px;font-size:13px">启动扫描</button></div><div class="metric"><div class="label">扫描进度</div><div class="value" id="sweep-progress" style="font-size:17px">未运行</div><div class="label" id="sweep-detail">震动持续开启，杆在震动状态下依次移动</div></div></div><div class="section-title">加粉任务计划</div><div id="dispense-plans" class="chips"></div>';
document.querySelector('main').appendChild(taskPanel);
const powderPanel=document.createElement('section');
powderPanel.className='panel';
powderPanel.style.marginTop='18px';
powderPanel.innerHTML='<div class="panel-head"><h2>粉末特征码</h2><span id="powder-status-label" class="status">未加载</span></div><div style="padding:14px 16px;border-bottom:1px solid var(--line)"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><select id="powder-select" style="height:34px;min-width:180px;padding:0 8px;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--ink);font:inherit"><option value="">+ 新粉末…</option></select><button id="run-probe-btn" class="command-button primary" style="width:auto">运行探针</button><button id="run-rate-search-btn" class="command-button primary" style="width:auto">速率搜索</button><button id="delete-powder-btn" class="command-button danger" style="width:auto" disabled>删除粉末</button></div><div id="powder-message" class="label" style="margin-top:9px">⚠ 未加载粉末指纹，使用默认参数</div><div id="probe-progress" style="display:none;margin-top:12px"><div style="display:flex;gap:10px;align-items:center"><span id="probe-phase" style="font-weight:600;color:var(--ink)"></span><div style="flex:1;height:8px;background:#eef2f5;border-radius:4px;overflow:hidden"><div id="probe-bar" style="height:100%;width:0%;background:var(--blue);border-radius:4px;transition:width .3s"></div></div><span id="probe-pct" style="font-size:13px;color:var(--muted)"></span></div></div><div id="powder-detail" style="display:none;margin-top:12px;padding:12px;background:#f8fafb;border:1px solid var(--line);border-radius:6px"><div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap"><span style="font-weight:600;font-size:13px">手动改分类：</span><select id="powder-category-select" style="height:30px;padding:0 6px;border:1px solid var(--line);border-radius:4px;font:inherit"><option value="Low-flow">Low-flow</option><option value="Medium-flow">Medium-flow</option><option value="High-flow">High-flow</option></select><button id="apply-category-btn" class="command-button" style="width:auto;height:30px;font-size:12px">应用</button><span id="category-change-msg" style="font-size:12px;color:var(--muted)"></span></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:12px;color:var(--muted)"><div>推荐 Preset：<b id="detail-preset" style="color:var(--ink)">--</b></div><div>观测器上限：<b id="detail-maxrate" style="color:var(--ink)">--</b> mg/s</div><div>固定尾量：<b id="detail-tail" style="color:var(--ink)">--</b> mg</div><div>标签：<b id="detail-tags" style="color:var(--ink)">--</b></div></div></div></div><div class="metrics"><div class="metric"><div class="label">分类</div><div class="value" id="powder-category" style="font-size:19px;cursor:pointer" title="点击展开详情">--</div></div><div class="metric"><div class="label">稳态速率</div><div class="value" id="powder-rate">--<span class="unit">mg/s</span></div></div><div class="metric"><div class="label">速率 CV</div><div class="value" id="powder-cv">--<span class="unit">%</span></div></div><div class="metric"><div class="label">启动延迟</div><div class="value" id="powder-delay">--<span class="unit">s</span></div></div><div class="metric"><div class="label">尾量</div><div class="value" id="powder-tail">--<span class="unit">mg</span></div></div><div class="metric"><div class="label">推荐 Preset</div><div class="value" id="powder-preset" style="font-size:17px">--</div></div></div>';
document.querySelector('main').appendChild(powderPanel);

// ===== 加粉控制（独立入口） =====
const dispenseEntryPanel=document.createElement('section');
dispenseEntryPanel.className='panel';
dispenseEntryPanel.style.marginTop='18px';
dispenseEntryPanel.innerHTML='<div class="panel-head"><h2>加粉控制</h2><span id="dispense-entry-state" class="status">待命</span></div><div style="padding:14px 16px;border-bottom:1px solid var(--line)"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><div><label style="font-size:12px;color:var(--muted)">粉末选择</label><select id="dispense-entry-powder" style="display:block;height:34px;min-width:180px;padding:0 8px;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--ink);font:inherit;margin-top:4px"><option value="">-- 选择粉末 --</option></select></div><div><label style="font-size:12px;color:var(--muted)">目标质量</label><input id="dispense-entry-target" type="number" min="100" max="1000" step="1" placeholder="100–1000" style="display:block;width:100px;height:34px;padding:0 8px;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--ink);font:inherit;margin-top:4px"></div><button id="dispense-entry-start" class="command-button primary" style="width:auto;height:34px;align-self:flex-end">开始加粉</button></div><div id="dispense-entry-info" class="label" style="margin-top:9px;color:var(--muted)">选择粉末后自动加载参数</div></div><div style="padding:14px 16px"><div style="display:flex;gap:10px;align-items:center"><div style="flex:1;height:10px;background:#eef2f5;border-radius:5px;overflow:hidden"><div id="dispense-entry-bar" style="height:100%;width:0%;background:var(--blue);border-radius:5px;transition:width .3s"></div></div><span id="dispense-entry-pct" style="font-size:13px;color:var(--muted);min-width:42px;text-align:right">0%</span></div><div style="display:flex;justify-content:space-between;margin-top:8px"><span id="dispense-entry-mass" style="font-size:13px;color:var(--muted)">-- mg</span><span id="dispense-entry-phase" style="font-size:13px;color:var(--muted)">--</span></div></div>';
document.querySelector('main').appendChild(dispenseEntryPanel);

const dispensePanel=document.createElement('section');
dispensePanel.className='panel';
dispensePanel.style.marginTop='18px';
dispensePanel.innerHTML='<div class="panel-head"><h2>500 mg 闭环加粉</h2><span id="dispense-state" class="status">待命</span></div><div style="padding:14px 16px;border-bottom:1px solid var(--line)"><div class="label">起始参数</div><div id="preset-control" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px"><button class="preset-button" data-preset="60hz-p150" style="border-color:var(--teal);color:var(--teal)">60 Hz · 20% · 150 · 膨润土</button><button class="preset-button" data-preset="slow-40hz-p250" style="border-color:var(--teal);color:var(--teal)">40 Hz · 20% · 250 · 熟石灰</button><button class="preset-button" data-preset="slow-10hz-p100" style="border-color:var(--teal);color:var(--teal)">10 Hz · 10% · 100 · 小苏打</button><button class="preset-button" data-preset="starch-70hz-p200" style="border-color:var(--orange);color:var(--orange)">70 Hz · 20% · 100 · 淀粉</button><button class="preset-button" data-preset="80hz-22pct-p350-water-loss-agent-2" data-exact-target="1000" style="display:none;border-color:var(--orange);color:var(--orange)">80Hz-22%-p350-失水剂2</button><button class="preset-button" data-preset="80hz-22pct-p300-bentonite" data-exact-target="1000" style="display:none;border-color:var(--teal);color:var(--teal)">80Hz-22%-p300-膨润土</button><button class="preset-button" data-preset="80hz-22pct-p400-plugging-agent-1" data-exact-target="1000" style="display:none;border-color:var(--blue);color:var(--blue)">80Hz-22%-p400-封堵剂1</button><button class="preset-button" data-preset="80hz-22pct-p400-plugging-agent-2" data-exact-target="1000" style="display:none;border-color:var(--blue);color:var(--blue)">80Hz-22%-p400-封堵剂2</button></div><div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px"><button id="tare-balance" class="command-button">天平标零</button><button id="start-500mg" class="command-button primary">启动 500 mg 加粉</button><button id="cancel-500mg" class="command-button danger" disabled>停止任务</button></div><div id="dispense-message" class="label" style="margin-top:9px">验收 490–515 mg</div></div><div class="metrics"><div class="metric"><div class="label">控制采样质量</div><div class="value" id="dispense-mass">--<span class="unit">mg</span></div></div><div class="metric"><div class="label">天平实时质量</div><div class="value" id="dispense-balance-mass">--<span class="unit">mg</span></div></div><div class="metric"><div class="label">最终稳定质量</div><div class="value" id="dispense-final-mass">--<span class="unit">mg</span></div></div><div class="metric"><div class="label">控制速率</div><div class="value" id="dispense-rate">--<span class="unit">mg/s</span></div></div><div class="metric"><div class="label">预计尾量</div><div class="value" id="dispense-tail">--<span class="unit">mg</span></div></div><div class="metric"><div class="label">预计停机质量</div><div class="value" id="dispense-projected">--<span class="unit">mg</span></div></div><div class="metric"><div class="label">占空比</div><div class="value" id="dispense-duty">--</div></div><div class="metric"><div class="label">窗口位置 / 阶段</div><div class="value" id="dispense-window" style="font-size:19px">--</div></div></div>';
document.querySelector('main').appendChild(dispensePanel);
const continuousTaperPanel=document.createElement('section');
continuousTaperPanel.className='panel';
continuousTaperPanel.style.marginTop='18px';
continuousTaperPanel.innerHTML='<div class="panel-head"><h2>500 mg 连续收敛独立测试</h2><span id="continuous-taper-state" class="status">待命</span></div><div style="padding:14px 16px;border-bottom:1px solid var(--line)"><div class="label">0–420 mg：位置 200 / 80 Hz / 20%；420 mg 后一次切换：位置 100 / 65 Hz / 16%，振动不中断</div><div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px"><button id="start-continuous-taper" class="command-button primary">启动连续收敛测试</button><button id="cancel-continuous-taper" class="command-button danger" disabled>停止连续收敛测试</button></div><div id="continuous-taper-message" class="label" style="margin-top:9px">自动标零；按原始质量、滤波质量和短时预测决定停机</div></div><div class="metrics"><div class="metric"><div class="label">控制采样质量</div><div class="value" id="continuous-taper-mass">--<span class="unit">mg</span></div></div><div class="metric"><div class="label">天平实时质量</div><div class="value" id="continuous-taper-balance">--<span class="unit">mg</span></div></div><div class="metric"><div class="label">最终稳定质量</div><div class="value" id="continuous-taper-final">--<span class="unit">mg</span></div></div><div class="metric"><div class="label">实时速率</div><div class="value" id="continuous-taper-rate">--<span class="unit">mg/s</span></div></div><div class="metric"><div class="label">预测停机质量</div><div class="value" id="continuous-taper-predicted">--<span class="unit">mg</span></div></div><div class="metric"><div class="label">阶段 / 命令</div><div class="value" id="continuous-taper-stage" style="font-size:19px">--</div></div><div class="metric"><div class="label">频率 / 占空比</div><div class="value" id="continuous-taper-vibration" style="font-size:19px">--</div></div><div class="metric"><div class="label">窗口位置</div><div class="value" id="continuous-taper-window">--</div></div></div>';
document.querySelector('main').appendChild(continuousTaperPanel);
const pidPanel=document.createElement('section');
pidPanel.className='panel';
pidPanel.style.marginTop='18px';
pidPanel.innerHTML='<div class="panel-head"><h2>窗口 PID 对照测试</h2><span id="pid-state" class="status">待命</span></div><div style="padding:14px 16px;border-bottom:1px solid var(--line)"><div class="label">固定 80 Hz / 20%；PID 只调整 LA10 窗口，目标 500 mg</div><div style="display:flex;gap:8px;margin-top:12px"><button id="start-window-pid" class="command-button primary">启动窗口 PID 测试</button><button id="cancel-window-pid" class="command-button danger" disabled>停止 PID 测试</button></div><div id="pid-message" class="label" style="margin-top:9px">粗加窗口 650，慢加窗口 200，精加窗口 100</div></div><div class="metrics"><div class="metric"><div class="label">当前质量</div><div class="value" id="pid-mass">--<span class="unit">mg</span></div></div><div class="metric"><div class="label">实时 / 目标速率</div><div class="value" id="pid-rate" style="font-size:19px">--</div></div><div class="metric"><div class="label">当前 / 计划窗口</div><div class="value" id="pid-window" style="font-size:19px">--</div></div><div class="metric"><div class="label">PID 修正 / 阶段</div><div class="value" id="pid-adjust" style="font-size:19px">--</div></div></div>';
document.querySelector('main').appendChild(pidPanel);
const dispenseStyle=document.createElement('style');
dispenseStyle.textContent='.preset-button,.command-button{width:auto;height:34px;padding:0 12px;font-size:13px}.preset-button.selected{border-color:var(--blue);background:#eaf5fa;color:#0f5c80}.command-button.primary{background:var(--blue);border-color:var(--blue);color:#fff}.command-button.danger{color:var(--red);border-color:#e4a7a2}.command-button:disabled,.preset-button:disabled{opacity:.45;cursor:not-allowed}';
document.head.appendChild(dispenseStyle);
dispenseStyle.textContent+='.dispense-inputs{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}.dispense-inputs label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted)}.dispense-inputs input{width:104px;height:32px;padding:0 8px;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--ink);font:inherit}.dispense-powder-select{width:min(420px,100%);height:34px;margin-top:8px;padding:0 8px;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--ink);font:inherit}';
let selectedDispensePreset='slow-70hz-p300';
let selectedDispenseTarget=500;
const DISPENSE_PRESET_VALUES={
  '60hz-p150':{frequency_hz:60,duty_permyriad:2000,window_position_units:150,target_mg:100},
  '60hz-p200':{frequency_hz:60,duty_permyriad:2000,window_position_units:200,target_mg:300},
  'slow-40hz-p250':{frequency_hz:40,duty_permyriad:2000,window_position_units:250,target_mg:100},
  'slow-10hz-p100':{frequency_hz:10,duty_permyriad:1000,window_position_units:100,target_mg:100},
  'steady-70hz-p100':{frequency_hz:70,duty_permyriad:2000,window_position_units:100,target_mg:100},
  'starch-70hz-p200':{frequency_hz:70,duty_permyriad:2000,window_position_units:100,target_mg:100},
  'slow-70hz-p300':{frequency_hz:70,duty_permyriad:2000,window_position_units:300,target_mg:500},
  '80hz-22pct-p350-water-loss-agent-2':{frequency_hz:80,duty_permyriad:2200,window_position_units:350,target_mg:1000},
  '80hz-22pct-p300-bentonite':{frequency_hz:80,duty_permyriad:2200,window_position_units:300,target_mg:1000},
  '80hz-22pct-p400-plugging-agent-1':{frequency_hz:80,duty_permyriad:2200,window_position_units:400,target_mg:1000},
  '80hz-22pct-p250-plugging-agent-2':{frequency_hz:80,duty_permyriad:2200,window_position_units:250,target_mg:1000}
};
const DISPENSE_TARGET_LIMITS={100:[90,110],300:[290,310],500:[490,510]};
const dispenseConfig=document.createElement('div');
dispenseConfig.id='dispense-config';
dispenseConfig.innerHTML='<div class="label">粉末类型（必选，决定过程控制配置）</div><select id="dispense-powder" class="dispense-powder-select"><option value="">正在加载粉末列表…</option></select><div class="label" style="margin-top:12px">目标质量</div><div id="dispense-target-control" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px"><button class="preset-button" data-dispense-target="100">100 mg</button><button class="preset-button" data-dispense-target="300">300 mg</button><button class="preset-button selected" data-dispense-target="500">500 mg</button></div><div style="display:flex;align-items:center;gap:8px;margin-top:8px"><label style="font-size:12px;color:var(--muted)">自定义质量</label><input id="dispense-custom-target" type="number" min="100" max="1000" step="1" placeholder="100–1000" style="width:80px;height:32px;padding:0 8px;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--ink);font:inherit"><span style="font-size:12px;color:var(--muted)">mg</span></div><div class="label" style="margin-top:12px">本次起始 Preset（允许修改，不改变粉末过程配置）</div><div class="dispense-inputs"><label>频率 Hz<input id="dispense-frequency" type="number" min="10" max="80" step="1" value="80"></label><label>占空比<input id="dispense-duty-input" type="number" min="1000" max="5000" step="50" value="2000"></label><label>窗口位置<input id="dispense-window-input" type="number" min="100" max="750" step="1" value="200"></label><label>重复次数<input id="dispense-repeats" type="number" min="1" max="20" step="1" value="1"></label></div><div style="display:flex;gap:8px;margin-top:8px"><button id="add-dispense-to-batch" class="command-button" style="width:auto">+ 添加到批量队列</button></div>';
const presetControl=el('preset-control');
presetControl.parentElement.insertBefore(dispenseConfig,presetControl);
function selectedDispensePowder(){
  const select=el('dispense-powder');
  const option=select&&select.selectedOptions[0];
  if(!select||!select.value||!option)return null;
  return {powder_id:select.value,powder_name:option.dataset.powderName||option.textContent};
}
async function refreshDispensePowders(){
  const select=el('dispense-powder');
  select.disabled=true;
  try{
    const response=await fetch('/api/dispense/powders',{cache:'no-store'});
    const list=await response.json();
    if(!response.ok)throw new Error(list.error||'粉末列表加载失败');
    select.innerHTML='<option value="">-- 请先选择粉末类型 --</option>';
    list.filter(fp=>fp.powder_id&&fp.powder_name&&fp.selectable!==false).forEach(fp=>{
      const option=document.createElement('option');
      option.value=fp.powder_id;
      option.dataset.powderName=fp.powder_name;
      option.textContent=fp.powder_name+(fp.config_source==='dedicated_profile'?'（专属配置）':'（默认配置）');
      select.appendChild(option);
    });
    if(select.options.length===1){
      select.options[0].textContent='没有可选粉末，请先建立粉末指纹';
    }
  }catch(error){
    select.innerHTML='<option value="">粉末列表加载失败</option>';
    el('dispense-message').textContent=error.message;
  }finally{
    select.disabled=false;
  }
}
function dispenseInitialFromInputs(){
  return {
    frequency_hz:Number(el('dispense-frequency').value),
    duty_permyriad:Number(el('dispense-duty-input').value),
    window_position_units:Number(el('dispense-window-input').value)
  };
}
function updateDispensePanelLabels(){
  const target=selectedDispenseTarget;
  const minAccept=target-10;
  const maxAccept=target+10;
  dispensePanel.querySelector('h2').textContent=target+' mg 闭环加粉';
  el('start-500mg').textContent='启动 '+target+' mg 加粉';
  el('dispense-message').textContent='验收 '+minAccept+'–'+maxAccept+' mg；粉末决定过程配置，起始 Preset 可修改';
}
function selectDispensePreset(presetId){
  selectedDispensePreset=presetId;
  const values=DISPENSE_PRESET_VALUES[presetId];
  if(values){
    el('dispense-frequency').value=values.frequency_hz;
    el('dispense-duty-input').value=values.duty_permyriad;
    el('dispense-window-input').value=values.window_position_units;
  }
  document.querySelectorAll('[data-preset]').forEach(item=>item.classList.toggle('selected',item.dataset.preset===presetId));
}
function filterPresetsByTarget(target){
  const standardTargets=[100,300,500,1000];
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
      const exactTarget=Number(btn.dataset.exactTarget||0);
      btn.style.display=exactTarget&&exactTarget!==target?'none':'';
      if(exactTarget&&exactTarget!==target)return;
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
    selectedDispensePreset='slow-70hz-p300';
  }
}
document.querySelectorAll('[data-preset]').forEach(button=>button.addEventListener('click',()=>selectDispensePreset(button.dataset.preset)));
document.querySelectorAll('[data-dispense-target]').forEach(button=>button.addEventListener('click',()=>{
  selectedDispenseTarget=Number(button.dataset.dispenseTarget);
  document.querySelectorAll('[data-dispense-target]').forEach(item=>item.classList.toggle('selected',item===button));
  updateDispensePanelLabels();
  filterPresetsByTarget(selectedDispenseTarget);
}));
// Custom target input: sync selectedDispenseTarget on change
el('dispense-custom-target').addEventListener('input',()=>{
  const raw=el('dispense-custom-target').value.trim();
  if(raw===''){
    document.querySelectorAll('[data-exact-target]').forEach(button=>button.style.display='none');
    el('start-500mg').disabled=true;
    el('dispense-message').textContent='请输入 100–1000 mg 之间的整数质量';
    return;
  }
  const value=Number(raw);
  if(Number.isNaN(value)||!Number.isInteger(value)||value<100||value>1000){
    document.querySelectorAll('[data-exact-target]').forEach(button=>button.style.display='none');
    el('start-500mg').disabled=true;
    el('dispense-message').textContent='请输入 100–1000 mg 之间的整数质量';
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
  button.addEventListener('click',()=>{
    el('dispense-custom-target').value=selectedDispenseTarget;
  });
});
updateDispensePanelLabels();
filterPresetsByTarget(500);

async function postCommand(path,payload={}){
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const result=await response.json();
  if(!response.ok)throw new Error(result.error||'操作失败');
  return result;
}
async function tareBalance(){
  const button=el('tare-balance');button.disabled=true;el('dispense-message').textContent='正在标零并等待天平稳定';
  try{const result=await postCommand('/api/balance/tare');el('dispense-message').textContent='标零完成，当前 '+result.after_raw_count+' mg，'+(result.stable?'稳定':'未稳定')}catch(error){el('dispense-message').textContent=error.message}finally{button.disabled=false}
}
async function startLegacy500mg(){
  if(!confirm('确认容器已放好并启动 500 mg 加粉？'))return;
  try{const result=await postCommand('/api/dispense-500mg/start',{preset_id:selectedDispensePreset});el('dispense-message').textContent='任务已启动：'+result.run_id}catch(error){el('dispense-message').textContent=error.message}
}
async function cancelLegacy500mg(){
  try{await postCommand('/api/dispense-500mg/cancel');el('dispense-message').textContent='已请求停止，正在关闭振动'}catch(error){el('dispense-message').textContent=error.message}
}
async function startContinuousTaper(){
  if(!confirm('确认容器已放好并启动 500 mg 连续收敛独立测试？'))return;
  try{const result=await postCommand('/api/continuous-taper/start');el('continuous-taper-message').textContent='任务已启动：'+result.run_id}catch(error){el('continuous-taper-message').textContent=error.message}
}
async function cancelContinuousTaper(){
  try{await postCommand('/api/continuous-taper/cancel');el('continuous-taper-message').textContent='已请求停止，正在关闭振动'}catch(error){el('continuous-taper-message').textContent=error.message}
}
function renderContinuousTaperState(test){
  const running=test&&test.status==='running';
  const isContinuous=String(test&&test.run_id||'').startsWith('continuous-taper-500mg-');
  const sample=isContinuous?test.latest_sample:null;
  const finalMass=isContinuous&&test.result?test.result.final_mass_mg:null;
  const value=(number,digits=1)=>number==null?'--':Number(number).toFixed(digits);
  el('start-continuous-taper').disabled=running;
  el('cancel-continuous-taper').disabled=!(running&&isContinuous);
  el('continuous-taper-state').textContent=running&&isContinuous?'运行中':isContinuous&&test.status!=='running'?test.status:'待命';
  el('continuous-taper-mass').innerHTML=value(sample&&sample.mass_mg)+'<span class="unit">mg</span>';
  el('continuous-taper-final').innerHTML=value(finalMass)+'<span class="unit">mg</span>';
  el('continuous-taper-rate').innerHTML=value(sample&&sample.rate_mg_s,2)+'<span class="unit">mg/s</span>';
  el('continuous-taper-predicted').innerHTML=value(sample&&sample.projected_stop_mass_mg)+'<span class="unit">mg</span>';
  el('continuous-taper-stage').textContent=sample?sample.stage+' / '+sample.command:'--';
  el('continuous-taper-vibration').textContent=sample?sample.frequency_hz+' Hz / '+(sample.duty_permyriad/100).toFixed(1)+'%':'--';
  el('continuous-taper-window').textContent=sample?sample.window_position_units:'--';
  if(running&&isContinuous)el('continuous-taper-message').textContent='阶段 '+(test.phase||'-')+'，'+(sample?sample.reason:'准备设备');
  if(isContinuous&&test.status==='failed')el('continuous-taper-message').textContent=(test.result&&(test.result.error||test.result.acceptance_error||test.result.final_stability_error))||'连续收敛测试失败';
  if(isContinuous&&test.status==='completed')el('continuous-taper-message').textContent='连续收敛测试完成，最终稳定质量 '+value(finalMass)+' mg';
  if(isContinuous&&test.status==='cancelled')el('continuous-taper-message').textContent='连续收敛测试已取消，振动已关闭';
}
function renderContinuousTaperBalance(balance){
  const mass=balance&&balance.online?balance.raw_weight_mg:null;
  el('continuous-taper-balance').innerHTML=(mass==null?'--':Number(mass).toFixed(1))+'<span class="unit">mg</span>';
}
async function startWindowPid(){
  if(!confirm('确认容器已放好并启动窗口 PID 500 mg 对照测试？'))return;
  try{const result=await postCommand('/api/window-pid/start');el('pid-message').textContent='PID 任务已启动：'+result.run_id}catch(error){el('pid-message').textContent=error.message}
}
async function cancelWindowPid(){
  try{await postCommand('/api/window-pid/cancel');el('pid-message').textContent='已请求停止，正在关闭振动'}catch(error){el('pid-message').textContent=error.message}
}
function renderWindowPidState(test){
  const running=test&&test.status==='running';
  const isPid=String(test&&test.run_id||'').startsWith('window-pid-500mg-');
  const sample=isPid?test.latest_sample:null;
  const value=(number,digits=1)=>number==null?'--':Number(number).toFixed(digits);
  el('start-window-pid').disabled=running;
  el('cancel-window-pid').disabled=!(running&&isPid);
  el('pid-state').textContent=running&&isPid?'运行中':isPid&&test.status!=='running'?test.status:'待命';
  el('pid-mass').innerHTML=value(sample&&sample.mass_mg)+'<span class="unit">mg</span>';
  el('pid-rate').textContent=sample?value(sample.rate_mg_s,2)+' / '+value(sample.target_rate_mg_s,2)+' mg/s':'--';
  el('pid-window').textContent=sample?value(sample.window_position_units,0)+' / '+value(sample.planned_window_position_units,0):'--';
  el('pid-adjust').textContent=sample?(sample.pid_adjust_units>=0?'+':'')+sample.pid_adjust_units+' / '+sample.stage:'--';
  if(running&&isPid)el('pid-message').textContent='阶段 '+(test.phase||'-')+'，尾量预测 '+value(sample&&sample.predicted_tail_mg,2)+' mg';
  if(isPid&&test.status==='failed')el('pid-message').textContent=(test.result&&((test.result.error||test.result.acceptance_error)))||'PID 测试失败';
  if(isPid&&test.status==='completed')el('pid-message').textContent='PID 测试完成，振动已关闭';
}
function renderLegacy500mgState(test){
  const running=test&&test.status==='running';
  const isDispense=String(test&&test.run_id||'').startsWith('dispense-500mg-');
  const sample=isDispense?test.latest_sample:null;
  const finalMass=isDispense&&test.result?test.result.final_mass_mg:null;
  const value=(number,digits=1)=>number==null?'--':Number(number).toFixed(digits);
  document.querySelectorAll('[data-preset]').forEach(button=>button.disabled=running);
  el('tare-balance').disabled=running;el('start-500mg').disabled=running;el('cancel-500mg').disabled=!(running&&isDispense);
  el('dispense-state').textContent=running&&isDispense?'运行中':isDispense&&test.status!=='running'?test.status:'待命';
  el('dispense-mass').innerHTML=value(sample&&sample.mass_mg)+'<span class="unit">mg</span>';
  el('dispense-final-mass').innerHTML=value(finalMass)+'<span class="unit">mg</span>';
  el('dispense-rate').innerHTML=value(sample&&sample.control_rate_mg_s,2)+'<span class="unit">mg/s</span>';
  el('dispense-tail').innerHTML=value(sample&&sample.estimated_tail_mg,1)+'<span class="unit">mg</span>';
  el('dispense-projected').innerHTML=value(sample&&sample.projected_stop_mass_mg,1)+'<span class="unit">mg</span>';
  el('dispense-duty').textContent=sample?sample.duty_permyriad+' ('+(sample.duty_permyriad/100).toFixed(1)+'%)':'--';
  el('dispense-window').textContent=sample?sample.window_position_units+' / '+sample.stage:'--';
  if(running&&isDispense)el('dispense-message').textContent='阶段 '+(test.phase||'-')+'，目标速率 '+value(sample&&sample.target_rate_mg_s,1)+' mg/s';
  if(isDispense&&test.status==='failed')el('dispense-message').textContent=(test.result&&test.result.error)||'任务失败';
  if(isDispense&&test.status==='completed')el('dispense-message').textContent='500 mg 任务完成，振动已关闭';
}
function renderDispenseBalance(balance){
  const mass=balance&&balance.online?balance.raw_weight_mg:null;
  el('dispense-balance-mass').innerHTML=(mass==null?'--':Number(mass).toFixed(1))+'<span class="unit">mg</span>';
}
function renderDispenseState(test){
  const running=test&&test.status==='running';
  const isDispense=String(test&&test.run_id||'').startsWith('dispense-');
  const submitted=isDispense?(test.submitted||{}):{};
  const result=isDispense?(test.result||{}):{};
  const target=Number(result.target_mass_mg||submitted.target_mg||selectedDispenseTarget);
  const acceptanceMin=Number(result.acceptance_min_mg||submitted.acceptance_min_mg||target-10);
  const acceptanceMax=Number(result.acceptance_max_mg||submitted.acceptance_max_mg||target+15);
  const sample=isDispense?test.latest_sample:null;
  const finalMass=isDispense?result.final_mass_mg:null;
  const value=(number,digits=1)=>number==null?'--':Number(number).toFixed(digits);
  document.querySelectorAll('[data-preset],[data-dispense-target],#dispense-config input,#dispense-config select').forEach(control=>control.disabled=running);
  el('tare-balance').disabled=running;
  el('start-500mg').disabled=running;
  el('cancel-500mg').disabled=!(running&&isDispense);
  el('dispense-state').textContent=running&&isDispense?'运行中':isDispense&&test.status!=='running'?test.status:'待命';
  el('dispense-mass').innerHTML=value(sample&&sample.mass_mg)+'<span class="unit">mg</span>';
  el('dispense-final-mass').innerHTML=value(finalMass)+'<span class="unit">mg</span>';
  el('dispense-rate').innerHTML=value(sample&&sample.control_rate_mg_s,2)+'<span class="unit">mg/s</span>';
  el('dispense-tail').innerHTML=value(sample&&sample.estimated_tail_mg,1)+'<span class="unit">mg</span>';
  el('dispense-projected').innerHTML=value(sample&&sample.projected_stop_mass_mg,1)+'<span class="unit">mg</span>';
  el('dispense-duty').textContent=sample?sample.duty_permyriad+' ('+(sample.duty_permyriad/100).toFixed(1)+'%)':'--';
  el('dispense-window').textContent=sample?sample.window_position_units+' / '+sample.stage:'--';
  if(running&&isDispense)el('dispense-message').textContent='目标 '+target+' mg；阶段 '+(test.phase||'-')+'；目标速率 '+value(sample&&sample.target_rate_mg_s,1)+' mg/s';
  if(isDispense&&test.status==='failed')el('dispense-message').textContent=(result.error||result.acceptance_error||result.final_stability_error||'任务失败');
  if(isDispense&&test.status==='completed')el('dispense-message').textContent=target+' mg 任务完成，最终稳定质量 '+value(finalMass)+' mg，验收 '+acceptanceMin.toFixed(0)+'-'+acceptanceMax.toFixed(0)+' mg';
  if(isDispense&&test.status==='cancelled')el('dispense-message').textContent=target+' mg 任务已取消，振动已关闭';
}
async function start500mg(){
  const powder=selectedDispensePowder();
  if(!powder){el('dispense-message').textContent='请先选择粉末类型，再启动加粉';return;}
  const initial=dispenseInitialFromInputs();
  const valid=Number.isInteger(initial.frequency_hz)&&initial.frequency_hz>=10&&initial.frequency_hz<=80
    &&Number.isInteger(initial.duty_permyriad)&&initial.duty_permyriad>=1000&&initial.duty_permyriad<=5000
    &&Number.isInteger(initial.window_position_units)&&initial.window_position_units>=100&&initial.window_position_units<=750;
  if(!valid){el('dispense-message').textContent='起始参数无效：频率 10-80 Hz，占空比 1000-5000，窗口位置 100-750';return;}
  if(!confirm('确认粉末为“'+powder.powder_name+'”、容器已放好，并启动 '+selectedDispenseTarget+' mg 加粉？'))return;
  try{
    const result=await postCommand('/api/dispense/start',{...powder,target_mg:selectedDispenseTarget,preset_id:selectedDispensePreset,initial});
    el('dispense-message').textContent='任务已启动：'+result.run_id;
  }catch(error){el('dispense-message').textContent=error.message;}
}
async function cancel500mg(){
  try{await postCommand('/api/dispense/cancel');el('dispense-message').textContent='已请求停止，正在关闭振动';}
  catch(error){el('dispense-message').textContent=error.message;}
}
el('tare-balance').addEventListener('click',tareBalance);
el('start-500mg').addEventListener('click',start500mg);
el('cancel-500mg').addEventListener('click',cancel500mg);
el('add-dispense-to-batch').addEventListener('click',()=>{
  const powder=selectedDispensePowder();
  if(!powder){el('dispense-message').textContent='请先选择粉末类型，再添加批量任务';return;}
  const initial=dispenseInitialFromInputs();
  const repeats=Number(el('dispense-repeats').value);
  if(repeats<1||repeats>20){el('dispense-message').textContent='重复次数需在 1-20 之间';return;}
  const differentPowder=batchQueue.find(item=>item.type==='feedback_dispense'&&item.powder_id!==powder.powder_id);
  if(differentPowder){el('dispense-message').textContent='同一批量队列只能使用一种粉末；请先清空现有加粉任务';return;}
  batchQueue.push({
    type:'feedback_dispense',
    ...powder,
    target_mg:selectedDispenseTarget,
    preset_id:selectedDispensePreset,
    frequency_hz:initial.frequency_hz,
    duty_permyriad:initial.duty_permyriad,
    window_position_units:initial.window_position_units,
    repeat_count:repeats,
  });
  renderBatchQueue();
  el('dispense-message').textContent=powder.powder_name+' 已添加到批量队列（共 '+batchQueue.length+' 组）';
});
el('start-continuous-taper').addEventListener('click',startContinuousTaper);
el('cancel-continuous-taper').addEventListener('click',cancelContinuousTaper);
el('start-window-pid').addEventListener('click',startWindowPid);
el('cancel-window-pid').addEventListener('click',cancelWindowPid);

function renderSweepState(test){
  const state=el('sweep-state');
  const running=test&&test.status==='running';
  const isSweep=running&&String(test.run_id||'').startsWith('window-sweep-');
  el('start-sweep').disabled=running;
  if(isSweep){
    state.textContent='位置扫描运行中';
    el('sweep-progress').textContent='第 '+(test.segment_index||'-')+' / '+(test.segment_count||'-')+' 点';
    el('sweep-detail').textContent='目标位置 '+(test.target_window_position_units||'-')+'，阶段：'+(test.phase||'-');
  }else if(running){
    state.textContent='其他任务运行中';
    el('sweep-progress').textContent='已锁定';
    el('sweep-detail').textContent='当前任务完成后才可启动位置扫描';
  }else{
    state.textContent='待命';
    el('sweep-progress').textContent='未运行';
    el('sweep-detail').textContent='100 至 750，每 50；80 Hz；占空比 20%；每点 10 s';
  }
}
async function loadDispensePlans(){
  try{
    const response=await fetch('/api/dispense-plans',{cache:'no-store'});
    const plans=await response.json();
    el('dispense-plans').innerHTML=plans.map(plan=>chip('目标 '+plan.target_mg+' mg：粗加至 '+plan.coarse_end_mg+' mg（80%），随后反馈控制','ok')).join('');
  }catch(error){el('dispense-plans').innerHTML=chip('控制计划读取失败','bad')}
}
async function startWindowSweep(){
  const payload={position_schedule:[100,150,200,250,300,350,400,450,500,550,600,650,700,750],window_speed_mm_s:1.0,window_timeout_s:20,frequency_hz:80,duty_permyriad:2000,duration_s:10};
  const response=await fetch('/api/window-position-sweep',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const result=await response.json();
  if(!response.ok){alert(result.error||'启动扫描失败');return}
  renderSweepState({status:'running',run_id:result.run_id,phase:'tare'});
}
el('start-sweep').addEventListener('click',startWindowSweep);
const legacyShowFeedState=showFeedState;
showFeedState=function(test){legacyShowFeedState(test);renderSweepState(test);renderDispenseState(test);renderContinuousTaperState(test);renderWindowPidState(test);renderGridState(test)};
loadDispensePlans();
refreshFeedState();setInterval(refreshFeedState,200);

// ===== 定速出粉测试面板 =====
const constRatePanel=document.createElement('section');
constRatePanel.className='panel';
constRatePanel.style.marginTop='18px';
constRatePanel.innerHTML='<div class="panel-head"><h2>定速出粉测试</h2><span id="const-rate-state" class="status">待命</span></div><div style="padding:14px 16px;border-bottom:1px solid var(--line)"><div class="label">输入期望的目标流速和初始振动参数，测试过程中反馈控制器自动调节占空比和窗口位置维持稳定流速。验收范围：目标 ±2 mg/s，CV ≤ 10%</div><div class="dispense-inputs" style="margin-top:8px"><label>目标流速 mg/s<input id="const-rate-target" type="number" min="3" max="50" step="0.5" value="10.0"></label><label>频率 Hz<input id="const-rate-frequency" type="number" min="10" max="80" step="1" value="40"></label><label>占空比 %<input id="const-rate-duty-pct" type="number" min="10" max="50" step="0.5" value="20.0"></label><label>窗口位置<input id="const-rate-window" type="number" min="100" max="750" step="1" value="300"></label><label>持续时间 s<input id="const-rate-duration" type="number" min="5" max="300" step="1" value="15"></label><label>重复次数<input id="const-rate-repeats" type="number" min="1" max="10" step="1" value="3"></label></div><div style="display:flex;gap:8px;margin-top:12px"><button id="start-const-rate" class="command-button primary">启动定速测试</button><button id="cancel-const-rate" class="command-button danger" disabled>停止测试</button><button id="add-to-batch" class="command-button" style="width:auto">+ 添加到批量队列</button></div><div id="const-rate-message" class="label" style="margin-top:9px">设置振动参数后启动，自动标零并测试</div></div><div class="metrics"><div class="metric"><div class="label">实时流速</div><div class="value" id="const-rate-rate">--<span class="unit">mg/s</span></div></div><div class="metric"><div class="label">当前质量</div><div class="value" id="const-rate-mass">--<span class="unit">mg</span></div></div><div class="metric"><div class="label">已过时间</div><div class="value" id="const-rate-elapsed">--<span class="unit">s</span></div></div><div class="metric"><div class="label">进度 / 峰值</div><div class="value" id="const-rate-progress" style="font-size:19px">--</div></div><div class="metric"><div class="label">当前段 CV% / 均值</div><div class="value" id="const-rate-cv" style="font-size:19px">--</div></div><div class="metric"><div class="label">判定</div><div class="value" id="const-rate-verdict" style="font-size:19px">--</div></div></div><div class="section-title">段测试结果</div><div style="overflow-x:auto"><table><thead><tr><th>段</th><th>平均流速</th><th>峰值</th><th>标准差</th><th>CV%</th><th>增量</th><th>流速判定</th><th>稳定性判定</th></tr></thead><tbody id="const-rate-segments"></tbody></table></div><div id="const-rate-summary" class="label" style="padding:14px 16px;color:var(--muted)"></div>';

// ===== 批量队列子面板 =====
const batchPanel=document.createElement('section');
batchPanel.className='panel';
batchPanel.style.marginTop='18px';
batchPanel.innerHTML='<div class="panel-head"><h2>批量测试队列</h2><span id="batch-state" class="status">就绪</span></div><div style="padding:14px 16px;border-bottom:1px solid var(--line)"><div class="label">队列中的参数组（当前 '+(document.getElementById('const-rate-repeats')?3:'--')+' 组）</div><div style="display:flex;gap:8px;margin-top:12px"><button id="run-batch" class="command-button primary">运行全部</button><button id="cancel-batch" class="command-button danger" disabled>停止批量</button><button id="clear-batch" class="command-button" style="width:auto">清空队列</button></div><div class="label" style="margin-top:9px"><label><input id="batch-tare-between" type="checkbox" checked> 组间自动标零</label></div></div><div style="overflow-x:auto"><table><thead><tr><th>#</th><th>类型</th><th>参数1</th><th>参数2</th><th>参数3</th><th>参数4</th><th>重复</th><th>操作</th></tr></thead><tbody id="batch-queue-body"></tbody></table></div><div id="batch-empty" class="label" style="padding:14px 16px;color:var(--muted)">队列为空，请在上方"定速出粉测试"面板中设置参数后点击"+ 添加到批量队列"</div><div class="section-title">批量结果对比</div><div style="overflow-x:auto"><table><thead><tr><th>#</th><th>频率</th><th>占空比</th><th>窗口</th><th>平均流速</th><th>CV%</th><th>启动延迟</th><th>终量</th><th>判定</th></tr></thead><tbody id="batch-results-body"></tbody></table></div><div id="batch-summary" class="label" style="padding:14px 16px;color:var(--muted)"></div>';
document.querySelector('main').appendChild(constRatePanel);
document.querySelector('main').appendChild(batchPanel);

// Grid state tracking — updated by poll loop to sync grid panel with test status
let gridWasRunning=false;
function renderGridState(test){
  const state=el('grid-state');
  const startBtn=el('grid-start');
  const cancelBtn=el('grid-cancel');
  const msg=el('grid-message');
  if(!state||!startBtn||!cancelBtn)return;
  const running=test&&test.status==='running';
  const runId=test&&test.run_id||'';
  const isGridTest=runId.startsWith('grid-');
  if(running&&isGridTest){
    state.textContent='扫描中';state.className='status warn';
    startBtn.disabled=true;cancelBtn.disabled=false;
    gridWasRunning=true;
  }else if(gridWasRunning&&!running){
    // Transitioned from running to done
    state.textContent=test.status==='completed'?'完成':test.status==='cancelled'?'已取消':'失败';
    state.className=test.status==='completed'?'status ok':test.status==='cancelled'?'status':'status bad';
    startBtn.disabled=false;cancelBtn.disabled=true;
    if(test.result&&test.result.set_results){
      const n=test.result.set_results.length;
      const passed=test.result.cross_set_summary?test.result.cross_set_summary.passed_sets:0;
      msg.textContent='扫描完成：'+n+'组，'+passed+'组通过';
    }
    gridWasRunning=false;
  }else if(!running&&isGridTest){
    // Grid test result available but wasn't actively watched
    state.textContent='完成';state.className='status ok';
    startBtn.disabled=false;cancelBtn.disabled=true;
    gridWasRunning=false;
  }
}

// ===== 网格扫描实验面板 =====
const gridPanel=document.createElement('section');
gridPanel.className='panel';
gridPanel.style.marginTop='18px';
gridPanel.innerHTML='<div class="panel-head"><h2>网格扫描实验</h2><span id="grid-state" class="status">就绪</span></div><div style="padding:14px 16px;border-bottom:1px solid var(--line)"><div class="label">选择预置模板后仍可修改参数列表；展开后也可逐行编辑，提交时以预览表中的参数为准。</div><div style="display:flex;gap:12px;margin-top:12px;flex-wrap:wrap;align-items:flex-end"><div><label style="font-size:12px">粉末/预置模板</label><select id="grid-template" style="width:220px"><option value="">-- 选择模板 --</option></select></div><div><label style="font-size:12px">持续时间 s</label><input id="grid-duration" type="number" min="5" max="60" value="15" style="width:70px"></div><div><label style="font-size:12px">重复次数</label><input id="grid-repeats" type="number" min="1" max="5" value="3" style="width:60px"></div><div><label style="font-size:12px"><input id="grid-tare" type="checkbox" checked> 组间标零</label></div><div><label style="font-size:12px"><input id="grid-autocollect" type="checkbox" checked> 自动写入工作空间</label></div></div><div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap"><div><label style="font-size:12px">频率列表 Hz（逗号分隔）</label><input id="grid-freqs" type="text" value="40,55,65" style="width:240px;padding:6px;border:1px solid var(--line);border-radius:4px"></div><div><label style="font-size:12px">占空比列表 %（逗号分隔）</label><input id="grid-duties" type="text" value="16,20" style="width:200px;padding:6px;border:1px solid var(--line);border-radius:4px"></div><div><label style="font-size:12px">窗口位置列表（逗号分隔）</label><input id="grid-windows" type="text" value="250" style="width:180px;padding:6px;border:1px solid var(--line);border-radius:4px"></div></div><div style="display:flex;gap:8px;margin-top:12px"><button id="grid-expand" class="command-button" style="width:auto">展开/重新生成</button><button id="grid-start" class="command-button primary" disabled>启动扫描</button><button id="grid-cancel" class="command-button danger" disabled>停止</button></div><div id="grid-message" class="label" style="margin-top:9px">选择模板或输入自定义网格，点击"展开/重新生成"预览</div></div><div style="overflow-x:auto"><table><thead><tr><th>#</th><th>频率 Hz</th><th>占空比 %</th><th>窗口</th><th>重复</th><th>操作</th></tr></thead><tbody id="grid-preview-body"><tr><td colspan="6" style="color:var(--muted)">未展开网格</td></tr></tbody></table></div><div id="grid-expand-info" class="label" style="padding:0 16px 8px;color:var(--muted)"></div>';

document.querySelector('main').appendChild(gridPanel);

// Grid state
let gridSets=[];
let gridPowderId='';
let gridPowderName='';

function parseList(str){return str.split(',').map(s=>Number(s.trim())).filter(n=>!isNaN(n))}

el('grid-expand').addEventListener('click',()=>{
  const freqs=parseList(el('grid-freqs').value);
  const duties=parseList(el('grid-duties').value);
  const windows=parseList(el('grid-windows').value);
  if(!freqs.length||!duties.length||!windows.length){
    el('grid-message').textContent='请填写至少一组频率和占空比';return;
  }
  gridSets=[];
  for(const f of freqs)for(const d of duties)for(const w of windows){
    gridSets.push({frequency_hz:f,duty_permyriad:Math.round(d*100),window_position_units:w});
  }
  const dur=Number(el('grid-duration').value);
  const reps=Number(el('grid-repeats').value);
  gridSets.forEach(s=>s.repeat_count=reps);
  renderGridPreview();
  el('grid-message').textContent='网格已展开，检查后点击"启动扫描"';
});
function updateGridSet(index,key,rawValue,scale=1){
  const value=Number(rawValue);
  if(!Number.isFinite(value)){el('grid-message').textContent='参数必须是数字';el('grid-start').disabled=true;return;}
  gridSets[index][key]=Math.round(value*scale);
  el('grid-message').textContent='参数已修改；启动时将按当前预览表提交';
}
function removeGridSet(index){
  gridSets.splice(index,1);
  renderGridPreview();
  el('grid-message').textContent='参数组已移除；启动时将按当前预览表提交';
}
function renderGridPreview(){
  const tbody=el('grid-preview-body');
  const reps=Number(el('grid-repeats').value);
  const dur=Number(el('grid-duration').value);
  tbody.innerHTML=gridSets.length?gridSets.map((s,i)=>`<tr><td>${i+1}</td><td><input type="number" min="10" max="80" step="1" value="${s.frequency_hz}" oninput="updateGridSet(${i},'frequency_hz',this.value)" style="width:72px"></td><td><input type="number" min="10" max="50" step="0.1" value="${(s.duty_permyriad/100).toFixed(1)}" oninput="updateGridSet(${i},'duty_permyriad',this.value,100)" style="width:72px"></td><td><input type="number" min="100" max="750" step="1" value="${s.window_position_units}" oninput="updateGridSet(${i},'window_position_units',this.value)" style="width:82px"></td><td>${reps}</td><td><button type="button" onclick="removeGridSet(${i})" style="width:auto;font-size:12px">移除</button></td></tr>`).join(''):'<tr><td colspan="6" style="color:var(--muted)">无参数组</td></tr>';
  gridSets.forEach(s=>s.repeat_count=reps);
  const totalTime=gridSets.length*dur*reps;
  el('grid-expand-info').textContent=`共 ${gridSets.length} 组参数，预计耗时约 ${Math.ceil(totalTime/60)} 分钟`;
  el('grid-start').disabled=gridSets.length===0;
}

['grid-freqs','grid-duties','grid-windows'].forEach(id=>el(id).addEventListener('input',()=>{
  gridSets=[];
  el('grid-preview-body').innerHTML='<tr><td colspan="6" style="color:var(--muted)">参数列表已修改，请点击“展开/重新生成”</td></tr>';
  el('grid-expand-info').textContent='';
  el('grid-start').disabled=true;
}));
['grid-duration','grid-repeats'].forEach(id=>el(id).addEventListener('change',()=>{if(gridSets.length)renderGridPreview()}));

el('grid-start').addEventListener('click',async()=>{
  if(!gridSets.length){alert('请先展开网格');return;}
  if(gridSets.length>20){alert('最多20组，当前'+gridSets.length+'组');return;}
  if(!confirm('确认将执行 '+gridSets.length+' 组网格扫描？请确保粉末已装载。'))return;
  const dur=Number(el('grid-duration').value);
  const reps=Number(el('grid-repeats').value);
  const tareBetween=el('grid-tare').checked;
  const autoCollect=el('grid-autocollect').checked;
  try{
    const payload={
      experiment_type:'constant_rate',
      powder_name:gridPowderName||'custom',
      powder_id:gridPowderId||'custom',
      sets:gridSets.map(s=>({frequency_hz:s.frequency_hz,duty_permyriad:s.duty_permyriad,window_position_units:s.window_position_units,duration_s:dur,repeat_count:reps})),
      duration_s:dur,repeat_count:reps,tare_between_sets:tareBetween,
      auto_collect:autoCollect,experiment_id:gridPowderId||'custom-scan',
    };
    const result=await postCommand('/api/experiment/grid/start',payload);
    el('grid-message').textContent='扫描已启动：'+result.run_id+'（'+result.expanded_sets+'组）';
    if(result.warnings&&result.warnings.length)el('grid-message').textContent+=' | ⚠ '+result.warnings.join('; ');
    el('grid-start').disabled=true;el('grid-cancel').disabled=false;
  }catch(error){el('grid-message').textContent=error.message;}
});

el('grid-cancel').addEventListener('click',async()=>{
  try{await postCommand('/api/constant-rate/cancel');el('grid-message').textContent='已请求停止';el('grid-cancel').disabled=true;el('grid-start').disabled=false;}
  catch(error){el('grid-message').textContent=error.message;}
});

// Load grid templates
const FALLBACK_TEMPLATES={
  'baking_soda_low_freq':{powder_name:'小苏打',powder_id:'baking_soda',experiment_type:'constant_rate',dimensions:[{name:'frequency_hz',values:[15,20,25,30]},{name:'duty_permyriad',values:[1000,1200]},{name:'window_position_units',values:[250]}],duration_s:20,repeat_count:3,tare_between_sets:true},
  'bentonite_mid_freq':{powder_name:'膨润土',powder_id:'bentonite',experiment_type:'constant_rate',dimensions:[{name:'frequency_hz',values:[40,65]},{name:'duty_permyriad',values:[2000,2400,2800]},{name:'window_position_units',values:[250]}],duration_s:20,repeat_count:3,tare_between_sets:true},
  'slaked_lime_mid_freq':{powder_name:'熟石灰',powder_id:'slaked_lime',experiment_type:'constant_rate',dimensions:[{name:'frequency_hz',values:[40,55,65]},{name:'duty_permyriad',values:[1600,2000]},{name:'window_position_units',values:[250]}],duration_s:20,repeat_count:3,tare_between_sets:true},
  'corn_starch_high_freq':{powder_name:'玉米淀粉',powder_id:'corn_starch',experiment_type:'constant_rate',dimensions:[{name:'frequency_hz',values:[50,55,60,65,70,75]},{name:'duty_permyriad',values:[2000]},{name:'window_position_units',values:[250]}],duration_s:15,repeat_count:3,tare_between_sets:true},
  'corn_starch_duty_sweep':{powder_name:'玉米淀粉（占空比）',powder_id:'corn_starch',experiment_type:'constant_rate',dimensions:[{name:'frequency_hz',values:[70]},{name:'duty_permyriad',values:[1600,2400]},{name:'window_position_units',values:[250]}],duration_s:15,repeat_count:3,tare_between_sets:true},
};
function populateTemplates(templates){
  const sel=el('grid-template');
  const existing=new Set(Array.from(sel.options).map(o=>o.value));
  for(const [key,t] of Object.entries(templates)){
    if(existing.has(key))continue;
    const opt=document.createElement('option');
    opt.value=key;opt.textContent=t.powder_name+' — '+t.dimensions.map(d=>d.name.split('_')[0]+'×'+t.dimensions[0].values.length).join(' × ');
    opt.dataset.spec=JSON.stringify(t);
    sel.appendChild(opt);
  }
}
(async()=>{
  try{
    const resp=await fetch('/api/experiment/grid/templates');
    if(!resp.ok)throw new Error('HTTP '+resp.status);
    const data=await resp.json();
    if(data.templates&&Object.keys(data.templates).length>0){
      populateTemplates(data.templates);
      el('grid-message').textContent='已加载 '+Object.keys(data.templates).length+' 个预置模板';
      return;
    }
  }catch(e){
    console.warn('Grid templates API unavailable, using fallback:', e.message);
  }
  populateTemplates(FALLBACK_TEMPLATES);
  el('grid-message').textContent='已加载离线模板（API 不可用）';
})();

el('grid-template').addEventListener('change',()=>{
  const opt=el('grid-template').selectedOptions[0];
  if(!opt||!opt.dataset.spec)return;
  const t=JSON.parse(opt.dataset.spec);
  gridPowderId=t.powder_id;
  gridPowderName=t.powder_name;
  el('grid-freqs').value=t.dimensions.find(d=>d.name==='frequency_hz')?.values.join(',')||'';
  el('grid-duties').value=(t.dimensions.find(d=>d.name==='duty_permyriad')?.values||[]).map(v=>v/100).join(',')||'';
  el('grid-windows').value=t.dimensions.find(d=>d.name==='window_position_units')?.values.join(',')||'250';
  el('grid-duration').value=t.duration_s;
  el('grid-repeats').value=t.repeat_count;
  el('grid-tare').checked=t.tare_between_sets;
  el('grid-message').textContent='已加载模板：'+t.powder_name;
  el('grid-expand').click();
});

const batchQueue=[];
renderBatchQueue();

function constantRateParamsFromInputs(){
  return {
    target_rate_mg_s:Number(el('const-rate-target').value),
    frequency_hz:Number(el('const-rate-frequency').value),
    duty_permyriad:Math.round(Number(el('const-rate-duty-pct').value)*100),
    window_position_units:Number(el('const-rate-window').value),
    duration_s:Number(el('const-rate-duration').value),
    repeat_count:Number(el('const-rate-repeats').value),
  };
}

el('start-const-rate').addEventListener('click',async()=>{
  const params=constantRateParamsFromInputs();
  if(params.duty_permyriad<1000||params.duty_permyriad>5000){el('const-rate-message').textContent='占空比需在 10%-50% 之间';return;}
  if(!confirm('确认容器已放好？将自动标零并启动定速出粉测试。'))return;
  try{
    const result=await postCommand('/api/constant-rate/start',params);
    el('const-rate-message').textContent='任务已启动：'+result.run_id;
  }catch(error){el('const-rate-message').textContent=error.message;}
});

el('cancel-const-rate').addEventListener('click',async()=>{
  try{await postCommand('/api/constant-rate/cancel');el('const-rate-message').textContent='已请求停止';}
  catch(error){el('const-rate-message').textContent=error.message;}
});

el('add-to-batch').addEventListener('click',()=>{
  const params=constantRateParamsFromInputs();
  if(params.duty_permyriad<1000||params.duty_permyriad>5000){el('const-rate-message').textContent='占空比需在 10%-50% 之间';return;}
  batchQueue.push({...params});
  renderBatchQueue();
  el('const-rate-message').textContent='已添加到批量队列（共 '+batchQueue.length+' 组）';
});

el('run-batch').addEventListener('click',async()=>{
  if(!batchQueue.length){alert('队列为空');return;}
  const constRate=batchQueue.filter(e=>e.type!=='feedback_dispense');
  const dispense=batchQueue.filter(e=>e.type==='feedback_dispense');
  if(constRate.length&&dispense.length){alert('队列中包含定速测试和加粉测试两种类型，请先清空一种后再运行。');return;}
  const sets=constRate.length?constRate:dispense;
  const isDispense=dispense.length>0;
  const powderLabel=isDispense&&sets[0]?('，粉末“'+sets[0].powder_name+'”'):'';
  if(!confirm('确认运行批量队列（'+sets.length+' 组'+powderLabel+'）？将自动依次执行。'))return;
  try{
    const tareBetween=el('batch-tare-between').checked;
    if(isDispense){
      const result=await postCommand('/api/dispense/batch',{sets:sets,tare_between_sets:tareBetween});
    }else{
      const result=await postCommand('/api/constant-rate/batch',{sets:sets,target_rate_mg_s:Number(el('const-rate-target').value),tare_between_sets:tareBetween});
    }
    el('batch-state').textContent='批量已启动';
  }catch(error){el('batch-state').textContent=error.message;}
});

el('cancel-batch').addEventListener('click',async()=>{
  try{await postCommand('/api/constant-rate/cancel');}
  catch(error){}
});

el('clear-batch').addEventListener('click',()=>{batchQueue.length=0;renderBatchQueue();});

function renderBatchQueue(){
  if(!batchQueue.length){
    el('batch-queue-body').innerHTML='<tr><td colspan="8" style="color:var(--muted)">队列为空</td></tr>';
    el('batch-empty').style.display='block';
  }else{
    el('batch-empty').style.display='none';
    el('batch-queue-body').innerHTML=batchQueue.map((p,i)=>{
      const isDisp=p.type==='feedback_dispense';
      const powderName=String(p.powder_name||'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
      const typeChip=isDisp?'<span class="chip ok">加粉</span><div style="margin-top:4px;font-size:11px">'+powderName+'</div>':'<span class="chip">定速</span>';
      const col2=isDisp?(p.target_mg+' mg'):(p.frequency_hz+' Hz');
      const col3=isDisp?(p.frequency_hz+' Hz'):((p.duty_permyriad/100).toFixed(1)+'%');
      const col4=isDisp?((p.duty_permyriad/100).toFixed(1)+'%'):p.window_position_units;
      const col5=isDisp?p.window_position_units:(p.duration_s+' s');
      const col6=isDisp?'-':(p.duration_s+' s');
      return '<tr><td class="num">'+(i+1)+'</td><td>'+typeChip+'</td><td class="num">'+col2+'</td><td class="num">'+col3+'</td><td class="num">'+col4+'</td><td class="num">'+col5+'</td><td class="num">'+p.repeat_count+'</td><td><button onclick="batchQueue.splice('+i+',1);renderBatchQueue()" style="width:auto;height:24px;font-size:11px;padding:0 6px">删除</button></td></tr>';
    }).join('');
  }
  const btn=el('add-to-batch');const btnD=el('add-dispense-to-batch');
  if(btn)btn.textContent='+ 添加到批量队列（'+batchQueue.length+' 组）';
  if(btnD)btnD.textContent='+ 添加到批量队列（'+batchQueue.length+' 组）';
}

function renderConstantRateState(test){
  const running=test&&test.status==='running';
  const isConstRate=!!(test&&test.run_id&&(String(test.run_id).startsWith('const-rate-')||String(test.run_id).startsWith('const-batch-')));
  const isDispBatch=!!(test&&test.run_id&&String(test.run_id).startsWith('disp-batch-'));
  const isBatch=!!(test&&test.run_id&&(String(test.run_id).startsWith('const-batch-')||String(test.run_id).startsWith('disp-batch-')));
  const isOurBatch=isBatch||isDispBatch;
  const sample=isConstRate?test.latest_sample:null;
  const result=isConstRate||isDispBatch?(test.result||{}):{};
  const value=(number,digits=1)=>number==null?'--':Number(number).toFixed(digits);

  el('start-const-rate').disabled=running;
  el('cancel-const-rate').disabled=!(running&&isConstRate&&!isBatch);
  el('add-to-batch').disabled=running;el('add-dispense-to-batch').disabled=running;
  el('run-batch').disabled=running;
  el('cancel-batch').disabled=!(running&&isBatch);
  el('clear-batch').disabled=running;

  if(isOurBatch&&running){
    const bs=test.batch_summary||{};
    const settling=isDispBatch&&test.phase==='final_settle';
    const liveMass=isDispBatch&&test.latest_sample?test.latest_sample.mass_mg:null;
    el('const-rate-state').textContent=isDispBatch?'加粉批量运行中':'批量运行中';
    el('const-rate-message').textContent=settling
      ?'停振后持续读取天平：'+value(liveMass,1)+' mg'
      :'批量：已完成 '+bs.completed+'/'+bs.total+' 组，通过 '+bs.passed_so_far+' 组';
    el('const-rate-rate').innerHTML='--<span class="unit">mg/s</span>';
    el('const-rate-mass').innerHTML=isDispBatch&&liveMass!=null
      ?value(liveMass,1)+'<span class="unit">mg</span>'
      :'--<span class="unit">mg</span>';
    el('const-rate-elapsed').innerHTML='--<span class="unit">s</span>';
    el('const-rate-progress').textContent=settling
      ?'停振后沉降 '+value(test.latest_sample&&test.latest_sample.elapsed_after_stop_s,1)+' s'
      :(test.phase||'--');
    el('const-rate-cv').textContent='--';
    el('const-rate-verdict').textContent='--';
    el('batch-state').textContent='运行中 ('+bs.completed+'/'+bs.total+')';
    if(result.set_results&&result.set_results.length){
      el('batch-results-body').innerHTML=result.set_results.map((sr,i)=>{
        const s=sr.summary||{};
        const passed=sr.result==='completed'&&(s.overall_passed!==false)&&!sr.error;
        const failed=sr.result==='failed'||sr.error;
        const statusChip=passed?'<span class="chip ok">通过</span>':failed?'<span class="chip bad">失败</span>':'<span class="chip warn">'+sr.result+'</span>';
        if(isDispBatch){
          return '<tr><td class="num">'+(i+1)+'</td><td class="num">'+sr.frequency_hz+'</td><td class="num">'+(sr.duty_permyriad/100).toFixed(1)+'</td><td class="num">'+sr.window_position_units+'</td><td class="num">'+value(s.final_mass_mg,1)+'</td><td class="num">'+value(s.actual_duration_s,1)+'</td><td class="num">'+value(sr.startup_delay_s,3)+'</td><td class="num">'+(sr.acceptance_passed?'<span class="chip ok">√</span>':'<span class="chip bad">×</span>')+'</td><td>'+statusChip+'</td></tr>';
        }else{
          return '<tr><td class="num">'+(i+1)+'</td><td class="num">'+sr.frequency_hz+'</td><td class="num">'+(sr.duty_permyriad/100).toFixed(1)+'</td><td class="num">'+sr.window_position_units+'</td><td class="num">'+value(s.overall_mean_rate_mg_s,2)+'</td><td class="num">'+value(s.overall_cv_pct,2)+'</td><td class="num">'+value(sr.startup_delay_s,3)+'</td><td class="num">'+value(sr.final_mass_mg,1)+'</td><td>'+statusChip+'</td></tr>';
        }
      }).join('');
      const cross=result.cross_set_summary||{};
      el('batch-summary').innerHTML=isDispBatch
        ?'完成 '+cross.total_sets+' 组，通过 '+cross.passed_sets+' 组（'+(cross.pass_rate||0)+'%），平均终量 '+value(cross.avg_final_mass_mg,1)+' mg'
        :'完成 '+cross.total_sets+' 组，通过 '+cross.passed_sets+' 组（'+(cross.pass_rate||0)+'%），最佳：第 '+(cross.best_set_index||'--')+' 组 ('+value(cross.best_mean_rate_mg_s,2)+' mg/s)';
    }
    return;
  }

  const locked=sample&&sample.locked;
  const clogged=sample&&sample.clogged;
  if(clogged){
    el('const-rate-state').textContent='疑似卡粉';
    el('const-rate-state').style.color='var(--red)';
  }else if(locked){
    el('const-rate-state').textContent='参数已锁定';
    el('const-rate-state').style.color='var(--green)';
  }else{
    el('const-rate-state').textContent=running&&isConstRate?(sample&&sample.rate_valid?'反馈调节中':'开环等待'):isConstRate&&test.status!=='running'?test.status:'待命';
    el('const-rate-state').style.color='';
  }
  el('batch-state').textContent=running?'锁定中':(batchQueue.length?batchQueue.length+' 组待运行':'就绪');

  if(sample){
    el('const-rate-rate').innerHTML=value(sample.rate_mg_s,2)+'<span class="unit">mg/s</span>';
    el('const-rate-mass').innerHTML=value(sample.mass_mg,1)+'<span class="unit">mg</span>';
    el('const-rate-elapsed').innerHTML=value(sample.elapsed_s,1)+'<span class="unit">s</span>';
    const dutyPct=sample.duty_permyriad!=null?(sample.duty_permyriad/100).toFixed(1)+'%':'--';
    const win=sample.window_position_units!=null?sample.window_position_units:'--';
    el('const-rate-progress').textContent='第 '+sample.segment_index+'/'+(test.segment_count||'--')+' 段 | 峰值 '+value(sample.segment_peak_rate_mg_s,2);
    el('const-rate-cv').textContent='CV '+value(sample.segment_cv_pct,2)+'% | 均值 '+value(sample.segment_mean_rate_mg_s,2);
    const targetRate=sample.target_rate_mg_s!=null?sample.target_rate_mg_s:10.0;
    const meanOk=sample.segment_mean_rate_mg_s!=null&&Math.abs(sample.segment_mean_rate_mg_s-targetRate)<=2.0;
    const cvOk=sample.segment_cv_pct!=null&&sample.segment_cv_pct<=10.0;
    el('const-rate-verdict').innerHTML=(meanOk?'<span style="color:var(--green)">流速 ✓</span>':'<span style="color:var(--red)">流速 ✗</span>')+' / '+(cvOk?'<span style="color:var(--green)">CV ✓</span>':'<span style="color:var(--red)">CV ✗</span>');
    // feedback status line
    const freqHz=sample.frequency_hz!=null?sample.frequency_hz+'Hz':'--';
    const errSign=sample.rate_error_mg_s!=null?(sample.rate_error_mg_s>=0?'+':''):'';
    const feedbackInfo='频率 '+freqHz+' | 占空比 '+dutyPct+' | 窗口 '+win+' | 误差 '+errSign+value(sample.rate_error_mg_s,2)+' mg/s | '+((sample.feedback_reason||'').substring(0,40));
    if(running)el('const-rate-message').textContent='段 '+sample.segment_index+'/'+test.segment_count+'，段内已过 '+value(sample.segment_elapsed_s,1)+'s — '+feedbackInfo;
  }else if(!running&&isConstRate){
    // render final results
    const segments=result.segments||[];
    const summary=result.summary||{};
    if(segments.length){
      el('const-rate-segments').innerHTML=segments.map(s=>{
        const rateChip=s.rate_passed?'<span class="chip ok">✓</span>':'<span class="chip bad">✗</span>';
        const stabChip=s.stability_passed?'<span class="chip ok">✓</span>':'<span class="chip bad">✗</span>';
        return '<tr><td class="num">'+s.segment_index+'</td><td class="num">'+value(s.mean_rate_mg_s,2)+'</td><td class="num">'+value(s.peak_rate_mg_s,2)+'</td><td class="num">'+value(s.std_mg_s,3)+'</td><td class="num">'+value(s.cv_pct,2)+'</td><td class="num">'+value(s.mass_gain_mg,1)+'</td><td>'+rateChip+'</td><td>'+stabChip+'</td></tr>';
      }).join('');
      el('const-rate-summary').innerHTML='汇总：平均流速 '+value(summary.overall_mean_rate_mg_s,2)+' mg/s | 总体 CV '+value(summary.overall_cv_pct,2)+'% | 启动延迟 '+value(result.startup_delay_s,3)+' s | 最终质量 '+value(result.final_mass_mg,1)+' mg | '+(summary.overall_passed?'<span class="chip ok">整体通过</span>':'<span class="chip bad">未通过</span>');
    }
    if(!running)el('const-rate-message').textContent=test.status==='completed'?'测试完成，振动已关闭':test.status==='failed'?(result.error||'测试失败'):test.status==='cancelled'?'测试已取消':'';
  }
}

// Patch into main poll loop — just append our renderer
const legacyShowFeedStateCR=showFeedState;
showFeedState=function(test){legacyShowFeedStateCR(test);renderConstantRateState(test);};

// ===== 试验记录查询面板 =====
const recordsPanel=document.createElement('section');
recordsPanel.className='panel';
recordsPanel.style.marginTop='18px';
recordsPanel.innerHTML='<div class="panel-head"><h2>试验记录查询</h2><span id="records-state" class="status">就绪</span></div><div style="padding:14px 16px;border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:center;flex-wrap:wrap"><select id="records-filter-type" style="height:32px;border:1px solid var(--line);border-radius:4px;padding:0 8px;font-size:13px"><option value="">全部类型</option><option value="feedback_dispense_100mg">闭环加粉 (100mg)</option><option value="feedback_dispense_300mg">闭环加粉 (300mg)</option><option value="feedback_dispense_500mg">闭环加粉 (500mg)</option><option value="vibration_feed">振动喂料测试</option><option value="window_position_sweep">窗口位置扫描</option><option value="window_pid_dispense">窗口 PID 对照</option><option value="continuous_taper_dispense">连续收敛测试</option><option value="low_rate_startup_scan">低流量启动扫描</option><option value="constant_rate_dispense">定速出粉测试</option><option value="constant_rate_batch">定速批量测试</option><option value="at8811c_drift">天平漂移</option></select><label style="font-size:12px;color:var(--muted)">从 <input id="records-date-from" type="date" style="height:32px;border:1px solid var(--line);border-radius:4px;padding:0 6px;font-size:13px"></label><label style="font-size:12px;color:var(--muted)">至 <input id="records-date-to" type="date" style="height:32px;border:1px solid var(--line);border-radius:4px;padding:0 6px;font-size:13px"></label><select id="records-filter-result" style="height:32px;border:1px solid var(--line);border-radius:4px;padding:0 8px;font-size:13px"><option value="">全部结果</option><option value="passed">通过</option><option value="failed">失败</option></select><button id="records-query-btn" style="height:32px;padding:0 14px;font-size:13px;border:1px solid var(--line);border-radius:4px;background:var(--paper);cursor:pointer">查询</button></div><div class="metrics"><div class="metric"><div class="label">记录总数</div><div class="value" id="records-stat-total">--</div></div><div class="metric"><div class="label">通过率</div><div class="value" id="records-stat-passrate">--</div></div><div class="metric"><div class="label">平均最终质量</div><div class="value" id="records-stat-avgmass">--<span class="unit">mg</span></div></div><div class="metric"><div class="label">通过 / 失败</div><div class="value" id="records-stat-passfail" style="font-size:19px">--</div></div></div><div class="section-title">查询结果</div><div style="overflow-x:auto"><table><thead><tr><th>Run ID</th><th>日期</th><th>类型</th><th>结果</th><th>最终质量</th><th>目标</th><th>耗时</th><th>备注</th></tr></thead><tbody id="records-table-body"></tbody></table></div><div id="records-empty" class="label" style="padding:14px 16px;display:none;color:var(--muted)">未找到匹配的记录</div>';
document.querySelector('main').appendChild(recordsPanel);

const typeLabels={feedback_dispense_100mg:'闭环加粉(100mg)',feedback_dispense_300mg:'闭环加粉(300mg)',feedback_dispense_500mg:'闭环加粉(500mg)',feedback_dispense:'闭环加粉',vibration_feed:'振动喂料',window_position_sweep:'窗口扫描',window_pid_dispense:'窗口PID',continuous_taper_dispense:'连续收敛',low_rate_startup_scan:'低流量扫描',constant_rate_dispense:'定速出粉',constant_rate_batch:'定速批量',at8811c_drift:'天平漂移'};
el('records-query-btn').addEventListener('click',queryTestRecords);
setTimeout(queryTestRecords,500);

async function queryTestRecords(){
  el('records-state').textContent='查询中...';
  const params={};
  const tt=el('records-filter-type').value;if(tt)params.test_type=tt;
  const df=el('records-date-from').value;if(df)params.date_from=df.replace(/-/g,'');
  const dt=el('records-date-to').value;if(dt)params.date_to=dt.replace(/-/g,'');
  const rf=el('records-filter-result').value;if(rf)params.result=rf;
  try{
    const response=await fetch('/api/test-records?'+new URLSearchParams(params).toString(),{cache:'no-store'});
    const data=await response.json();
    renderTestRecords(data);
    el('records-state').textContent='完成 ('+data.summary.total+' 条)';
  }catch(error){
    el('records-state').textContent='加载失败';
    el('records-table-body').innerHTML='';
  }
}

function renderTestRecords(data){
  const s=data.summary;
  el('records-stat-total').textContent=s.total;
  el('records-stat-passrate').innerHTML=s.pass_rate_pct+'<span class="unit">%</span>';
  el('records-stat-avgmass').innerHTML=(s.avg_final_mass_mg!=null?s.avg_final_mass_mg.toFixed(1):'--')+'<span class="unit">mg</span>';
  el('records-stat-passfail').innerHTML='<span style="color:var(--green)">'+s.passed+' 通过</span> / <span style="color:var(--red)">'+s.failed+' 失败</span>';
  if(!data.records.length){el('records-table-body').innerHTML='';el('records-empty').style.display='block';return}
  el('records-empty').style.display='none';
  el('records-table-body').innerHTML=data.records.map(r=>{
    const statusChip=r.status==='passed'?'<span class="chip ok">通过</span>':'<span class="chip bad">失败</span>';
    const isConstRate=r.test_type==='constant_rate_dispense'||r.test_type==='constant_rate_batch';
    // 最终质量列：定速测试显示平均流速
    const massCol=isConstRate
      ?(r.overall_mean_rate_mg_s!=null?r.overall_mean_rate_mg_s.toFixed(2)+' mg/s':'--')
      :(r.final_mass_mg!=null?r.final_mass_mg.toFixed(1)+' mg':'--');
    // 目标列：定速测试显示 CV%
    const targetCol=isConstRate
      ?(r.overall_cv_pct!=null?r.overall_cv_pct.toFixed(1)+'%':'--')
      :(r.target_mass_mg!=null?r.target_mass_mg+' mg':'--');
    const dur=r.actual_duration_s!=null?r.actual_duration_s.toFixed(1)+' s':'--';
    const dateDisplay=r.date?r.date.slice(0,4)+'-'+r.date.slice(4,6)+'-'+r.date.slice(6,8):'';
    // 备注列追加定速测试的关键信息
    let noteText=r.error?'错误: '+r.error:(r.note||'');
    if(r.powder_name)noteText='粉末：'+r.powder_name+(noteText?'；'+noteText:'');
    if(isConstRate&&r.startup_delay_s!=null){
      noteText=(noteText?'':'')+'启动延迟 '+r.startup_delay_s.toFixed(2)+'s';
    }
    return '<tr><td class="num" style="font-size:12px">'+r.run_id+'</td><td>'+dateDisplay+'</td><td>'+(typeLabels[r.test_type]||r.test_type)+'</td><td>'+statusChip+'</td><td class="num">'+massCol+'</td><td class="num">'+targetCol+'</td><td class="num">'+dur+'</td><td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;color:var(--muted)">'+noteText+'</td></tr>';
  }).join('');
}

// ===== 粉末特征码 =====
let powderProbeTaskId=null;
let powderProbePollTimer=null;
let powderSummaryTimer=null;
let powderDetailVisible=false;
let powderCurrentTags=[];

function togglePowderDetail(){
  powderDetailVisible=!powderDetailVisible;
  el('powder-detail').style.display=powderDetailVisible?'':'none';
}

el('powder-category').addEventListener('click',togglePowderDetail);

el('apply-category-btn').addEventListener('click',async()=>{
  const category=el('powder-category-select').value;
  try{
    const result=await postCommand('/api/powder/category',{category:category});
    el('powder-category').textContent=category;
    el('powder-preset').textContent=result.preset_id||'--';
    el('detail-preset').textContent=result.preset_id||'--';
    el('detail-maxrate').textContent=result.maximum_flow_rate_mg_s||'--';
    el('detail-tail').textContent=result.fixed_tail_mass_mg||'--';
    el('category-change-msg').textContent='✅ 已应用（仅本次会话）';
    el('category-change-msg').style.color='var(--green)';
    // Update preset highlight
    highlightRecommendedPreset(result.preset_id);
    setTimeout(()=>{el('category-change-msg').textContent='';},3000);
  }catch(error){
    el('category-change-msg').textContent='❌ '+error.message;
    el('category-change-msg').style.color='var(--red)';
  }
});

function highlightRecommendedPreset(presetId){
  document.querySelectorAll('[data-preset]').forEach(btn=>{
    btn.classList.remove('recommended');
    if(btn.dataset.preset===presetId){
      btn.classList.add('recommended');
      btn.style.borderColor='var(--green)';
      btn.style.background='#eafaf1';
      btn.style.color='#1a7a3a';
    }else{
      btn.style.borderColor='';
      btn.style.background='';
      btn.style.color='';
    }
  });
}

function clearPresetHighlight(){
  document.querySelectorAll('[data-preset]').forEach(btn=>{
    btn.classList.remove('recommended');
    btn.style.borderColor='';
    btn.style.background='';
    btn.style.color='';
  });
}

async function refreshPowderStatus(){
  try{
    const resp=await fetch('/api/powder/status',{cache:'no-store'});
    const data=await resp.json();
    if(data.loaded){
      el('powder-status-label').textContent='已加载';
      el('powder-status-label').style.color='var(--green)';
      const rs=data.rate_search;
      if(rs&&rs.found&&rs.recommended){
        const rec=rs.recommended;
        const fr=Array.isArray(rs.frequency_hz_range)?(rs.frequency_hz_range[0]===rs.frequency_hz_range[1]?String(rs.frequency_hz_range[0]):rs.frequency_hz_range.join('–')):'--';
        const wr=Array.isArray(rs.window_units_range)?(rs.window_units_range[0]===rs.window_units_range[1]?String(rs.window_units_range[0]):rs.window_units_range.join('–')):'--';
        el('powder-message').textContent='✅ '+data.powder_name+' · 稳定 '+fr+' Hz / 窗 '+wr+' · 推荐 '+rec.frequency_hz+'Hz·窗'+rec.window_units+' ('+(rec.mean_rate_mg_s||0).toFixed(1)+' mg/s, CV '+(rec.cv_pct!=null?rec.cv_pct.toFixed(1):'--')+'%)';
        el('powder-message').style.color='var(--green)';
        el('powder-category').textContent='速率搜索';
        el('powder-preset').textContent=rec.frequency_hz+'Hz·窗'+rec.window_units;
        el('powder-rate').innerHTML=(rec.mean_rate_mg_s||0).toFixed(1)+'<span class="unit">mg/s</span>';
        el('powder-cv').innerHTML=(rec.cv_pct!=null?rec.cv_pct.toFixed(1):'--')+'<span class="unit">%</span>';
      }else{
        el('powder-message').textContent='✅ '+data.powder_name+' → '+data.category;
        el('powder-message').style.color='var(--green)';
        el('powder-category').textContent=data.category;
        el('powder-preset').textContent=data.preset_id||'--';
      }
      powderCurrentTags=data.tags||[];
      if(el('delete-powder-btn'))el('delete-powder-btn').disabled=false;
      // Update detail panel if visible
      el('powder-category-select').value=data.category||'Medium-flow';
      el('detail-preset').textContent=data.preset_id||'--';
      el('detail-maxrate').textContent=data.maximum_flow_rate_mg_s||'--';
      el('detail-tail').textContent=data.fixed_tail_mass_mg||'--';
      el('detail-tags').textContent=(data.tags||[]).join(', ')||'无';
      // Highlight recommended preset
      highlightRecommendedPreset(data.preset_id);
    }else{
      el('powder-status-label').textContent='未加载';
      el('powder-status-label').style.color='';
      el('powder-message').textContent='⚠ 未加载粉末指纹，使用默认参数';
      el('powder-message').style.color='';
      el('powder-category').textContent='--';
      el('powder-preset').textContent='--';
      el('powder-rate').innerHTML='--<span class="unit">mg/s</span>';
      el('powder-cv').innerHTML='--<span class="unit">%</span>';
      el('powder-delay').innerHTML='--<span class="unit">s</span>';
      el('powder-tail').innerHTML='--<span class="unit">mg</span>';
      if(el('delete-powder-btn'))el('delete-powder-btn').disabled=true;
      if(el('powder-detail'))el('powder-detail').style.display='none';
      powderDetailVisible=false;
      clearPresetHighlight();
    }
  }catch(e){}
}

async function refreshFingerprintList(){
  try{
    const resp=await fetch('/api/powder/fingerprints',{cache:'no-store'});
    const list=await resp.json();
    const select=el('powder-select');
    select.innerHTML='<option value="">+ 新粉末…</option>';
    list.forEach(fp=>{
      const opt=document.createElement('option');
      opt.value=fp.powder_id;
      opt.textContent=fp.powder_name+' ('+fp.category+')';
      select.appendChild(opt);
    });
  }catch(e){}
}

function showProbeProgress(show){
  el('probe-progress').style.display=show?'':'none';
}

async function startPowderProbe(){
  const select=el('powder-select');
  let powderName;
  if(select.value===''){
    powderName=prompt('请输入新粉末名称：');
    if(!powderName||!powderName.trim())return;
    powderName=powderName.trim();
    if(!confirm('即将对粉末 "'+powderName+'" 运行探针测试（约20秒），确认继续？'))return;
  }else{
    powderName=select.selectedOptions[0].textContent.split(' (')[0];
    if(!confirm('即将对粉末 "'+powderName+'" 重新运行探针测试（约20秒），确认继续？'))return;
  }
  try{
    const payload={powder_name:powderName,frequency_hz:40,duty_permyriad:2000,window_position_units:250,duration_s:10};
    const result=await postCommand('/api/powder/probe/start',payload);
    powderProbeTaskId=result.run_id;
    showProbeProgress(true);
    el('run-probe-btn').disabled=true;
    el('powder-message').textContent='探针运行中…';
    el('powder-message').style.color='var(--ink)';
    pollProbeProgress();
  }catch(error){
    el('powder-message').textContent='探针启动失败: '+error.message;
    el('powder-message').style.color='var(--red)';
  }
}

async function pollProbeProgress(){
  if(!powderProbeTaskId)return;
  try{
    const resp=await fetch('/api/powder/probe/'+powderProbeTaskId,{cache:'no-store'});
    const data=await resp.json();
    el('probe-phase').textContent=data.current_phase||'';
    el('probe-pct').textContent=(data.progress_pct||0).toFixed(0)+'%';
    el('probe-bar').style.width=(data.progress_pct||0)+'%';
    if(data.status==='idle'){
      // Probe finished
      clearInterval(powderProbePollTimer);
      powderProbePollTimer=null;
      powderProbeTaskId=null;
      el('run-probe-btn').disabled=false;
      showProbeProgress(false);
      if(data.result&&data.result.result==='completed'){
        refreshPowderStatus();
        refreshFingerprintList();
        el('powder-message').textContent='✅ '+data.result.powder_name+' → '+data.result.classification.category+' | '+data.result.feature_vector.steady_rate_mg_s.toFixed(1)+' mg/s';
        el('powder-message').style.color='var(--green)';
        el('powder-rate').innerHTML=data.result.feature_vector.steady_rate_mg_s.toFixed(1)+'<span class="unit">mg/s</span>';
        el('powder-cv').innerHTML=data.result.feature_vector.rate_cv_pct.toFixed(1)+'<span class="unit">%</span>';
        el('powder-delay').innerHTML=data.result.feature_vector.startup_delay_s.toFixed(2)+'<span class="unit">s</span>';
        el('powder-tail').innerHTML=data.result.feature_vector.tail_mass_mg.toFixed(1)+'<span class="unit">mg</span>';
        if(powderSummaryTimer)clearTimeout(powderSummaryTimer);
        powderSummaryTimer=setTimeout(()=>{
          el('powder-message').textContent='✅ '+data.result.powder_name+' → '+data.result.classification.category;
        },8000);
      }else{
        const errMsg=data.result?data.result.error:'探针失败';
        el('powder-message').textContent='❌ '+errMsg;
        el('powder-message').style.color='var(--red)';
      }
      return;
    }
    powderProbePollTimer=setTimeout(pollProbeProgress,300);
  }catch(e){
    powderProbePollTimer=setTimeout(pollProbeProgress,500);
  }
}

// ===== 速率搜索（目标带 10–30 mg/s） =====
let rateSearchTaskId=null;
let rateSearchPollTimer=null;

async function startRateSearch(){
  const select=el('powder-select');
  let powderName;
  if(select.value===''){
    powderName=prompt('请输入新粉末名称：');
    if(!powderName||!powderName.trim())return;
    powderName=powderName.trim();
  }else{
    powderName=select.selectedOptions[0].textContent.split(' (')[0];
  }
  if(!confirm('即将对粉末 "'+powderName+'" 运行速率搜索（约1–2分钟，自动寻找 10–30 mg/s 稳态窗口），确认继续？'))return;
  try{
    const result=await postCommand('/api/powder/rate-search/start',{powder_name:powderName,target_lo:10,target_hi:30});
    rateSearchTaskId=result.run_id;
    showProbeProgress(true);
    el('run-rate-search-btn').disabled=true;
    el('powder-message').textContent='速率搜索运行中…';
    el('powder-message').style.color='var(--ink)';
    pollRateSearchProgress();
  }catch(error){
    el('powder-message').textContent='速率搜索启动失败: '+error.message;
    el('powder-message').style.color='var(--red)';
  }
}

async function pollRateSearchProgress(){
  if(!rateSearchTaskId)return;
  try{
    // rate-search shares the global test-snapshot endpoint used by the probe.
    const resp=await fetch('/api/powder/probe/'+rateSearchTaskId,{cache:'no-store'});
    const data=await resp.json();
    el('probe-phase').textContent=data.current_phase||'';
    el('probe-pct').textContent=(data.progress_pct||0).toFixed(0)+'%';
    el('probe-bar').style.width=(data.progress_pct||0)+'%';
    if(data.status==='idle'){
      clearInterval(rateSearchPollTimer);
      rateSearchPollTimer=null;
      rateSearchTaskId=null;
      el('run-rate-search-btn').disabled=false;
      showProbeProgress(false);
      const res=data.result||{};
      const band=res.stable_band||{};
      if(res.result==='completed'&&band.found){
        const rec=band.recommended||{};
        const freqRange=Array.isArray(band.frequency_hz_range)?band.frequency_hz_range.join('–'):'--';
        el('powder-message').textContent='✅ '+res.powder_name+' 稳定 '+freqRange+' Hz | 推荐 '+rec.frequency_hz+'Hz/窗'+rec.window_units+' ('+(rec.mean_rate_mg_s||0).toFixed(1)+' mg/s)';
        el('powder-message').style.color='var(--green)';
        el('powder-rate').innerHTML=(rec.mean_rate_mg_s||0).toFixed(1)+'<span class="unit">mg/s</span>';
        el('powder-cv').innerHTML=(rec.cv_pct!=null?rec.cv_pct.toFixed(1):'--')+'<span class="unit">%</span>';
        el('powder-category').textContent='速率搜索';
        el('powder-preset').textContent=rec.frequency_hz+'Hz/窗'+rec.window_units;
        el('powder-delay').innerHTML='--<span class="unit">s</span>';
        el('powder-tail').innerHTML='--<span class="unit">mg</span>';
      }else{
        let errMsg='速率搜索未锁定';
        if(res.error)errMsg=res.error;
        else if(band.notes)errMsg=band.notes;
        el('powder-message').textContent='❌ '+errMsg;
        el('powder-message').style.color='var(--red)';
      }
      refreshPowderStatus();
      return;
    }
    rateSearchPollTimer=setTimeout(pollRateSearchProgress,300);
  }catch(e){
    rateSearchPollTimer=setTimeout(pollRateSearchProgress,500);
  }
}

async function selectPowder(powderId){
  if(!powderId){
    el('powder-message').textContent='⚠ 未加载粉末指纹，使用默认参数';
    el('powder-message').style.color='';
    return;
  }
  try{
    await postCommand('/api/powder/fingerprints/'+powderId+'/apply',{});
    refreshPowderStatus();
    el('powder-message').textContent='已加载粉末指纹';
    el('powder-message').style.color='var(--green)';
  }catch(error){
    el('powder-message').textContent='加载失败: '+error.message;
    el('powder-message').style.color='var(--red)';
  }
}

async function deleteSelectedPowder(){
  const select=el('powder-select');
  if(!select.value)return;
  const name=select.selectedOptions[0].textContent;
  if(!confirm('确认删除 '+name+' 的所有指纹版本？此操作不可撤销。'))return;
  try{
    const resp=await fetch('/api/powder/fingerprints/'+select.value,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const data=await resp.json();
    if(resp.ok){
      refreshFingerprintList();
      refreshPowderStatus();
      el('powder-message').textContent='已删除 '+name;
    }else{
      throw new Error(data.error||'删除失败');
    }
  }catch(error){
    el('powder-message').textContent='删除失败: '+error.message;
    el('powder-message').style.color='var(--red)';
  }
}

el('run-probe-btn').addEventListener('click',startPowderProbe);
el('run-rate-search-btn').addEventListener('click',startRateSearch);
el('powder-select').addEventListener('change',()=>selectPowder(el('powder-select').value));
el('delete-powder-btn').addEventListener('click',deleteSelectedPowder);

// Initial load
refreshFingerprintList();
refreshPowderStatus();

// Update powder status in main refresh cycle
const _originalRefresh=refresh;
refresh=async function(){
  await _originalRefresh();
  refreshPowderStatus();
};

// ===== 加粉控制（独立入口）逻辑 =====
let dispenseEntryActive=false;
let dispenseEntryTarget=0;

async function refreshDispenseEntryPowders(){
  try{
    const resp=await fetch('/api/dispense/powders',{cache:'no-store'});
    const list=await resp.json();
    const select=el('dispense-entry-powder');
    select.innerHTML='<option value="">-- 选择粉末 --</option>';
    list.forEach(profile=>{
      const opt=document.createElement('option');
      opt.value=profile.powder_id;
      opt.textContent=profile.powder_name+(profile.config_source==='dedicated_profile'?'（专属）':'（默认）');
      opt.dataset.powderName=profile.powder_name;
      opt.dataset.status=profile.status;
      opt.dataset.presetId=profile.recommended_preset_id;
      opt.dataset.configSource=profile.config_source;
      opt.dataset.warnings=(profile.generation_warnings||[]).join('；');
      opt.disabled=profile.selectable===false;
      select.appendChild(opt);
    });
  }catch(e){
    el('dispense-entry-info').textContent='粉末列表加载失败：'+e.message;
    el('dispense-entry-info').style.color='var(--red)';
  }
}

async function previewDispenseConfiguration(){
  const select=el('dispense-entry-powder');
  const powderId=select.value;
  const target=Number(el('dispense-entry-target').value);
  if(!powderId){el('dispense-entry-info').textContent='选择粉末后自动加载参数';el('dispense-entry-info').style.color='var(--muted)';return;}
  if(!Number.isInteger(target)||target<100||target>1000){el('dispense-entry-info').textContent='粉末已选择；输入 100–1000 mg 整数后显示实际控制配置';el('dispense-entry-info').style.color='var(--muted)';return;}
  try{
    el('dispense-entry-info').textContent='正在自动解析控制配置…';
    el('dispense-entry-info').style.color='var(--muted)';
    const resp=await fetch('/api/dispense/config?powder_id='+encodeURIComponent(powderId)+'&target_mg='+target,{cache:'no-store'});
    const config=await resp.json();
    if(!resp.ok)throw new Error(config.error||'控制配置加载失败');
    const p=config.profile;
    const initial=config.initial;
    const controller=config.controller;
    const source=config.config_source==='dedicated_profile'?'专属控制配置':'粉末指纹＋统一默认参数';
    const hold=controller.flow_hold_enabled?'，轻流量保持已启用':'';
    el('dispense-entry-info').textContent='✅ 已自动加载 '+source+'｜'+initial.frequency_hz+' Hz，'+(initial.duty_permyriad/100).toFixed(1)+'%，窗口 '+initial.window_position_units+'｜粗/细/精 '+p.coarse_rate_mg_s+'/'+p.fine_rate_mg_s+'/'+p.precision_rate_mg_s+' mg/s｜固定尾料 '+controller.fixed_tail_mass_mg+' mg｜占空比上限 '+(controller.max_duty_permyriad/100).toFixed(0)+'%'+hold;
    el('dispense-entry-info').style.color=config.control_profile_status==='draft'?'var(--amber)':'var(--green)';
  }catch(e){
    el('dispense-entry-info').textContent='❌ '+e.message;
    el('dispense-entry-info').style.color='var(--red)';
  }
}

el('dispense-entry-powder').addEventListener('change',previewDispenseConfiguration);
el('dispense-entry-target').addEventListener('change',previewDispenseConfiguration);

el('dispense-entry-start').addEventListener('click',async()=>{
  const raw=el('dispense-entry-target').value.trim();
  if(!raw){el('dispense-entry-info').textContent='请输入目标质量';el('dispense-entry-info').style.color='var(--red)';return;}
  const target=Number(raw);
  if(Number.isNaN(target)||!Number.isInteger(target)||target<100||target>1000){
    el('dispense-entry-info').textContent='目标质量需为 100–1000 整数';el('dispense-entry-info').style.color='var(--red)';return;
  }
  const powderId=el('dispense-entry-powder').value;
  if(!powderId){el('dispense-entry-info').textContent='请先选择粉末';el('dispense-entry-info').style.color='var(--red)';return;}
  try{
    el('dispense-entry-info').textContent='正在标零…';el('dispense-entry-info').style.color='';
    el('dispense-entry-start').disabled=true;
    const result=await postCommand('/api/dispense/start',{powder_id:powderId,target_mg:target});
    dispenseEntryActive=true;
    dispenseEntryTarget=target;
    el('dispense-entry-info').textContent='✅ 任务已启动：'+result.run_id;
    el('dispense-entry-info').style.color='var(--green)';
  }catch(e){
    el('dispense-entry-info').textContent='❌ '+e.message;
    el('dispense-entry-info').style.color='var(--red)';
    el('dispense-entry-start').disabled=false;
  }
});

function renderDispenseEntry(test){
  const isDispense=String(test&&test.run_id||'').startsWith('dispense-');
  const running=test&&test.status==='running';
  const sample=isDispense?test.latest_sample:null;
  const result=isDispense?(test.result||{}):{};
  const submitted=isDispense?(test.submitted||{}):{};
  const target=Number(result.target_mass_mg||submitted.target_mg||dispenseEntryTarget);
  const currentMass=sample?sample.mass_mg:(result.final_mass_mg||0);
  const phase=test&&test.phase?test.phase:(test&&test.status==='completed'?'完成':(test&&test.status==='failed'?'失败':'--'));
  const pct=target>0?Math.min(100,Math.max(0,currentMass/target*100)):0;

  el('dispense-entry-bar').style.width=pct.toFixed(1)+'%';
  el('dispense-entry-pct').textContent=pct.toFixed(0)+'%';
  el('dispense-entry-mass').textContent=(currentMass||0).toFixed(1)+' mg / '+target+' mg';
  el('dispense-entry-phase').textContent=phase;

  if(running&&isDispense){
    el('dispense-entry-state').innerHTML='<span style="color:var(--blue);font-weight:600">运行中</span>';
  }else if(isDispense&&test.status==='completed'){
    el('dispense-entry-state').innerHTML='<span style="color:var(--green);font-weight:600">完成</span>';
    el('dispense-entry-start').disabled=false;
    dispenseEntryActive=false;
  }else if(isDispense&&test.status==='failed'){
    el('dispense-entry-state').innerHTML='<span style="color:var(--red);font-weight:600">失败</span>';
    el('dispense-entry-start').disabled=false;
    dispenseEntryActive=false;
    el('dispense-entry-info').textContent='❌ '+(result.error||'任务失败');
    el('dispense-entry-info').style.color='var(--red)';
  }
}

// Patch into main poll loop
const _originalShowFeedState=showFeedState;
showFeedState=function(test){
  _originalShowFeedState(test);
  renderDispenseEntry(test||{status:'idle'});
};

refreshDispensePowders();
refreshDispenseEntryPowders();
</script></body></html>"""


def make_handler(reader: DeviceReader):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/snapshot":
                body = json.dumps(reader.snapshot(), ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
            elif path == "/":
                body = HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
            else:
                self.send_error(404)
                return
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    return DashboardHandler


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="local HTTP port")
    parser.add_argument("--at-port", default="COM9", help="AT8811C serial port")
    parser.add_argument("--at-address", type=int, default=1)
    parser.add_argument("--la10-port", default="COM8", help="LA10 serial port")
    parser.add_argument("--la10-address", type=int, default=1)
    parser.add_argument(
        "--balance-calibration",
        type=Path,
        default=PROJECT_ROOT / "config" / "devices" / "at8811c-calibration.json",
        help="validated count-to-mg calibration JSON",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    calibration = (
        load_balance_calibration(args.balance_calibration)
        if args.balance_calibration.exists()
        else None
    )
    reader = DeviceReader(
        args.at_port,
        args.la10_port,
        args.at_address,
        args.la10_address,
        balance_calibration=calibration,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(reader))
    print(f"dashboard: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        reader.close()


if __name__ == "__main__":
    from device_control_server import main as control_server_main

    control_server_main()
