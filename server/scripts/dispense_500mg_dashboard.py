"""Browser UI for the monitored 500 mg closed-loop dispensing task."""

HTML = r"""<!doctype html>
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
