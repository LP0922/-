<template>
  <PanelSection title="LA10 / 振动模块">
    <template #header-actions>
      <span :class="['status-dot', online ? 'online' : 'offline']"></span>
      <span :class="online ? 'status-text-online' : 'status-text-offline'">
        {{ online ? '在线' : '离线' }}
      </span>
    </template>

    <div class="metrics-grid">
      <MetricCard label="当前位置" :value="positionDisplay" unit="mm" />
      <MetricCard label="当前目标" :value="targetDisplay" unit="mm" />
      <MetricCard label="运行状态" :value="act.running ? '运行' : '停止'" />
      <MetricCard label="振动状态" :value="act.vibration_enabled ? '振动中' : '已停止'" />
    </div>

    <div class="chips-row">
      <el-tag :type="hasFault ? 'danger' : 'success'" size="small">
        {{ hasFault ? '故障: ' + faultText : '无故障' }}
      </el-tag>
      <el-tag :type="act.running ? 'success' : 'info'" size="small">
        执行器{{ act.running ? '运行中' : '已停止' }}
      </el-tag>
      <el-tag :type="act.vibration_enabled ? 'warning' : 'info'" size="small">
        振动{{ act.vibration_enabled ? '中' : '已停止' }}
      </el-tag>
    </div>

    <el-alert
      v-if="!online && act.error"
      :title="act.error"
      type="error"
      show-icon
      :closable="false"
      class="error-alert"
    />

    <div class="register-section">
      <h4 class="section-title">保持寄存器 0 - 14</h4>
      <el-table :data="registerTableData" size="small" border stripe>
        <el-table-column prop="address" label="地址" width="60" align="center" />
        <el-table-column prop="name" label="名称" width="110" />
        <el-table-column prop="rawValue" label="原始值" width="80" align="center">
          <template #default="{ row }">
            {{ row.rawValue != null ? row.rawValue : '--' }}
          </template>
        </el-table-column>
        <el-table-column prop="parsedValue" label="解析值" min-width="140" />
        <el-table-column prop="unit" label="单位 / 含义" min-width="160" />
        <el-table-column label="写入" width="180" align="center" fixed="right">
          <template #default="{ row }">
            <template v-if="isWritable(row.address)">
              <div class="write-cell">
                <el-input-number
                  v-model="editValues[row.address]"
                  :min="row.address === 14 ? 0 : undefined"
                  :max="row.address === 14 ? 1 : undefined"
                  :step="row.address === 13 ? 100 : 1"
                  size="small"
                  controls-position="right"
                  style="width: 100px"
                  :disabled="store.isRunning"
                />
                <el-button
                  type="primary"
                  size="small"
                  :disabled="store.isRunning"
                  @click="handleWrite(row.address)"
                >
                  写入
                </el-button>
              </div>
            </template>
            <span v-else class="readonly-hint">只读</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </PanelSection>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useDeviceStore } from '../stores/device.js'
import { writeLa10Register } from '../api/index.js'
import PanelSection from './PanelSection.vue'
import MetricCard from './MetricCard.vue'

const store = useDeviceStore()
const act = computed(() => store.actuator)

const online = computed(() => act.value.online)

const positionDisplay = computed(() => {
  const v = act.value.position_mm
  return v != null ? v.toFixed(4) : '--'
})

const targetDisplay = computed(() => {
  const v = act.value.target_mm
  return v != null ? v.toFixed(4) : '--'
})

// --- Fault bits ---
const faultLabels = ['堵转', '过温', '过流', '电机异常']

const faultList = computed(() => {
  const bits = act.value.fault_bits
  if (bits == null) return []
  return faultLabels.filter((_, i) => bits & (1 << i))
})

const hasFault = computed(() => faultList.value.length > 0)

const faultText = computed(() => {
  return faultList.value.length > 0 ? faultList.value.join(' / ') : '正常'
})

