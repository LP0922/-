<template>
  <PanelSection title="震粉实时数据">
    <template #header-actions>
      <el-tag :type="isRunning ? 'warning' : 'info'" size="small" effect="plain">
        {{ phaseLabel }}
      </el-tag>
    </template>

    <div class="metrics-row">
      <MetricCard label="每秒震粉量" :value="fmt(sample.rate_mg_s)" unit="mg/s" />
      <MetricCard label="加速度" :value="fmt(sample.acceleration_mg_s2)" unit="mg/s²" />
      <MetricCard label="加加速度" :value="fmt(sample.jerk_mg_s3)" unit="mg/s³" />
      <MetricCard label="当前震粉质量" :value="fmt(sample.mass_mg)" unit="mg" />
    </div>

    <div class="chip-row">
      <el-alert :type="lockChipType" :closable="false" show-icon class="lock-alert">
        {{ lockChipText }}
      </el-alert>
    </div>
  </PanelSection>
</template>

<script setup>
import { computed } from 'vue'
import { useDeviceStore } from '../stores/device.js'
import MetricCard from './MetricCard.vue'
import PanelSection from './PanelSection.vue'

const store = useDeviceStore()

const testState = computed(() => store.testState)
const isRunning = computed(() => store.isRunning)
const sample = computed(() => testState.value.latest_sample || {})

const phaseLabel = computed(() => {
  if (!isRunning.value) return '空闲'
  if (testState.value.phase) return testState.value.phase
  return '运行中'
})

const lockChipType = computed(() => (isRunning.value ? 'warning' : 'success'))
const lockChipText = computed(() =>
  isRunning.value
    ? '任务运行中，寄存器写入已锁定'
    : '无任务，可写 LA10 地址 0-4、12-14',
)

function fmt(v, digits) {
  const d = digits === undefined ? 2 : digits
  if (v === undefined || v === null || v === '') return '--'
  if (typeof v === 'number') return v.toFixed(d)
  return String(v)
}
</script>

<style scoped>
.metrics-row {
  display: flex;
  justify-content: space-around;
  flex-wrap: wrap;
  gap: 8px;
}

.chip-row {
  margin-top: 16px;
}

.lock-alert {
  border-radius: 6px;
}
</style>
