<template>
  <PanelSection title="闭环加粉">
    <template #header-actions>
      <el-tag :type="isDispensing && store.isRunning ? 'warning' : 'info'" effect="plain">{{ statusLabel }}</el-tag>
    </template>
    <div class="dispense-layout">
      <section class="setup-section" aria-label="闭环加粉设置">
        <h3 class="section-heading">加粉设置</h3>
        <p class="section-note">选择粉末与目标质量，系统自动匹配控制参数。</p>
        <el-form label-position="top" :disabled="locked">
          <el-form-item label="粉末类型">
            <div class="row powder-row">
              <el-select v-model="powderId" filterable placeholder="请选择粉末类型" aria-label="粉末类型">
                <el-option v-for="p in powders" :key="p.powder_id" :value="p.powder_id" :disabled="p.selectable === false"
                  :label="p.powder_name + (p.config_source_label ? '（' + p.config_source_label + '）' : '')" />
              </el-select>
              <el-button @click="loadPowders">刷新列表</el-button>
            </div>
          </el-form-item>
          <el-form-item label="目标质量">
            <div class="target-controls">
              <div v-if="!largeMode" class="target-presets">
                <el-button v-for="t in [100,300,500,1000]" :key="t" :type="target === t ? 'primary' : 'default'" :plain="target === t" @click="target=t">{{ t }} mg</el-button>
              </div>
              <div v-if="!largeMode" class="row">
                <el-input-number v-model="target" :min="100" :max="1000" :step="1" aria-label="目标质量" />
                <span class="input-hint">mg · 支持 100–1000 mg 整数</span>
              </div>
              <div class="large-mode">
                <el-button :type="largeMode ? 'primary' : 'default'" :plain="!largeMode" @click="largeMode=!largeMode">大重量 1–10 g</el-button>
                <template v-if="largeMode">
                  <el-button v-for="g in [1,2,5,10]" :key="g" :type="largeTargetG === g ? 'primary' : 'default'" :plain="largeTargetG !== g" @click="largeTargetG=g">{{ g }} g</el-button>
                  <el-input-number v-model="largeTargetG" :min="1" :max="10" :step="1" aria-label="大重量目标" />
                  <el-input-number v-model="largeWindow" :min="0" :step="10" aria-label="大重量窗口位置" />
                  <span class="input-hint">窗口</span>
                  <span class="input-hint">1–10 g；80 Hz、窗口 700；预加粉阶段按下方占空比恒速加粉。</span>
                </template>
              </div>
              <div v-if="largeMode" class="large-duty-row">
                <span class="input-hint">预加粉占空比</span>
                <el-button v-for="d in [20,25,30]" :key="d" :type="largeDutyPercent === d ? 'primary' : 'default'" :plain="largeDutyPercent !== d" @click="largeDutyPercent=d">{{ d }}%</el-button>
                <el-input-number v-model="largeDutyPercent" :min="10" :max="50" :step="0.5" :precision="1" aria-label="大重量预加粉占空比" />
                <span class="input-hint">% · 10–50%；切回精加闭环后按粉末配置执行</span>
              </div>
            </div>
          </el-form-item>
          <el-alert v-if="largeMode" :title="'大重量模式尚未完成粉末实测标定，请在现场监督下运行。预加粉阶段固定使用 ' + largeDutyPercent + '% 占空比恒速加粉；' + largeReserveHint + '。'" type="warning" :closable="false" show-icon />
          <el-alert v-if="!largeMode && configError" :title="configError" type="error" :closable="false" show-icon />
          <el-alert v-else-if="!largeMode && loadingConfig" title="正在匹配控制配置…" type="info" :closable="false" />
          <el-alert v-else-if="!largeMode && config" :type="config.control_profile_status === 'validated' && !config.control_profile_warnings?.length ? 'success' : 'warning'" :closable="false" show-icon>
            <template #title>{{ config.control_profile_status === 'validated' ? '控制配置已验证' : '控制配置尚未验证，请在监督下使用' }}</template>
            <div>验收范围 {{ config.acceptance_min_mg }}–{{ config.acceptance_max_mg }} mg</div>
            <div>{{ config.config_source_label }}</div>
            <div v-if="config.control_profile_warnings?.length">含 {{ config.control_profile_warnings.length }} 项使用注意事项，请在启动前展开阅读。</div>
          </el-alert>
          <div v-else-if="!largeMode" class="config-placeholder">选择粉末后，将显示对应配置与验收范围。</div>
          <el-collapse v-if="config?.control_profile_warnings?.length" class="config-warnings">
            <el-collapse-item :title="'使用注意事项（' + config.control_profile_warnings.length + ' 项）'" name="warnings">
              <ul><li v-for="warning in config.control_profile_warnings" :key="warning">{{ warningZh(warning) }}</li></ul>
            </el-collapse-item>
          </el-collapse>

          <el-collapse class="advanced">
            <el-collapse-item title="高级设置与批量选项" name="advanced">
              <el-form-item label="起始参数">
                <el-switch v-model="manualEnabled" active-text="手动调整" inactive-text="自动匹配" />
                <div class="input-hint">手动设置仅调整起始参数，不改变粉末过程配置。</div>
              </el-form-item>
              <template v-if="manualEnabled">
                <el-form-item label="起始参数预设">
                  <el-select v-model="presetId" filterable aria-label="起始参数预设" @change="selectPreset">
                    <el-option v-for="p in presets" :key="p.preset_id" :value="p.preset_id" :label="p.preset_id" />
                  </el-select>
                </el-form-item>
                <div class="manual-grid">
                  <el-form-item label="频率 Hz"><el-input-number v-model="initial.frequency_hz" :min="10" :max="80" aria-label="起始频率" /></el-form-item>
                  <el-form-item label="占空比（万分值）"><el-input-number v-model="initial.duty_permyriad" :min="1000" :max="5000" :step="50" aria-label="起始占空比" /></el-form-item>
                  <el-form-item label="窗口位置"><el-input-number v-model="initial.window_position_units" :min="100" :max="750" aria-label="起始窗口位置" /></el-form-item>
                </div>
              </template>
              <el-form-item label="批量重复次数"><el-input-number v-model="repeats" :min="1" :max="20" aria-label="闭环批量重复次数" /></el-form-item>
              <template v-if="config">
                <div class="config-details">
                  <div>初始 {{ config.initial.frequency_hz }} Hz / {{ config.initial.duty_permyriad / 100 }}% / 窗口 {{ config.initial.window_position_units }}</div>
                  <div>粗 / 细 / 精速率：{{ config.profile.coarse_rate_mg_s }} / {{ config.profile.fine_rate_mg_s }} / {{ config.profile.precision_rate_mg_s }} mg/s</div>
                  <div>固定尾量 {{ config.controller.fixed_tail_mass_mg }} mg；占空比上限 {{ config.controller.max_duty_permyriad / 100 }}%</div>
                  <div>轻流量保持 {{ onOff(config.controller.flow_hold_enabled) }}；堵料恢复 {{ onOff(config.controller.stall_recovery_enabled) }}；尾段脉冲 {{ onOff(config.controller.tail_pulse_enabled) }}</div>
                </div>
                <el-collapse><el-collapse-item title="查看完整控制配置（中文）" name="config"><pre>{{ localizedConfigText(config) }}</pre></el-collapse-item></el-collapse>
              </template>
            </el-collapse-item>
          </el-collapse>
        </el-form>
        <div class="row actions">
          <el-button type="primary" size="large" :disabled="!ready" :loading="submitting" @click="start">启动 {{ activeTargetLabel }} 加粉</el-button>
          <el-button type="danger" plain size="large" :disabled="!isDispensing || !store.isRunning" @click="stop">停止加粉</el-button>
        </div>
        <div class="row secondary-actions">
          <el-button :disabled="locked" @click="tare">天平标零</el-button>
          <el-button type="warning" plain :disabled="locked" @click="closeWindowPosition">关闭窗口</el-button>
          <el-button :disabled="!ready" @click="enqueue">添加到批量队列</el-button>
        </div>
        <p class="operation-hint">启动前请确认粉末正确、容器放稳，并按需标零。</p>
        <p v-if="isDispensing && store.isRunning" class="operation-hint">当前步骤：{{ phaseLabel }}</p>
      </section>

      <section class="monitor-section" aria-label="闭环加粉实时监测">
        <div class="balance-display" :class="{ unavailable: !reading.available }" data-testid="live-balance">
          <div class="balance-heading">
            <span>天平实时读数</span>
            <el-tag :type="reading.tagType" effect="plain" size="small">{{ reading.status }}</el-tag>
          </div>
          <div class="balance-number"><strong data-testid="balance-value">{{ reading.text }}</strong><span>{{ reading.unit }}</span></div>
          <p v-if="reading.note" class="balance-note">{{ reading.note }}</p>
        </div>
        <div class="progress-section">
          <div class="progress-heading">
            <span>{{ isDispensing ? '本次加粉进度' : '等待启动加粉' }}</span>
            <span>目标 <strong>{{ displayTarget }}</strong> mg</span>
          </div>
          <el-progress :percentage="isDispensing ? progress : 0" :stroke-width="10" />
        </div>
        <div class="metrics">
          <MetricCard label="控制采样质量" :value="fmt(sample.mass_mg)" unit="mg" />
          <MetricCard label="控制速率" :value="fmt(sample.control_rate_mg_s ?? sample.rate_mg_s)" unit="mg/s" />
          <MetricCard label="当前占空比" :value="sample.duty_permyriad == null ? '--' : sample.duty_permyriad / 100" unit="%" />
          <MetricCard label="窗口位置" :value="sample.window_position_units ?? '--'" />
        </div>
        <div class="final-mass"><span>最终稳定质量</span><strong>{{ fmt(result.final_mass_mg) }} <small>mg</small></strong></div>
        <p v-if="isDispensing && !store.isRunning" class="input-hint">任务数据为上次加粉结果；上方天平读数持续刷新。</p>
        <el-alert v-if="sample.stall_recovery_active" :title="'堵料恢复中 · 第 ' + sample.stall_recovery_attempt + ' 次'" type="warning" :closable="false" class="message" />
        <el-alert v-if="result.error" :title="result.error" type="error" :closable="false" class="message" />
        <el-collapse v-if="isDispensing" class="advanced">
          <el-collapse-item title="查看过程详情" name="process">
            <div class="config-details">
              <div>控制阶段：{{ sample.stage || test.phase || '--' }}</div>
              <div>预计尾量：{{ fmt(sample.estimated_tail_mg) }} mg</div>
              <div>预计停机质量：{{ fmt(sample.projected_stop_mass_mg) }} mg</div>
            </div>
          </el-collapse-item>
        </el-collapse>
      </section>
    </div>
    <el-alert v-if="message" :title="message" :type="messageType" :closable="false" class="message" />
  </PanelSection>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useDeviceStore } from '../stores/device.js'
