<template>
  <PanelSection title="定速测试">
    <template #header-actions>
      <el-tag :type="isConstRate && isAnyRunning ? 'warning' : 'info'" effect="plain">{{ statusLabel }}</el-tag>
    </template>
    <p class="section-note">设置固定运行参数，测试出粉流速与稳定性。</p>
    <div class="rate-layout">
      <section aria-label="定速测试设置">
        <el-form label-position="top" :disabled="isAnyRunning || loading" class="params-grid">
          <el-form-item label="目标流速 mg/s">
            <el-input-number v-model="params.targetRate" :min="3" :max="50" :step="0.5" :precision="1" controls-position="right" aria-label="定速目标流速" />
          </el-form-item>
          <el-form-item label="频率 Hz">
            <el-input-number v-model="params.frequency" :min="10" :max="80" :step="1" controls-position="right" aria-label="定速频率" />
          </el-form-item>
          <el-form-item label="占空比 %">
            <el-input-number v-model="params.dutyPercent" :min="10" :max="50" :step="0.5" :precision="1" controls-position="right" aria-label="定速占空比" />
          </el-form-item>
          <el-form-item label="窗口位置">
            <el-input-number v-model="params.windowPosition" :min="100" :max="750" :step="1" controls-position="right" aria-label="定速窗口位置" />
          </el-form-item>
          <el-form-item label="持续时间 s">
            <el-input-number v-model="params.duration" :min="5" :max="300" :step="1" controls-position="right" aria-label="定速持续时间" />
          </el-form-item>
          <el-form-item label="重复次数">
            <el-input-number v-model="params.repeat" :min="1" :max="10" :step="1" controls-position="right" aria-label="定速重复次数" />
          </el-form-item>
        </el-form>
        <div class="action-row">
          <el-button type="primary" :disabled="isAnyRunning" :loading="loading" @click="handleStart">启动定速测试</el-button>
          <el-button type="danger" plain :disabled="!isConstRate || !isAnyRunning" @click="handleCancel">停止测试</el-button>
          <el-button type="warning" plain :disabled="isAnyRunning || loading" @click="handleMoveWindowToMinimum">窗口设至最小值</el-button>
          <el-button :disabled="isAnyRunning || loading" @click="handleAddToBatch">添加到批量队列</el-button>
        </div>
      </section>
      <section aria-label="定速测试监测" class="metrics-grid">
        <MetricCard label="实时流速" :value="fmt(sample.rate_mg_s)" unit="mg/s" />
        <MetricCard label="当前质量" :value="fmt(sample.mass_mg)" unit="mg" />
        <MetricCard label="已过时间" :value="fmt(sample.elapsed_s)" unit="s" />
        <MetricCard label="段进度 / 峰值" :value="progressPeakDisplay" />
        <MetricCard label="段 CV / 均值" :value="segmentStatsDisplay" />
        <MetricCard label="控制状态" :value="verdictDisplay" />
      </section>
    </div>
    <el-alert v-if="stateWarning" :title="stateWarning" type="warning" :closable="false" class="message" />
    <el-alert v-if="result.error" :title="result.error" type="error" :closable="false" class="message" />
    <div v-if="result.summary" class="summary-line">
      <span>总体平均流速：{{ fmt(result.summary.overall_mean_rate_mg_s) }} mg/s</span>
      <span>总体 CV：{{ fmt(result.summary.overall_cv_pct) }}%</span>
      <el-tag :type="result.summary.overall_passed ? 'success' : 'warning'">{{ result.summary.overall_passed ? '测试通过' : '未达标' }}</el-tag>
    </div>
    <el-collapse v-if="result.segments?.length" class="segments-section">
      <el-collapse-item title="查看分段测试结果" name="segments">
        <el-table :data="result.segments" size="small" border stripe>
          <el-table-column label="段" width="55" align="center"><template #default="{ row }">{{ row.segment_index + 1 }}</template></el-table-column>
          <el-table-column label="平均流速" min-width="95" align="center"><template #default="{ row }">{{ fmt(row.mean_rate_mg_s) }}</template></el-table-column>
          <el-table-column label="峰值" min-width="80" align="center"><template #default="{ row }">{{ fmt(row.peak_rate_mg_s) }}</template></el-table-column>
          <el-table-column label="标准差" min-width="85" align="center"><template #default="{ row }">{{ fmt(row.std_mg_s) }}</template></el-table-column>
          <el-table-column label="CV%" min-width="80" align="center"><template #default="{ row }">{{ fmt(row.cv_pct) }}</template></el-table-column>
          <el-table-column label="增量 mg" min-width="85" align="center"><template #default="{ row }">{{ fmt(row.mass_gain_mg) }}</template></el-table-column>
          <el-table-column label="流速判定" min-width="90" align="center">
            <template #default="{ row }"><el-tag v-if="row.rate_passed != null" :type="row.rate_passed ? 'success' : 'danger'" size="small">{{ row.rate_passed ? '通过' : '未达标' }}</el-tag><span v-else>--</span></template>
          </el-table-column>
          <el-table-column label="稳定性判定" min-width="100" align="center">
            <template #default="{ row }"><el-tag v-if="row.stability_passed != null" :type="row.stability_passed ? 'success' : 'danger'" size="small">{{ row.stability_passed ? '通过' : '未达标' }}</el-tag><span v-else>--</span></template>
          </el-table-column>
        </el-table>
      </el-collapse-item>
    </el-collapse>
  </PanelSection>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useDeviceStore } from '../stores/device.js'