// --- Register metadata (hardcoded from Python backend) ---
const registerMeta = [
  { address: 0, name: '控制命令', unit: '1=工作，2=暂停，3=急停，4=清故障' },
  { address: 1, name: '运动方向', unit: '0=缩回，1=伸出' },
  { address: 2, name: '运动距离', unit: '0.01 mm' },
  { address: 3, name: '运动速度', unit: '0.01 mm/s' },
  { address: 4, name: '运动使能', unit: '写 1 启动相对运动' },
  { address: 5, name: '当前位置', unit: '约 200 单位/mm' },
  { address: 6, name: '当前目标', unit: '约 200 单位/mm' },
  { address: 7, name: '温度', unit: 'int16，degC' },
  { address: 8, name: '电流', unit: 'mA' },
  { address: 9, name: '故障位', unit: 'bit0 堵转，bit1 过温，bit2 过流，bit3 电机异常' },
  { address: 10, name: '运行状态', unit: '0=停止，1=运行' },
  { address: 11, name: '最后结果', unit: '0=成功；非 0 为网关错误码' },
  { address: 12, name: '振动频率', unit: 'Hz，允许 10-80' },
  { address: 13, name: '占空比', unit: '1000-5000 对应 10%-50%' },
  { address: 14, name: '振动使能', unit: '0=停止，1=振动' },
]

const writableSet = computed(() => store.la10WritableRegisters)

function isWritable(address) {
  return writableSet.value.has(address)
}

// --- Look up raw register value from store ---
function getRegisterRawValue(address) {
  const regs = act.value.registers
  if (!regs || !Array.isArray(regs)) return null
  const found = regs.find((r) => r.address === address)
  return found ? found.value : null
}

// --- Parse register value for display ---
function parseRegisterValue(meta, raw) {
  if (raw == null) return '--'

  switch (meta.address) {
    case 1:
      return raw === 0 ? '缩回' : raw === 1 ? '伸出' : String(raw)
    case 2:
      return (raw / 100).toFixed(2) + ' mm'
    case 3:
      return (raw / 100).toFixed(2) + ' mm/s'
    case 5:
    case 6:
      return (raw / 200).toFixed(4) + ' mm'
    case 7:
      return raw + ' degC'
    case 8:
      return raw + ' mA'
    case 9: {
      const faults = []
      if (raw & 0x01) faults.push('堵转')
      if (raw & 0x02) faults.push('过温')
      if (raw & 0x04) faults.push('过流')
      if (raw & 0x08) faults.push('电机异常')
      return faults.length > 0 ? faults.join(' / ') : '正常'
    }
    case 10:
      return raw === 1 ? '运行' : raw === 0 ? '停止' : String(raw)
    case 12:
      return raw + ' Hz'
    case 13:
      return (raw / 100).toFixed(2) + ' %'
    case 14:
      return raw === 1 ? '振动中' : raw === 0 ? '已停止' : String(raw)
    default:
      return String(raw)
  }
}

const registerTableData = computed(() => {
  return registerMeta.map((meta) => {
    const raw = getRegisterRawValue(meta.address)
    return {
      address: meta.address,
      name: meta.name,
      rawValue: raw,
      parsedValue: parseRegisterValue(meta, raw),
      unit: meta.unit,
    }
  })
})

// --- Write state ---
const editValues = reactive({})

// Initialize edit values from register data
watch(
  () => act.value.registers,
  (regs) => {
    if (!regs || !Array.isArray(regs)) return
    for (const reg of regs) {
      if (isWritable(reg.address) && editValues[reg.address] == null) {
        editValues[reg.address] = reg.value
      }
    }
  },
  { immediate: true, deep: true }
)

async function handleWrite(address) {
  const value = editValues[address]
  if (value == null) {
    ElMessage.warning('请输入要写入的值')
    return
  }
  try {
    await writeLa10Register(address, value)
    ElMessage.success(`寄存器 ${address} 写入成功`)
  } catch (e) {
    ElMessage.error(`寄存器 ${address} 写入失败: ${e.message || e}`)
  }
}
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
  flex-wrap: wrap;
}

.error-alert {
  margin-top: 12px;
}

.register-section {
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

.write-cell {
  display: flex;
  align-items: center;
  gap: 4px;
}

.readonly-hint {
  color: #c0c4cc;
  font-size: 12px;
}
</style>
