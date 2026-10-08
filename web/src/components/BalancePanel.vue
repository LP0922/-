<template>
  <PanelSection title="AT8811C 称量模块">
    <template #header-actions>
      <span :class="['status-dot', online ? 'online' : 'offline']"></span>
      <span :class="online ? 'status-text-online' : 'status-text-offline'">
        {{ online ? '在线' : '离线' }}
      </span>
    </template>

    <div class="metrics-grid">
      <MetricCard label="实时重量" :value="weightDisplay" unit="mg" />
      <MetricCard label="状态字" :value="statusWordDisplay" />
      <MetricCard label="稳定标志" :value="stableDisplay" />
      <MetricCard label="零区标志" :value="zeroBandDisplay" />
    </div>

    <div class="chips-row">
      <el-tag :type="bal.stable ? 'success' : 'info'" size="small">硬件稳定位</el-tag>
      <el-tag :type="bal.in_zero_band ? 'warning' : 'info'" size="small">零区位</el-tag>
    </div>

    <el-alert
      v-if="!online && bal.error"
      :title="bal.error"
      type="error"
      show-icon
      :closable="false"
      class="error-alert"
    />

    <div v-if="online && hasConfig" class="config-section">
      <h4 class="section-title">配置寄存器</h4>
      <el-table :data="configTableData" size="small" border stripe>
        <el-table-column prop="label" label="参数名称" width="160" />
        <el-table-column prop="value" label="参数值" />
      </el-table>
    </div>
  </PanelSection>
</template>

<script setup>
import { computed } from 'vue'
import { useDeviceStore } from '../stores/device.js'
import PanelSection from './PanelSection.vue'
import MetricCard from './MetricCard.vue'

const store = useDeviceStore()
const bal = computed(() => store.balance)

const online = computed(() => bal.value.online)

const weightDisplay = computed(() => {
  const v = bal.value.raw_weight_mg
  return v != null ? String(v) : '--'
})

const statusWordDisplay = computed(() => {
  const v = bal.value.status_word
  if (v == null) return '--'
  return '0x' + v.toString(16).toUpperCase().padStart(4, '0')
})

const stableDisplay = computed(() => {
  if (bal.value.stable == null) return '--'
  return bal.value.stable ? '稳定' : '不稳定'
})

const zeroBandDisplay = computed(() => {
  if (bal.value.in_zero_band == null) return '--'
  return bal.value.in_zero_band ? '在零区' : '非零区'
})

const configFieldMap = [
  { key: 'division_mg', label: '分度值' },
  { key: 'full_scale_mg', label: '满量程' },
  { key: 'zero_range', label: '置零范围' },
  { key: 'startup_zero_range', label: '启动置零范围' },
  { key: 'zero_tracking_range', label: '零点跟踪范围' },
  { key: 'zero_tracking_time', label: '零点跟踪时间' },
  { key: 'ad_conversion', label: 'AD转换频率' },
  { key: 'filter_level', label: '滤波等级' },
  { key: 'configured_address', label: '模块地址' },
  { key: 'baudrate', label: '波特率' },
  { key: 'protocol_format', label: '协议格式' },
  { key: 'stable_range', label: '硬件判稳范围' },
  { key: 'tare_range_percent', label: '去皮范围' },
]

const hasConfig = computed(() => {
  return bal.value.configuration && Object.keys(bal.value.configuration).length > 0
})

const configTableData = computed(() => {
  if (!bal.value.configuration) return []
  const cfg = bal.value.configuration
  return configFieldMap
    .filter((f) => cfg[f.key] != null)
    .map((f) => {
      let displayValue = cfg[f.key]
      if (f.key === 'ad_conversion' && typeof displayValue === 'object') {
        displayValue = displayValue.label + '（代码 ' + displayValue.code + '）'
      } else if (f.key === 'protocol_format' && typeof displayValue === 'object') {
        displayValue = displayValue.label || JSON.stringify(displayValue)
      }
      return { label: f.label, value: displayValue }
    })
})
</script>

<style scoped>
.status-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 4px;
}

.status-dot.online {
  background-color: #67c23a;
  box-shadow: 0 0 4px #67c23a;
}

.status-dot.offline {
  background-color: #f56c6c;
  box-shadow: 0 0 4px #f56c6c;
}

.status-text-online {
  font-size: 13px;
  color: #67c23a;
  font-weight: 500;
}

.status-text-offline {
  font-size: 13px;
  color: #f56c6c;
  font-weight: 500;
}

.metrics-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
}

.chips-row {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  justify-content: center;
}

.error-alert {
  margin-top: 12px;
}

.config-section {
  margin-top: 16px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 8px 0;
  padding-bottom: 6px;
  border-bottom: 1px solid #ebeef5;
}
</style>
