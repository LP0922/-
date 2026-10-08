<template>
  <div class="metric-card">
    <div class="metric-label">{{ label }}</div>
    <div class="metric-value">
      <span class="value-text">{{ displayValue }}</span>
      <span v-if="unit" class="metric-unit">{{ unit }}</span>
    </div>
    <div v-if="subtitle" class="metric-subtitle">{{ subtitle }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '--' },
  unit: { type: String, default: '' },
  subtitle: { type: String, default: '' },
})

const displayValue = computed(() => {
  if (props.value === null || props.value === undefined) return '--'
  if (typeof props.value === 'number') return props.value.toFixed(1)
  return String(props.value)
})
</script>

<style scoped>
.metric-card {
  background: #fafbfc;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  transition: box-shadow 0.2s, border-color 0.2s;
}

.metric-card:hover {
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  border-color: #d0d7e3;
}

.metric-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
  font-weight: 500;
}

.metric-value {
  display: flex;
  align-items: baseline;
  gap: 2px;
}

.value-text {
  font-size: 28px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
  font-family: 'DIN', 'Helvetica Neue', Arial, sans-serif;
}

.metric-unit {
  font-size: 14px;
  font-weight: 400;
  color: #909399;
}

.metric-subtitle {
  font-size: 12px;
  color: #c0c4cc;
  margin-top: 6px;
}
</style>
