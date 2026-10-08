<template>
  <PanelSection title="测试与控制计划">
    <template #header-actions>
      <div class="header-right">
        <el-tag v-if="isSweepRunning" type="warning" size="small" effect="plain">
          扫描中
        </el-tag>
        <el-tag v-else type="info" size="small" effect="plain">
          待命
        </el-tag>
      </div>
    </template>

    <div class="sweep-header">
      <span class="section-subtitle">窗口位置扫描</span>
    </div>

    <p class="sweep-desc">
      窗口位置扫描 100 至 750, 步长 50；80 Hz；20%；每点 10 s
    </p>

    <div v-if="isSweepRunning" class="progress-area">
      <div class="progress-info">
        <span>当前段: {{ currentSegment }} / {{ totalSegments }}</span>
        <span>位置: {{ currentPosition }} 单位</span>
      </div>
      <el-progress
        :percentage="progressPercent"
        :stroke-width="12"
        :text-inside="true"
      />
    </div>
    <div v-else class="progress-area placeholder">
      <span class="muted">点击「启动扫描」开始窗口位置遍历</span>
    </div>

    <div class="action-row">
      <el-button
        type="primary"
        :disabled="isAnyRunning || sweeping"
        :loading="sweeping"
        @click="handleStartSweep"
      >
        启动扫描
      </el-button>
    </div>
  </PanelSection>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useDeviceStore } from '../stores/device.js'
import { startWindowSweep } from '../api/index.js'
import PanelSection from './PanelSection.vue'

const SWEEP_SCHEDULE = [
  100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750,
]

const store = useDeviceStore()
const testState = computed(() => store.testState)

const isAnyRunning = computed(() => store.isRunning)

const isSweepRunning = computed(() => {
  const rid = testState.value.run_id
  return rid && typeof rid === 'string' && rid.startsWith('window-sweep-')
})

const currentSegment = computed(() => {
  if (!isSweepRunning.value) return 0
  const seg = testState.value.current_segment
  return seg !== undefined && seg !== null ? seg + 1 : 0
})

const totalSegments = computed(() => SWEEP_SCHEDULE.length)

const currentPosition = computed(() => {
  if (!isSweepRunning.value) return '--'
  const pos = testState.value.current_position
  if (pos !== undefined && pos !== null) return pos
  if (testState.value.window_position_units !== undefined) return testState.value.window_position_units
  return '--'
})

const progressPercent = computed(() => {
  if (!isSweepRunning.value || totalSegments.value === 0) return 0
  return Math.round((currentSegment.value / totalSegments.value) * 100)
})

const sweeping = ref(false)

async function handleStartSweep() {
  sweeping.value = true
  try {
    await startWindowSweep({
      position_schedule: SWEEP_SCHEDULE,
      window_speed_mm_s: 1.0,
      window_timeout_s: 20,
      frequency_hz: 80,
      duty_permyriad: 2000,
      duration_s: 10,
    })
  } catch (_e) {
    // error surfaced by axios / caller
  } finally {
    sweeping.value = false
  }
}
</script>

<style scoped>
.sweep-header {
  margin-bottom: 8px;
}

.section-subtitle {
  font-size: 14px;
  font-weight: 600;
  color: #606266;
}

.sweep-desc {
  margin: 0 0 16px;
  font-size: 13px;
  color: #909399;
  line-height: 1.5;
}

.progress-area {
  margin-bottom: 16px;
}

.progress-area.placeholder {
  padding: 16px 0;
}

.progress-info {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
  font-size: 13px;
  color: #606266;
}

.muted {
  color: #c0c4cc;
  font-size: 13px;
}

.action-row {
  display: flex;
  gap: 8px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
