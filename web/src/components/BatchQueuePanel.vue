<template>
  <PanelSection title="批量测试队列">
    <template #header-actions>
      <el-tag v-if="isConstRate" type="warning" size="small" effect="plain">
        批量运行中
      </el-tag>
      <el-tag v-else type="info" size="small" effect="plain">
        {{ queueCount > 0 ? queueCount + ' 项待执行' : '空闲' }}
      </el-tag>
    </template>

    <!-- Queue table -->
    <div v-if="batchQueue.length > 0" class="queue-section">
      <el-table :data="batchQueue" row-key="id" size="small" border stripe @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="42" align="center" :selectable="row => !isAnyRunning && !batchLoading" />
        <el-table-column label="#" width="45" align="center">
          <template #default="{ $index }">
            {{ $index + 1 }}
          </template>
        </el-table-column>
        <el-table-column label="类型" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.type === 'constant-rate' ? '' : 'success'" size="small">
              {{ row.typeLabel || (row.type === 'constant-rate' ? '定速' : '加粉') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="params.powder_name" label="粉末" min-width="120" />
        <el-table-column prop="params.target_mg" label="目标 mg" width="90" />
        <el-table-column label="流速 mg/s" width="95" align="center">
          <template #default="{ row }">
            {{ row.params.target_rate_mg_s }}
          </template>
        </el-table-column>
        <el-table-column label="频率 Hz" width="75" align="center">
          <template #default="{ row }">
            {{ row.params.frequency_hz }}
          </template>
        </el-table-column>
        <el-table-column label="占空比 %" width="85" align="center">
          <template #default="{ row }">
            {{ fmtDuty(row.params.duty_permyriad) }}
          </template>
        </el-table-column>
        <el-table-column label="窗口" width="70" align="center">
          <template #default="{ row }">
            {{ row.params.window_position_units }}
          </template>
        </el-table-column>
        <el-table-column label="时长 s" width="70" align="center">
          <template #default="{ row }">
            {{ row.params.duration_s }}
          </template>
        </el-table-column>
        <el-table-column label="重复" width="60" align="center">
          <template #default="{ row }">
            {{ row.params.repeat_count || row.params.repeat || 1 }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="70" align="center">
          <template #default="{ row }">
            <el-button
              type="danger"
              size="small"
              :icon="Delete"
              circle
              :disabled="isAnyRunning || batchLoading"
              @click="removeFromQueue(row.id)"
            />
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div v-else class="empty-queue">
      <span class="muted">队列为空</span>
    </div>

    <div class="batch-actions">
      <el-button
        type="primary"
        :disabled="batchQueue.length === 0 || isAnyRunning"
        :loading="batchLoading"
        @click="handleRunAll"
      >
        运行全部
      </el-button>
      <el-button
        type="success"
        :disabled="selectedItems.length === 0 || isAnyRunning"
        :loading="batchLoading"
        @click="handleRunSelected"
      >
        运行选中 ({{ selectedItems.length }})
      </el-button>
      <el-button
        type="danger"
        :disabled="!isAnyRunning || !isConstRate"
        @click="handleStopBatch"
      >
        停止批量
      </el-button>
      <el-button
        type="default"
        :disabled="batchQueue.length === 0 || isAnyRunning"
        @click="clearQueue"
      >
        清空队列
      </el-button>
      <el-button
        type="warning"
        plain
        :disabled="isAnyRunning || batchLoading"
        @click="handleCloseWindow"
      >
        关闭窗口
      </el-button>
      <el-checkbox
        v-model="autoTareBetweenGroups"
        class="tare-checkbox"
      >
        组间自动标零
      </el-checkbox>
      <el-checkbox
        v-if="batchQueue[0]?.type === 'dispense'"
        v-model="closeWindowBetweenRuns"
        class="tare-checkbox"
      >
        每次加粉后关闭窗口
      </el-checkbox>
    </div>

    <!-- Batch results table -->
    <div v-if="batchResults.length > 0" class="results-section">
      <h4 class="section-title">批量结果</h4>
      <el-table :data="batchResults" size="small" border stripe>
        <el-table-column label="#" width="45" align="center">
          <template #default="{ $index }">
            {{ $index + 1 }}
          </template>
        </el-table-column>
        <el-table-column prop="frequency_hz" label="频率" width="70" align="center" />
        <el-table-column prop="powder_name" label="粉末" min-width="120" />
        <el-table-column label="占空比" width="80" align="center">
          <template #default="{ row }">
            {{ fmtDuty(row.duty_permyriad) }}
          </template>
        </el-table-column>
        <el-table-column label="窗口" width="70" align="center">
          <template #default="{ row }">
            {{ row.window_position_units || '--' }}
          </template>
        </el-table-column>
        <el-table-column label="平均流速/CV%" width="130" align="center">
          <template #default="{ row }">
            {{ fmt(row.avg_rate_mg_s) }} / {{ fmt(row.cv_percent) }}%
          </template>
        </el-table-column>
        <el-table-column label="启动延迟" width="85" align="center">
          <template #default="{ row }">
            {{ fmt(row.startup_delay_s) }} s
          </template>
        </el-table-column>
        <el-table-column label="终量" width="85" align="center">
          <template #default="{ row }">
            {{ fmt(row.final_mass_mg) }} mg
          </template>
        </el-table-column>
        <el-table-column label="判定" width="80" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.passed" type="success" size="small">通过</el-tag>
            <el-tag v-else type="danger" size="small">失败</el-tag>
          </template>
        </el-table-column>
      </el-table>

      <div class="summary-line">
        <span>通过率: {{ batchPassRate }}%</span>
        <el-divider direction="vertical" />
        <span>通过 {{ batchPassCount }} / 失败 {{ batchFailCount }}</span>
      </div>
    </div>

    <div v-else-if="isConstRate" class="results-section">
      <span class="muted">等待批量结果...</span>
    </div>
  </PanelSection>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useDeviceStore } from '../stores/device.js'
import { startConstantRateBatch, startDispenseBatch, cancelConstantRate, closeWindow, errorMessage } from '../api/index.js'
import { validateBatchQueue, batchResults as normalizeBatchResults } from '../utils/dispense.js'
import { useBatchQueue } from '../composables/useBatchQueue.js'
import PanelSection from './PanelSection.vue'

const store = useDeviceStore()
const { batchQueue, autoTareBetweenGroups, closeWindowBetweenRuns, removeFromQueue, clearQueue } = useBatchQueue()

const testState = computed(() => store.testState)
const isAnyRunning = computed(() => store.isRunning)

const isConstRate = computed(() => {
  const rid = testState.value.run_id
  return rid && typeof rid === 'string' && (rid.startsWith('const-batch-') || rid.startsWith('disp-batch-'))
})

const queueCount = computed(() => batchQueue.value.length)

const result = computed(() => testState.value.result || {})
const batchResults = computed(() => isConstRate.value ? normalizeBatchResults(result.value) : [])

const batchPassCount = computed(() => batchResults.value.filter((r) => r.passed).length)
const batchFailCount = computed(() => batchResults.value.filter((r) => !r.passed).length)
const batchPassRate = computed(() => {
  if (batchResults.value.length === 0) return 0
  return ((batchPassCount.value / batchResults.value.length) * 100).toFixed(1)
})

const batchLoading = ref(false)
const selectedIds = ref([])
const selectedItems = computed(() => batchQueue.value.filter((item) => selectedIds.value.includes(item.id)))

function handleSelectionChange(rows) {
  selectedIds.value = rows.map((row) => row.id)
}

function queueItemsForRun(items) {
  return JSON.parse(JSON.stringify(items))
}

async function handleRunAll() {
  if (batchQueue.value.length === 0) return

  await runItems(batchQueue.value)
}

async function handleRunSelected() {
  if (selectedItems.value.length === 0) return

  await runItems(selectedItems.value)
}

async function runItems(items) {

  batchLoading.value = true
  try {
    validateBatchQueue(items)
    const snapshot = queueItemsForRun(items)
    const powderName = snapshot[0].params.powder_name || '当前装载粉末'
    await ElMessageBox.confirm('确认使用“' + powderName + '”执行 ' + snapshot.length + ' 组任务？', '批量启动确认', { type: 'warning' })
    const rateItems = snapshot.filter((q) => q.type === 'constant-rate')
    const dispenseItems = snapshot.filter((q) => q.type === 'dispense')

    if (rateItems.length > 0) {
      await startConstantRateBatch({
        target_rate_mg_s: rateItems[0].params.target_rate_mg_s,
        tare_between_sets: autoTareBetweenGroups.value,
        sets: rateItems.map((q) => q.params),
      })
      ElMessage.success(`已启动定速批量测试 (${rateItems.length} 项)`)
    } else if (dispenseItems.length > 0) {
      await startDispenseBatch({
        tare_between_sets: autoTareBetweenGroups.value,
        close_window_between_runs: closeWindowBetweenRuns.value,
        sets: dispenseItems.map((q) => q.params),
      })
      ElMessage.success(`已启动加粉批量测试 (${dispenseItems.length} 项)`)
    }
    await store.fetchSnapshot()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  } finally {
    batchLoading.value = false
  }
}

async function handleStopBatch() {
  try {
    await cancelConstantRate()
    ElMessage.info('批量测试已停止')
  } catch (_e) {
    ElMessage.error('停止失败')
  }
}

async function handleCloseWindow() {
  try {
    await ElMessageBox.confirm('确认将窗口移动到最小安全位置并关闭窗口？', '关闭窗口确认', { type: 'warning' })
    const response = await closeWindow()
    ElMessage.success(`窗口已关闭（位置 ${response.after_position_units}）`)
    await store.fetchSnapshot()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}

function fmtDuty(permyriad) {
  if (permyriad == null) return '--'
  return (permyriad / 100).toFixed(1) + '%'
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
.queue-section {
  margin-bottom: 14px;
}

.empty-queue {
  padding: 20px 0;
  text-align: center;
  border: 1px dashed #dcdfe6;
  border-radius: 4px;
  margin-bottom: 14px;
}

.muted {
  color: #c0c4cc;
  font-size: 13px;
}

.batch-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.tare-checkbox {
  margin-left: 4px;
}

.results-section {
  margin-top: 8px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 8px 0;
  padding-bottom: 6px;
  border-bottom: 1px solid #ebeef5;
}

.summary-line {
  margin-top: 14px;
  padding: 10px 14px;
  background: #f5f7fa;
  border-radius: 6px;
  font-size: 13px;
  color: #606266;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
</style>
