<template>
  <PanelSection title="试验记录查询">
    <template #header-actions>
      <el-tag type="info" size="small" effect="plain">
        {{ totalCount > 0 ? totalCount + ' 条记录' : '无记录' }}
      </el-tag>
    </template>

    <!-- Filter row -->
    <div class="filter-row">
      <div class="filter-item">
        <label class="filter-label">类型</label>
        <el-select v-model="filters.type" placeholder="全部类型" size="small" clearable style="width: 170px">
          <el-option label="全部类型" value="" />
          <el-option label="闭环加粉 100mg" value="feedback_dispense_100mg" />
          <el-option label="闭环加粉 300mg" value="feedback_dispense_300mg" />
          <el-option label="闭环加粉 500mg" value="feedback_dispense_500mg" />
          <el-option label="闭环加粉（其他质量）" value="feedback_dispense" />
          <el-option label="批量加粉" value="dispense_batch" />
          <el-option label="振动喂料" value="vibration_feed" />
          <el-option label="窗口位置扫描" value="window_position_sweep" />
          <el-option label="窗口 PID" value="window_pid_dispense" />
          <el-option label="连续收敛" value="continuous_taper_dispense" />
          <el-option label="定速出粉" value="constant_rate_dispense" />
          <el-option label="定速批量" value="constant_rate_batch" />
          <el-option label="天平漂移" value="at8811c_drift" />
        </el-select>
      </div>
      <div class="filter-item">
        <label class="filter-label">起始日期</label>
        <el-date-picker
          v-model="filters.dateFrom"
          type="date"
          placeholder="起始"
          size="small"
          value-format="YYYY-MM-DD"
          style="width: 145px"
        />
      </div>
      <div class="filter-item">
        <label class="filter-label">结束日期</label>
        <el-date-picker
          v-model="filters.dateTo"
          type="date"
          placeholder="结束"
          size="small"
          value-format="YYYY-MM-DD"
          style="width: 145px"
        />
      </div>
      <div class="filter-item">
        <label class="filter-label">结果</label>
        <el-select v-model="filters.result" placeholder="全部" size="small" clearable style="width: 100px">
          <el-option label="全部" value="" />
          <el-option label="通过" value="passed" />
          <el-option label="失败" value="failed" />
        </el-select>
      </div>
      <div class="filter-item filter-btn-item">
        <el-button type="primary" size="small" @click="handleQuery" :loading="queryLoading">
          查询
        </el-button>
      </div>
    </div>

    <el-alert title="后端每次最多返回200条记录；可按日期和类型缩小范围查询最新实验。" type="info" :closable="false" style="margin-bottom:14px" />
    <!-- Summary stat cards -->
    <div class="summary-cards">
      <div class="summary-card">
        <span class="summary-value">{{ totalCount }}</span>
        <span class="summary-label">记录总数</span>
      </div>
      <div class="summary-card">
        <span class="summary-value">{{ passRate }}%</span>
        <span class="summary-label">通过率</span>
      </div>
      <div class="summary-card">
        <span class="summary-value">{{ avgFinalMass }}</span>
        <span class="summary-label">平均最终质量 (mg)</span>
      </div>
      <div class="summary-card">
        <span class="summary-value">
          <span class="pass-count">{{ passCount }}</span>
          <span class="summary-sep"> / </span>
          <span class="fail-count">{{ failCount }}</span>
        </span>
        <span class="summary-label">通过 / 失败</span>
      </div>
    </div>

    <!-- Results table -->
    <div class="results-section">
      <el-table :data="records" size="small" border stripe max-height="480">
        <el-table-column prop="run_id" label="Run ID" min-width="160" show-overflow-tooltip />
        <el-table-column prop="powder_name" label="粉末" min-width="100" show-overflow-tooltip />
        <el-table-column label="日期" width="130" align="center">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="类型" width="130" align="center">
          <template #default="{ row }">
            {{ typeLabelMap[row.test_type] || row.test_type || '--' }}
          </template>
        </el-table-column>
        <el-table-column label="结果" width="70" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.passed === true" type="success" size="small">通过</el-tag>
            <el-tag v-else-if="row.passed === false" type="danger" size="small">失败</el-tag>
            <span v-else>--</span>
          </template>
        </el-table-column>
        <el-table-column label="最终质量/平均流速" width="150" align="center">
          <template #default="{ row }">
            {{ fmt(row.final_mass_mg) }} / {{ fmt(row.avg_rate_mg_s) }}
          </template>
        </el-table-column>
        <el-table-column label="目标/CV%" width="120" align="center">
          <template #default="{ row }">
            {{ fmt(row.target_mg) }} / {{ fmt(row.cv_percent) }}%
          </template>
        </el-table-column>
        <el-table-column label="耗时(s)" width="80" align="center">
          <template #default="{ row }">
            {{ fmt(row.elapsed_s) }}
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.remark || '--' }}
          </template>
        </el-table-column>
      </el-table>
      <div v-if="records.length === 0 && !queryLoading" class="empty-results">
        <span class="muted">暂无记录，请点击「查询」加载数据</span>
      </div>
    </div>
  </PanelSection>
