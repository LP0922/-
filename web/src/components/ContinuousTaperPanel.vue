<template>
  <PanelSection title="500 mg 连续收敛独立测试">
    <template #header-actions>
      <el-tag :type="isContinuous ? 'warning' : 'info'" size="small" effect="plain">
        {{ isContinuous ? '测试中' : '待命' }}
      </el-tag>
    </template>

    <p class="desc-text">
      0-420 mg：位置 200 / 80 Hz / 20%；420 mg 后一次切换：位置 100 / 65 Hz / 16%
    </p>

    <div class="action-row">
      <el-button
        type="primary"
        :disabled="isAnyRunning"
        :loading="loading"
        @click="handleStart"
      >
        启动连续收敛测试
      </el-button>
      <el-button
        type="danger"
        :disabled="!isContinuous"
        @click="handleCancel"
      >
        停止连续收敛测试
      </el-button>
    </div>

    <div v-if="messageText" class="message-line">
      <el-tag size="small" effect="plain">{{ messageText }}</el-tag>
    </div>

    <div class="metrics-grid">
      <MetricCard label="控制采样质量" :value="fmt(sample.mass_mg)" unit="mg" />
      <MetricCard label="天平实时质量" :value="fmt(balanceWeight)" unit="mg" />
      <MetricCard label="最终稳定质量" :value="fmt(sample.final_mass_mg)" unit="mg" />
      <MetricCard label="实时速率" :value="fmt(sample.rate_mg_s)" unit="mg/s" />
      <MetricCard label="预测停机质量" :value="fmt(sample.predicted_stop_mass_mg)" unit="mg" />
      <MetricCard label="阶段/命令" :value="phaseDisplay" />
      <MetricCard label="频率/占空比" :value="freqDutyDisplay" />
      <MetricCard label="窗口位置" :value="fmt(sample.window_position_units)" />
    </div>
  </PanelSection>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useDeviceStore } from '../stores/device.js'
import { startContinuousTaper, cancelContinuousTaper } from '../api/index.js'
import PanelSection from './PanelSection.vue'
import MetricCard from './MetricCard.vue'

const store = useDeviceStore()

const testState = computed(() => store.testState)
const isAnyRunning = computed(() => store.isRunning)

const isContinuous = computed(() => {
  const rid = testState.value.run_id
  return rid && typeof rid === 'string' && rid.startsWith('continuous-taper-500mg-')
})

const sample = computed(() => testState.value.latest_sample || {})

const balanceWeight = computed(() => {
  const v = store.balance.raw_weight_mg
  return v != null ? v : null
})

const phaseDisplay = computed(() => {
  if (!isContinuous.value) return '--'
  return testState.value.phase || sample.value.phase || '运行中'
})

const freqDutyDisplay = computed(() => {
  const freq = sample.value.frequency_hz
  const duty = sample.value.duty_cycle_percent
  if (freq == null && duty == null) return '--'
  const f = freq != null ? freq + ' Hz' : '--'
  const d = duty != null ? duty + '%' : '--'
  return f + ' / ' + d
})

const messageText = computed(() => {
  if (!isContinuous.value) return ''
  const phase = testState.value.phase || sample.value.phase
  if (phase) return '当前阶段: ' + phase
  return '运行中'
})

const loading = ref(false)

async function handleStart() {
  loading.value = true
  try {
    await startContinuousTaper()
    ElMessage.success('连续收敛测试已启动')
  } catch (_e) {
    ElMessage.error('启动失败')
  } finally {
    loading.value = false
  }
}

async function handleCancel() {
  try {
    await cancelContinuousTaper()
    ElMessage.info('连续收敛测试已停止')
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
