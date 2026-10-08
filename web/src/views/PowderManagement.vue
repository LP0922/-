<template>
  <div class="page">
    <el-card shadow="never">
      <template #header><div class="row"><span>粉末控制配置</span><el-button :disabled="locked" @click="refresh">刷新</el-button></div></template>
      <el-alert title="正式加粉以专属控制配置优先；指纹分类仅影响没有专属配置的粉末。草稿、已验证等状态会在加粉页明确显示。" type="info" :closable="false" />
      <el-table :data="profiles" border stripe class="spaced">
        <el-table-column prop="powder_name" label="粉末" min-width="120" />
        <el-table-column label="验证状态" width="150"><template #default="{row}"><el-tag :type="row.status === 'validated' ? 'success' : 'warning'">{{ statusZh(row.status) }}</el-tag></template></el-table-column>
        <el-table-column prop="recommended_preset_id" label="推荐起始参数预设" min-width="240" show-overflow-tooltip />
        <el-table-column label="目标质量锚点（mg）" min-width="170"><template #default="{row}">{{ row.anchor_masses_mg?.join(', ') }}</template></el-table-column>
        <el-table-column label="配置使用注意事项" min-width="190">
          <template #default="{row}">
            <span v-if="!warningItems(row).length" class="muted">无</span>
            <el-popover v-else placement="left" :width="520" trigger="click">
              <template #reference><el-button link type="primary">查看 {{ warningItems(row).length }} 项中文说明</el-button></template>
              <div class="warning-title">{{ row.powder_name }} · 配置使用注意事项</div>
              <ul class="warning-list"><li v-for="warning in warningItems(row)" :key="warning">{{ warning }}</li></ul>
            </el-popover>
          </template>
        </el-table-column>
      </el-table>
      <router-link to="/dispense">进入按粉末配置加粉</router-link>
    </el-card>
    <el-card shadow="never">
      <template #header><div class="row"><span>粉末特征码</span><el-tag :type="status.loaded ? 'success' : 'info'">{{ status.loaded ? '已加载' : '未加载' }}</el-tag></div></template>
      <el-alert v-if="status.loaded" :title="'当前会话：'+(status.powder_name || status.powder_id)" type="success" :closable="false" />
      <el-form inline class="spaced" :disabled="locked">
        <el-form-item label="已有粉末"><el-select v-model="selected" filterable placeholder="选择指纹" style="width:280px"><el-option v-for="item in fingerprints" :key="item.powder_id" :label="item.powder_name || item.powder_id" :value="item.powder_id" /></el-select></el-form-item>
        <el-form-item><el-button type="primary" :disabled="!selected" @click="applySelected">加载指纹</el-button></el-form-item>
        <el-form-item><el-button type="danger" plain :disabled="!selected" @click="removeSelected">删除指纹</el-button></el-form-item>
        <el-form-item v-if="status.loaded" label="会话分类"><el-select :model-value="status.category" style="width:170px" @change="changeCategory"><el-option v-for="category in categoryOptions" :key="category.value" :label="category.label" :value="category.value"/></el-select></el-form-item>
      </el-form>
      <el-table :data="fingerprints" border stripe>
        <el-table-column prop="powder_name" label="名称" min-width="150" />
        <el-table-column prop="powder_id" label="ID" min-width="240" show-overflow-tooltip />
        <el-table-column label="分类" width="130"><template #default="{row}">{{ categoryZh(row.category) }}</template></el-table-column>
        <el-table-column prop="steady_rate_mg_s" label="稳态流量 mg/s" width="150" />
        <el-table-column prop="created_at" label="创建时间" min-width="180" />
      </el-table>
    </el-card>
    <div class="two">
      <el-card shadow="never">
        <template #header>探针测试</template>
        <el-form label-width="130px" :disabled="locked">
          <el-form-item label="粉末名称"><el-input v-model="probe.powder_name" /></el-form-item>
          <el-form-item label="频率 Hz"><el-input-number v-model="probe.frequency_hz" :min="10" :max="80" /></el-form-item>
          <el-form-item label="占空比万分值"><el-input-number v-model="probe.duty_permyriad" :min="1000" :max="5000" :step="50" /></el-form-item>
          <el-form-item label="窗口位置"><el-input-number v-model="probe.window_position_units" :min="100" :max="750" /></el-form-item>
          <el-form-item label="测试时长(秒)"><el-input-number v-model="probe.duration_s" :min="3" :max="120" /></el-form-item>
          <el-form-item><el-button type="primary" @click="runProbe">开始探针测试</el-button></el-form-item>
        </el-form>
      </el-card>
      <el-card shadow="never">
        <template #header>稳态流量搜索</template>
        <el-form label-width="130px" :disabled="locked">
          <el-form-item label="粉末名称"><el-input v-model="search.powder_name" /></el-form-item>
          <el-form-item label="下限 mg/s"><el-input-number v-model="search.target_lo" :min="1" :max="99" /></el-form-item>
          <el-form-item label="上限 mg/s"><el-input-number v-model="search.target_hi" :min="2" :max="100" /></el-form-item>
          <el-form-item><el-button type="warning" @click="runSearch">开始流量搜索</el-button></el-form-item>
        </el-form>
      </el-card>
    </div>
    <el-card v-if="isPowderTask" shadow="never">
      <template #header>{{ test.run_id }} · {{ test.phase || test.status }}</template>
      <el-progress :percentage="Math.max(0,Math.min(100,test.progress_pct||0))" />
      <el-button type="danger" :disabled="!store.isRunning" @click="stop">停止测试</el-button>
      <el-alert v-if="test.result?.error" :title="test.result.error" type="error" :closable="false" />
      <pre v-if="test.result">{{ JSON.stringify(test.result,null,2) }}</pre>
    </el-card>
  </div>
