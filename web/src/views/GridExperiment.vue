<template>
  <el-card shadow="never">
    <template #header><div class="row"><span>网格扫描实验</span><el-tag>{{ sets.length }} 组参数</el-tag><el-tag v-if="isGrid">{{ test.phase || test.status }}</el-tag></div></template>
    <el-form label-width="130px" :disabled="locked">
      <el-form-item label="预置模板">
        <el-select v-model="templateKey" clearable placeholder="选择模板（或使用自定义参数）" style="width:420px" @change="loadTemplate">
          <el-option v-for="(v,k) in templates" :key="k" :label="v.powder_name+' · '+k" :value="k" />
        </el-select>
      </el-form-item>
      <el-form-item label="频率 Hz"><el-input v-model="form.freqs" aria-label="频率列表" @input="invalidate" /></el-form-item>
      <el-form-item label="占空比 %"><el-input v-model="form.duties" aria-label="占空比列表" @input="invalidate" /></el-form-item>
      <el-form-item label="窗口位置"><el-input v-model="form.windows" aria-label="窗口列表" @input="invalidate" /></el-form-item>
      <el-form-item label="每组时长"><el-input-number v-model="form.duration_s" :min="1" :max="120" /> 秒</el-form-item>
      <el-form-item label="重复次数"><el-input-number v-model="form.repeat_count" :min="1" :max="20" /></el-form-item>
      <el-form-item><el-checkbox v-model="form.tare_between_sets">组间自动去皮</el-checkbox><el-checkbox v-model="form.auto_collect">完成后自动归档</el-checkbox></el-form-item>
    </el-form>
    <div class="row">
      <el-button :disabled="locked" @click="expand">展开/重新生成</el-button>
      <el-button type="primary" :disabled="!sets.length || locked" @click="start">启动扫描</el-button>
      <el-button type="danger" plain :disabled="!store.isRunning || !isGrid" @click="stop">停止</el-button>
      <span>预计采样 {{ estimatedSeconds }} 秒（不含标零和稳定等待）</span>
    </div>
    <el-alert :title="message" :type="messageType" show-icon :closable="false" class="message" />
    <el-table :data="sets" border stripe max-height="480">
      <el-table-column type="index" label="#" width="50"/>
      <el-table-column label="频率 Hz" min-width="165"><template #default="{row}"><el-input-number v-model="row.frequency_hz" :min="10" :max="80" :disabled="locked" size="small" /></template></el-table-column>
      <el-table-column label="占空比 %" min-width="165"><template #default="{row}"><el-input-number :model-value="row.duty_permyriad/100" :min="10" :max="50" :step="0.1" :disabled="locked" size="small" @update:model-value="value=>row.duty_permyriad=value==null?null:Math.round(value*100)" /></template></el-table-column>
      <el-table-column label="窗口位置" min-width="165"><template #default="{row}"><el-input-number v-model="row.window_position_units" :min="100" :max="750" :disabled="locked" size="small" /></template></el-table-column>
      <el-table-column label="操作" width="90"><template #default="{$index}"><el-button type="danger" link :disabled="locked" @click="sets.splice($index,1)">移除</el-button></template></el-table-column>
    </el-table>
    <template v-if="isGrid">
      <p>实验：{{ test.run_id }} · {{ test.status }}</p>
      <el-alert v-if="test.result?.error" :title="test.result.error" type="error" :closable="false" />
      <el-table v-if="results.length" :data="results" border stripe>
        <el-table-column prop="set_index" label="组" width="60"/><el-table-column prop="frequency_hz" label="频率"/><el-table-column prop="window_position_units" label="窗口"/>
        <el-table-column label="结果"><template #default="{row}"><el-tag :type="row.passed?'success':'danger'">{{ row.passed?'通过':'失败' }}</el-tag></template></el-table-column>
      </el-table>
    </template>
  </el-card>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { cancelConstantRate, getGridTemplates, startGridExperiment, errorMessage } from '../api/index.js'
import { expandGrid, gridPayload, batchResults } from '../utils/dispense.js'
import { useDeviceStore } from '../stores/device.js'
const store=useDeviceStore()
const templates=ref({}),templateKey=ref(''),sets=ref([]),starting=ref(false)
const powder=reactive({powder_id:'custom',powder_name:'custom'})
const form=reactive({freqs:'20,40,60',duties:'10,15,20',windows:'250',duration_s:15,repeat_count:3,tare_between_sets:true,auto_collect:true})
const message=ref('选择模板或填写参数后展开；可逐行修改或移除，提交以预览表为准。'),messageType=ref('info')
const test=computed(()=>store.testState||{})
const isGrid=computed(()=>(test.value.run_id||'').startsWith('grid-'))
const locked=computed(()=>store.isRunning||starting.value)
const results=computed(()=>batchResults(test.value.result||{}))
const estimatedSeconds=computed(()=>sets.value.length*(form.duration_s||0)*(form.repeat_count||0))
function fail(error){message.value=errorMessage(error);messageType.value='error'}
function invalidate(){sets.value=[];message.value='参数列表已修改，请重新展开网格';messageType.value='info'}
function expand(){try{sets.value=expandGrid(form);message.value='已展开，可逐行编辑后启动';messageType.value='success'}catch(error){sets.value=[];fail(error)}}
function loadTemplate(){
  invalidate()
  const t=templates.value[templateKey.value]
  if(!t){Object.assign(powder,{powder_id:'custom',powder_name:'custom'});return}
  Object.assign(powder,{powder_id:t.powder_id,powder_name:t.powder_name})
  const dim=n=>t.dimensions?.find(x=>x.name===n)?.values||[]
  form.freqs=dim('frequency_hz').join(',');form.duties=dim('duty_permyriad').map(v=>v/100).join(',');form.windows=dim('window_position_units').join(',')||'250'
  form.duration_s=t.duration_s;form.repeat_count=t.repeat_count;form.tare_between_sets=t.tare_between_sets
  expand()
}
async function start(){
  starting.value=true
  try{
    const payload=gridPayload(sets.value,form,powder)
    await ElMessageBox.confirm('确认粉末已装载，将按预览表执行 '+payload.sets.length+' 组扫描？','启动实验',{type:'warning'})
    const r=await startGridExperiment(payload)
    message.value='实验已启动：'+r.run_id+(r.warnings?.length?'；'+r.warnings.join('；'):'');messageType.value='success'
    await store.fetchSnapshot()
  }catch(error){if(error!=='cancel'&&error!=='close')fail(error)}
  finally{starting.value=false}
}
async function stop(){try{await cancelConstantRate();message.value='已请求停止';messageType.value='info'}catch(error){fail(error)}}
onMounted(async()=>{try{const r=await getGridTemplates();templates.value=r.templates||r}catch(error){fail(error)}})
</script>
<style scoped>.row{display:flex;flex-wrap:wrap;align-items:center;gap:10px}.el-input{max-width:620px}.message{margin:16px 0}.el-table{margin-top:16px}</style>