import { useBatchQueue } from '../composables/useBatchQueue.js'
import { getDispensePowders, getDispenseConfig, getDispensePresets, startDispense, startLargeDispense, cancelDispense, tareBalance, closeWindow, errorMessage } from '../api/index.js'
import { dispensePayload, largeDispensePayload, dispenseQueueItem, isValidTarget, isValidLargeTarget, validateBatchQueue, LARGE_DEFAULT_DUTY_PERMYRIAD } from '../utils/dispense.js'
import { localizedConfigText, warningZh } from '../utils/configI18n.js'
import { balanceReading, taskStatusLabel } from '../utils/telemetry.js'
import PanelSection from './PanelSection.vue'
import MetricCard from './MetricCard.vue'

const store=useDeviceStore()
const { batchQueue, addToQueue }=useBatchQueue()
const powders=ref([]), presets=ref([]), powderId=ref(''), target=ref(500), largeTargetG=ref(1), largeWindow=ref(700), largeMode=ref(false), repeats=ref(1)
const largeDutyPercent=ref(LARGE_DEFAULT_DUTY_PERMYRIAD/100)
const config=ref(null), configError=ref(''), loadingConfig=ref(false), submitting=ref(false)
const manualEnabled=ref(false), presetId=ref(''), initial=reactive({frequency_hz:80,duty_permyriad:2000,window_position_units:200})
const message=ref(''), messageType=ref('info')
const test=computed(()=>store.testState || {})
const isDispensing=computed(()=> /^(dispense-|disp-batch-|large-dispense-)/.test(test.value.run_id || ''))
const sample=computed(()=>isDispensing.value ? test.value.latest_sample || {} : {})
const result=computed(()=>isDispensing.value ? test.value.result || {} : {})
const locked=computed(()=>store.isRunning || submitting.value)
const activeTargetMg=computed(()=>largeMode.value ? Math.round(largeTargetG.value * 1000) : target.value)
const activeTargetLabel=computed(()=>largeMode.value ? `${largeTargetG.value} g` : `${target.value} mg`)
const largeDutyPermyriad=computed(()=>{const pct=Number(largeDutyPercent.value);return Number.isFinite(pct)?Math.round(pct*100):0})
// Pre-feed hands control back to the saved closed loop once this reserve is
// left: a fixed 500 mg below 5 g, then 10% of the target from 5 g upwards.
const largeReserveMg=computed(()=>activeTargetMg.value<5000?500:Math.round(activeTargetMg.value*10)/100)
const largeReserveHint=computed(()=>`目标小于 5 g 时剩余 500 mg、5 g 及以上时剩余目标的 10%（当前目标将在剩余 ${largeReserveMg.value} mg 时切回精加闭环）`)
const ready=computed(()=>!locked.value && !!powderId.value && (largeMode.value ? isValidLargeTarget(activeTargetMg.value) : !loadingConfig.value && config.value?.powder_id===powderId.value && config.value?.target_mg===target.value && isValidTarget(target.value)))
const progress=computed(()=>Math.min(100,Math.max(0,Math.round(100*(result.value.final_mass_mg ?? sample.value.mass_mg ?? 0)/(result.value.target_mass_mg || test.value.submitted?.target_mg || activeTargetMg.value || 1)))))
const reading=computed(()=>balanceReading(store.balance, store.snapshotError))
const statusLabel=computed(()=>isDispensing.value ? taskStatusLabel(test.value.status) : store.isRunning ? '设备忙碌' : '待命')
const phaseLabel=computed(()=>({
  window_move: '正在定位到加粉窗口',
  tare: '窗口已到位，正在天平归零',
  vibration_start: '正在启动振动加粉',
  closing_window_after_dispense: '加粉结束，正在关闭窗口',
}[test.value.phase] || test.value.phase || '正在准备'))
const displayTarget=computed(()=>isDispensing.value ? (result.value.target_mass_mg ?? test.value.submitted?.target_mg ?? activeTargetMg.value) : activeTargetMg.value)
let previewSequence=0
const onOff=value=>value?'已启用':'未启用'
const fmt=value=>value==null?'--':Number(value).toFixed(1)
function fail(error){message.value=errorMessage(error);messageType.value='error';ElMessage.error(message.value)}
async function loadPowders(){
  try {
    const [list,seeds]=await Promise.all([getDispensePowders(),getDispensePresets()])
    powders.value=list;presets.value=seeds
    if(!list.some(p=>p.powder_id===powderId.value && p.selectable!==false)) powderId.value=''
    else await preview()
  } catch(error){fail(error)}
}
async function preview(){
  const sequence=++previewSequence
  config.value=null;configError.value='';loadingConfig.value=false
  if(!powderId.value || largeMode.value) return
  if(!isValidTarget(target.value)){configError.value='请输入100–1000 mg之间的整数质量';return}
  loadingConfig.value=true
  try {
    const data=await getDispenseConfig(powderId.value,target.value)
    if(sequence!==previewSequence)return
    config.value=data;presetId.value=data.preset_id;Object.assign(initial,data.initial)
  } catch(error){if(sequence===previewSequence)configError.value=errorMessage(error)}
  finally{if(sequence===previewSequence)loadingConfig.value=false}
}
watch([powderId,target,largeMode],preview,{flush:'sync'})
function selectPreset(id){const selected=presets.value.find(p=>p.preset_id===id);if(selected)for(const key of Object.keys(initial))initial[key]=selected[key]}
function manual(){return manualEnabled.value?{preset_id:presetId.value,initial:{...initial}}:null}
async function start(){
  submitting.value=true
  try {
    const dutyPermyriad=largeDutyPermyriad.value
    if(dutyPermyriad<1000||dutyPermyriad>5000) throw new Error('大重量预加粉占空比需为 10%–50%')
    const payload=largeMode.value ? largeDispensePayload(powderId.value,activeTargetMg.value,largeWindow.value,dutyPermyriad) : dispensePayload(powderId.value,target.value,config.value,manual())
    const powderName=largeMode.value ? powders.value.find(p=>p.powder_id===powderId.value)?.powder_name : config.value.powder_name
    await ElMessageBox.confirm('确认粉末为“'+powderName+'”、容器已放好，并启动 '+activeTargetLabel.value+' 加粉？','启动确认',{type:'warning'})
    const response=largeMode.value ? await startLargeDispense(payload) : await startDispense(payload)
    message.value='任务已启动：'+response.run_id;messageType.value='success'
    await store.fetchSnapshot()
  } catch(error){if(error!=='cancel' && error!=='close')fail(error)}
  finally{submitting.value=false}
}
function enqueue(){
  try{
    const item=dispenseQueueItem(powderId.value,target.value,config.value,repeats.value,manual())
    validateBatchQueue([...batchQueue.value,item]);addToQueue(item)
    ElMessage.success('已添加 '+config.value.powder_name+' 到批量队列')
  }catch(error){fail(error)}
}
async function stop(){try{await cancelDispense();message.value='已请求停止';messageType.value='info'}catch(error){fail(error)}}
async function tare(){try{await tareBalance();ElMessage.success('天平已标零')}catch(error){fail(error)}}
async function closeWindowPosition(){
  try{
    await ElMessageBox.confirm('确认将窗口移动到最小安全位置并关闭窗口？','关闭窗口确认',{type:'warning'})
    const response=await closeWindow()
    message.value='窗口已关闭（位置 '+response.after_position_units+'）';messageType.value='success'
    await store.fetchSnapshot()
  }catch(error){if(error!=='cancel' && error!=='close')fail(error)}
}
onMounted(loadPowders)
onUnmounted(()=>{previewSequence++})
</script>