</template>

<script setup>
import { ref, computed, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getTestRecords } from '../api/index.js'
import { recordQuery } from '../utils/dispense.js'
import PanelSection from './PanelSection.vue'

const typeLabelMap = {
  feedback_dispense: '闭环加粉',
  dispense_batch: '批量加粉',
  feedback_dispense_100mg: '闭环加粉(100mg)',
  feedback_dispense_300mg: '闭环加粉(300mg)',
  feedback_dispense_500mg: '闭环加粉(500mg)',
  vibration_feed: '振动喂料',
  window_position_sweep: '窗口扫描',
  window_pid_dispense: '窗口PID',
  continuous_taper_dispense: '连续收敛',
  constant_rate_dispense: '定速出粉',
  constant_rate_batch: '定速批量',
  at8811c_drift: '天平漂移',
}

const filters = reactive({
  type: '',
  dateFrom: '',
  dateTo: '',
  result: '',
})

const records = ref([])
const queryLoading = ref(false)

const totalCount = computed(() => records.value.length)

const passCount = computed(() => records.value.filter((r) => r.passed === true).length)
const failCount = computed(() => records.value.filter((r) => r.passed === false).length)

const passRate = computed(() => {
  if (records.value.length === 0) return '0.0'
  const withVerdict = records.value.filter((r) => r.passed !== null && r.passed !== undefined)
  if (withVerdict.length === 0) return '0.0'
  return ((withVerdict.filter((r) => r.passed).length / withVerdict.length) * 100).toFixed(1)
})

const avgFinalMass = computed(() => {
  const vals = records.value
    .map((r) => r.final_mass_mg)
    .filter((v) => v !== null && v !== undefined)
  if (vals.length === 0) return '--'
  const sum = vals.reduce((a, b) => a + b, 0)
  return (sum / vals.length).toFixed(2)
})

async function handleQuery() {
  queryLoading.value = true
  try {
    const params = recordQuery(filters)

    const data = await getTestRecords(params)
    records.value = (Array.isArray(data) ? data : (data.records || [])).map(row => ({
      ...row,
      passed: row.status === 'passed' ? true : row.status === 'failed' ? false : row.passed,
      created_at: row.date || row.created_at,
      target_mg: row.target_mass_mg ?? row.target_mg,
      elapsed_s: row.actual_duration_s ?? row.elapsed_s,
      avg_rate_mg_s: row.overall_mean_rate_mg_s ?? row.avg_rate_mg_s,
      cv_percent: row.overall_cv_pct ?? row.cv_percent,
      remark: row.error || row.note || row.remark,
    }))
  } catch (_e) {
    ElMessage.error('查询失败')
  } finally {
    queryLoading.value = false
  }
}

function formatDate(d) {
  if (!d) return '--'
  if (typeof d === 'string') {
    if (/^\d{8}$/.test(d)) return d.slice(0,4) + '-' + d.slice(4,6) + '-' + d.slice(6,8)
    return d.slice(0, 10)
  }
  return d
}

function fmt(v) {
  if (v === undefined || v === null || v === '') return '--'
  if (typeof v === 'number') {
    if (Number.isInteger(v)) return String(v)
    return v.toFixed(2)
  }
  return String(v)
}

onMounted(() => {
  handleQuery()
})
</script>

<style scoped>
.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
  margin-bottom: 16px;
}

.filter-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.filter-label {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}

.filter-btn-item {
  padding-bottom: 2px;
}

.summary-cards {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 10px;
  margin-bottom: 18px;
}

.summary-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 14px 8px;
  background: #f5f7fa;
  border-radius: 6px;
  border: 1px solid #e4e7ed;
}

.summary-value {
  font-size: 22px;
  font-weight: 700;
  color: #303133;
  display: flex;
  align-items: center;
  gap: 2px;
}

.summary-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.pass-count {
  color: #67c23a;
}

.fail-count {
  color: #f56c6c;
}

.summary-sep {
  color: #c0c4cc;
  font-weight: 400;
}

.results-section {
  margin-top: 4px;
}

.empty-results {
  padding: 30px 0;
  text-align: center;
}

.muted {
  color: #c0c4cc;
  font-size: 13px;
}
</style>
