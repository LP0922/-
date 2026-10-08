<template>
  <PanelSection title="窗口 PID 对照测试">
    <template #header-actions>
      <el-tag :type="isPid ? 'warning' : 'info'" size="small" effect="plain">
        {{ isPid ? 'PID 调节中' : '待命' }}
      </el-tag>
    </template>

    <p class="desc-text">
      固定 80 Hz / 20%；PID 只调整 LA10 窗口，目标 500 mg
    </p>

    <div class="action-row">
      <el-button
        type="primary"
        :disabled="isAnyRunning"
        :loading="loading"
        @click="handleStart"
      >
        启动窗口 PID 测试
      </el-button>
      <el-button
        type="danger"
        :disabled="!isPid"
        @click="handleCancel"
      >
        停止 PID 测试
      </el-button>
    </div>

    <div class="message-line">
      <span class="window-hint">粗加窗口 650，慢加窗口 200，精加窗口 100</span>
    </div>

    <div class="metrics-grid">
      <MetricCard label="当前质量" :value="fmt(sample.mass_mg)" unit="mg" />
      <MetricCard label="实时/目标速率" :value="rateDisplay" unit="mg/s" />
      <MetricCard label="当前/计划窗口" :value="windowDisplay" />
      <MetricCard label="PID 修正/阶段" :value="pidDisplay" />
    </div>
  </PanelSection>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useDeviceStore } from '../stores/device.js'
import { startWindowPid, cancelWindowPid } from '../api/index.js'
import PanelSection from './PanelSection.vue'
import MetricCard from './MetricCard.vue'

const store = useDeviceStore()

const testState = computed(() => store.testState)
const isAnyRunning = computed(() => store.isRunning)

const isPid = computed(() => {
  const rid = testState.value.run_id
  return rid && typeof rid === 'string' && rid.startsWith('window-pid-500mg-')
})

const sample = computed(() => testState.value.latest_sample || {})

const rateDisplay = computed(() => {
  const r = sample.value.rate_mg_s
  const t = sample.value.target_rate_mg_s
  if (r == null && t == null) return '--'
  const real = r != null ? (typeof r === 'number' ? r.toFixed(2) : r) : '--'
  const target = t != null ? (typeof t === 'number' ? t.toFixed(2) : t) : '--'
  return real + ' / ' + target
})

const windowDisplay = computed(() => {
  const cur = sample.value.current_window
  const plan = sample.value.planned_window
  if (cur == null && plan == null) return '--'
  const c = cur != null ? cur : '--'
  const p = plan != null ? plan : '--'
  return c + ' / ' + p
})

const pidDisplay = computed(() => {
  const corr = sample.value.pid_correction
  const phase = testState.value.phase || sample.value.phase
  const c = corr != null ? (typeof corr === 'number' ? corr.toFixed(2) : corr) : '--'
  const ph = phase || '--'
  return c + ' / ' + ph
})

const loading = ref(false)

async function handleStart() {
  loading.value = true
  try {
    await startWindowPid()
    ElMessage.success('窗口 PID 测试已启动')
  } catch (_e) {
    ElMessage.error('启动失败')
  } finally {
    loading.value = false
  }
}

async function handleCancel() {
  try {
    await cancelWindowPid()
    ElMessage.info('PID 测试已停止')
  } catch (_e) {
    ElMessage.error('停止失败')
  }
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
.desc-text {
  margin: 0 0 14px;
  font-size: 13px;
  color: #909399;
  line-height: 1.6;
}

.action-row {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.message-line {
  margin-bottom: 16px;
}

.window-hint {
  font-size: 13px;
  color: #606266;
  background: #f5f7fa;
  padding: 4px 10px;
  border-radius: 4px;
}

.metrics-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 4px;
}

@media (max-width: 900px) {
  .metrics-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