<style scoped>
.dispense-layout { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); gap: 32px; }
.setup-section, .monitor-section { min-width: 0; }
.section-heading { margin: 0 0 6px; font-size: 15px; color: #25364d; }
.section-note, .input-hint, .operation-hint { font-size: 12px; line-height: 1.7; color: #738196; }
.section-note { margin-bottom: 20px; }
.row { display: flex; flex-wrap: wrap; gap: 8px; width: 100%; align-items: center; }
.row :deep(.el-button + .el-button), .target-presets :deep(.el-button + .el-button) { margin-left: 0; }
.powder-row { flex-wrap: nowrap; }
.powder-row .el-select { flex: 1; min-width: 0; }
.target-controls { width: 100%; }
.target-presets { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-bottom: 12px; }
.target-presets .el-button { padding: 8px; }
.large-mode { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 8px; }
.large-mode :deep(.el-button + .el-button) { margin-left: 0; }
.large-mode :deep(.el-input-number) { width: 112px; }
.large-duty-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 8px; }
.large-duty-row :deep(.el-button + .el-button) { margin-left: 0; }
.large-duty-row :deep(.el-input-number) { width: 112px; }
.config-placeholder { background: #f7f9fc; border: 1px dashed #dce3ec; padding: 14px; border-radius: 8px; color: #7a8799; font-size: 12px; line-height: 1.7; }
.config-warnings { margin-top: 8px; border-top: 0; }
.config-warnings :deep(.el-collapse-item__header) { color: #99631d; font-size: 12px; }
.config-warnings ul { padding-left: 18px; color: #8d6229; line-height: 1.8; overflow-wrap: anywhere; }
.advanced { margin: 18px 0 0; border-top: 0; }
.advanced :deep(.el-collapse-item__header) { font-size: 12px; color: #63758c; }
.manual-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.manual-grid :deep(.el-input-number) { width: 100%; }
.config-details { font-size: 12px; line-height: 1.9; color: #6b7788; margin-bottom: 12px; overflow-wrap: anywhere; }
pre { max-height: 280px; overflow: auto; font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
.actions { margin-top: 20px; }
.secondary-actions { margin-top: 10px; }
.operation-hint { margin-top: 12px; }
.balance-display { border: 1px solid #cde1fa; border-radius: 12px; padding: 22px 24px; background: linear-gradient(120deg, #edf5ff, #f8fbff); }
.balance-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 14px; color: #345778; font-weight: 600; }
.balance-number { display: flex; align-items: baseline; gap: 12px; margin: 20px 0 10px; color: #1c66ba; font-variant-numeric: tabular-nums; }
.balance-number strong { font-size: clamp(36px, 4vw, 54px); line-height: 1.1; letter-spacing: -1px; overflow-wrap: anywhere; min-width: 0; }
.balance-number span { font-size: 18px; }
.balance-note { font-size: 12px; color: #63809d; line-height: 1.7; overflow-wrap: anywhere; }
.unavailable { background: #f5f7fa; border-color: #e0e6ed; }
.unavailable .balance-number { color: #97a4b4; }
.progress-section { margin: 22px 0 18px; }
.progress-heading { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; color: #708095; margin-bottom: 12px; }
.progress-heading strong { color: #334b68; }
.metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.metrics :deep(.metric-card) { padding: 12px 16px; }
.metrics :deep(.metric-value) { font-size: 23px; }
.final-mass { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 16px 0 10px; font-size: 13px; color: #667b94; }
.final-mass strong { font-size: 22px; color: #263d58; font-variant-numeric: tabular-nums; }
.final-mass small { font-size: 12px; font-weight: 400; }
.message { margin-top: 16px; }
@media (max-width: 1100px) { .dispense-layout { gap: 20px; } }
@media (max-width: 900px) { .dispense-layout { grid-template-columns: 1fr; } .monitor-section { grid-row: 1; } }
@media (max-width: 480px) { .balance-display { padding: 18px; } .manual-grid { grid-template-columns: 1fr; } .target-presets { gap: 4px; } }
</style>