</template>
<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useDeviceStore } from '../stores/device.js'
import { applyPowderFingerprint, deletePowderFingerprint, getPowderFingerprints, getPowderStatus, getControlProfiles, startPowderProbe, startRateSearch, setPowderCategory, cancelConstantRate, errorMessage } from '../api/index.js'
import { validateInitial } from '../utils/dispense.js'
import { categoryZh, statusZh, warningsZh } from '../utils/configI18n.js'
const store=useDeviceStore()
const fingerprints=ref([]),profiles=ref([]),selected=ref(''),busy=ref(false),status=ref({loaded:false})
const test=computed(()=>store.testState||{})
const isPowderTask=computed(()=>/^(probe-|ratesearch-)/.test(test.value.run_id||''))
const locked=computed(()=>busy.value||store.isRunning)
const probe=reactive({powder_name:'',duration_s:20,frequency_hz:40,duty_permyriad:2000,window_position_units:250})
const search=reactive({powder_name:'',target_lo:10,target_hi:30})
const categoryOptions=[
  {value:'Low-flow',label:'低流动性'},
  {value:'Medium-flow',label:'中等流动性'},
  {value:'High-flow',label:'高流动性'},
]
const warningItems=row=>warningsZh(row.generation_warnings)
function fail(error){if(error!=='cancel'&&error!=='close')ElMessage.error(errorMessage(error))}
async function refresh(){try{const [list,session,controls]=await Promise.all([getPowderFingerprints(),getPowderStatus(),getControlProfiles()]);fingerprints.value=list;status.value=session;profiles.value=controls}catch(error){fail(error)}}
async function applySelected(){try{await applyPowderFingerprint(selected.value);await refresh();ElMessage.success('指纹参数已加载')}catch(error){fail(error)}}
async function removeSelected(){try{await ElMessageBox.confirm('确认删除所选粉末的所有指纹版本？不会删除专属控制配置。','删除确认',{type:'warning'});await deletePowderFingerprint(selected.value);selected.value='';await refresh()}catch(error){fail(error)}}
async function changeCategory(category){try{await setPowderCategory(category);await refresh()}catch(error){fail(error)}}
async function runProbe(){
  busy.value=true
  try{if(!probe.powder_name.trim())throw new Error('请输入粉末名称');validateInitial(probe);if(!Number.isFinite(probe.duration_s)||probe.duration_s<3||probe.duration_s>120)throw new Error('探针时长需为3–120秒');const payload={...probe,powder_name:probe.powder_name.trim()};await ElMessageBox.confirm('确认对“'+payload.powder_name+'”启动探针测试？','启动确认',{type:'warning'});const r=await startPowderProbe(payload);ElMessage.success('探针测试已启动：'+r.run_id);await store.fetchSnapshot()}catch(error){fail(error)}finally{busy.value=false}
}
async function runSearch(){
  busy.value=true
  try{if(!search.powder_name.trim())throw new Error('请输入粉末名称');if(!(search.target_lo>=1&&search.target_lo<search.target_hi&&search.target_hi<=100))throw new Error('目标范围需满足1 ≤ 下限 < 上限 ≤ 100');const payload={...search,powder_name:search.powder_name.trim()};await ElMessageBox.confirm('确认对“'+payload.powder_name+'”启动流量搜索？','启动确认',{type:'warning'});const r=await startRateSearch(payload);ElMessage.success('流量搜索已启动：'+r.run_id);await store.fetchSnapshot()}catch(error){fail(error)}finally{busy.value=false}
}
async function stop(){try{await cancelConstantRate();ElMessage.info('已请求停止')}catch(error){fail(error)}}
watch(()=>store.isRunning,(running,wasRunning)=>{if(wasRunning&&!running)refresh()})
onMounted(refresh)
</script>
<style scoped>.page{display:grid;gap:16px}.row{display:flex;justify-content:space-between;align-items:center;gap:12px}.spaced{margin:16px 0}.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}.warning-title{font-weight:600;color:#303133;margin-bottom:10px}.warning-list{margin:0;padding-left:18px;line-height:1.7;max-height:420px;overflow:auto}.warning-list li+li{margin-top:7px}.muted{color:#909399}pre{overflow:auto;max-height:320px}@media(max-width:1000px){.two{grid-template-columns:1fr}}</style>