import { startConstantRate, cancelConstantRate, moveWindowToMinimum, errorMessage } from '../api/index.js'
import { useBatchQueue } from '../composables/useBatchQueue.js'
import { taskStatusLabel } from '../utils/telemetry.js'
import PanelSection from './PanelSection.vue'
import MetricCard from './MetricCard.vue'

const store = useDeviceStore()
const { addToQueue } = useBatchQueue()

const testState = computed(() => store.testState)
const isAnyRunning = computed(() => store.isRunning)

const isConstRate = computed(() => {
  const rid = testState.value.run_id
  return rid && typeof rid === 'string' && (rid.startsWith('const-rate-') || rid.startsWith('const-batch-'))
})

const sample = computed(() => isConstRate.value ? testState.value.latest_sample || {} : {})
const result = computed(() => isConstRate.value ? testState.value.result || {} : {})
const statusLabel = computed(() => isConstRate.value ? taskStatusLabel(testState.value.status) : isAnyRunning.value ? '设备忙碌' : '待命')

const stateWarning = computed(() => {
  if (!isConstRate.value) return ''
  const st = sample.value.state_text || testState.value.state_text || ''
  return st
})

const params = reactive({
  targetRate: 10.0,
  frequency: 40,
  dutyPercent: 20.0,
  windowPosition: 300,
  duration: 15,
  repeat: 3,
})

const progressPeakDisplay = computed(() => {
  const seg = sample.value.segment_index
  const cnt = sample.value.segment_count
  const peak = sample.value.segment_peak_rate_mg_s
  const segStr = seg != null && cnt != null ? (seg + 1) + '/' + cnt : '--'
  const peakStr = peak != null ? fmt(peak) : '--'
  return segStr + ' / ' + peakStr
})

const segmentStatsDisplay = computed(() => {
  const cv = sample.value.segment_cv_pct
  const mean = sample.value.segment_mean_rate_mg_s
  const cvStr = cv != null ? fmt(cv) + '%' : '--'
  const meanStr = mean != null ? fmt(mean) : '--'
  return cvStr + ' / ' + meanStr
})

const verdictDisplay = computed(() => {
  // Real-time verdict fields are only available in the per-segment summary after completion
  // During running, show rate-lock status from the feedback controller
  const locked = sample.value.locked
  const clogged = sample.value.clogged
  if (locked === true) return '已锁定'
  if (clogged === true) return '堵塞'
  if (locked === false) return '调节中'
  return '--'
})

const loading = ref(false)

async function handleStart() {
  loading.value = true
  try {
    await startConstantRate({
      target_rate_mg_s: params.targetRate,
      frequency_hz: params.frequency,
      duty_permyriad: Math.round(params.dutyPercent * 100),
      window_position_units: params.windowPosition,
      duration_s: params.duration,
      repeat_count: params.repeat,
    })
    ElMessage.success('定速测试已启动')
  } catch (_e) {
    ElMessage.error('启动失败')
  } finally {
    loading.value = false
  }
}

async function handleCancel() {
  try {
    await cancelConstantRate()
    ElMessage.info('定速测试已停止')
  } catch (_e) {
    ElMessage.error('停止失败')
  }
}

async function handleMoveWindowToMinimum() {
  try {
    await ElMessageBox.confirm(
      '确认将窗口移动到最小安全位置 100？请确认振动已停止且无人接触机构。',
      '窗口最小化确认',
      { type: 'warning' },
    )
    const response = await moveWindowToMinimum()
    ElMessage.success(`窗口已移动至 ${response.after_position_units}`)
    await store.fetchSnapshot()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}

function handleAddToBatch() {
  addToQueue({
    type: 'constant-rate',
    typeLabel: '定速',
    params: {
      target_rate_mg_s: params.targetRate,
      frequency_hz: params.frequency,
      duty_permyriad: Math.round(params.dutyPercent * 100),
      window_position_units: params.windowPosition,
      duration_s: params.duration,
      repeat_count: params.repeat,
    },
  })
  ElMessage.success('已添加到批量队列')
}

function fmt(v) {
  if (v === undefined || v === null || v === '') return '--'
  if (typeof v === 'number') {
    if (Number.isInteger(v)) return String(v)
    return v.toFixed(2)
  }
  return String(v)
}
</script>

<style scoped>
.section-note { color: #738196; font-size: 12px; margin: 0 0 20px; line-height: 1.7; }
.rate-layout { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); gap: 32px; }
.rate-layout > section { min-width: 0; }
.params-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 12px; }
.params-grid :deep(.el-input-number) { width: 100%; }
.params-grid :deep(.el-form-item__label) { font-size: 12px; color: #63758c; }
.action-row { display: flex; gap: 8px; margin-top: 4px; flex-wrap: wrap; }
.action-row :deep(.el-button + .el-button) { margin-left: 0; }
.metrics-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.metrics-grid :deep(.metric-card) { padding: 12px; }
.metrics-grid :deep(.metric-value) { font-size: 21px; overflow-wrap: anywhere; }
.metrics-grid :deep(.metric-label) { font-size: 12px; }
.segments-section, .message { margin-top: 20px; }
.summary-line { margin-top: 18px; padding: 12px 16px; background: #f5f8fc; border-radius: 8px; font-size: 13px; color: #526780; display: flex; align-items: center; flex-wrap: wrap; gap: 16px; }
@media (max-width: 1100px) { .rate-layout { gap: 20px; } .metrics-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 900px) { .rate-layout { grid-template-columns: 1fr; } .metrics-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 480px) { .params-grid, .metrics-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
