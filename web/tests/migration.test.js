import test from 'node:test'
import assert from 'node:assert/strict'
import { recordQuery } from '../src/utils/dispense.js'
import { isValidTarget, dispensePayload, dispenseQueueItem, validateBatchQueue, expandGrid, gridPayload, batchResults } from '../src/utils/dispense.js'

const config = { powder_id:'bentonite', powder_name:'膨润土', target_mg:1000, preset_id:'bentonite-seed', initial:{frequency_hz:80,duty_permyriad:2200,window_position_units:300} }
const form = {freqs:'40,60',duties:'10,20',windows:'250',duration_s:15,repeat_count:3,tare_between_sets:true,auto_collect:true}
test('record filters use the existing backend compact date format',()=>{
  assert.deepEqual(recordQuery({dateFrom:'2026-08-26',dateTo:'2026-08-26',type:'feedback_dispense',result:'passed'}),{
    date_from:'20260826',date_to:'20260826',test_type:'feedback_dispense',result:'passed'
  })
  assert.deepEqual(recordQuery({}),{})
})
test('integer target contract includes arbitrary 100..1000 mg values',()=>{
  for(const value of [100,437,1000])assert.equal(isValidTarget(value),true)
  for(const value of [99,1001,437.5,null,'500',NaN])assert.equal(isValidTarget(value),false)
})
test('automatic start sends identity without overriding server settings',()=>{
  assert.deepEqual(dispensePayload('bentonite',1000,config),{powder_id:'bentonite',powder_name:'膨润土',target_mg:1000})
})
test('stale previews and missing identity cannot start',()=>{
  assert.throws(()=>dispensePayload('',1000,config))
  assert.throws(()=>dispensePayload('bentonite',500,config))
  assert.throws(()=>dispensePayload('different',1000,config))
  assert.throws(()=>dispensePayload('bentonite',1000,null))
})
test('manual seed preserves powder identity and clones input',()=>{
  const seed={preset_id:'custom',initial:{frequency_hz:60,duty_permyriad:2000,window_position_units:250}}
  const payload=dispensePayload('bentonite',1000,config,seed)
  assert.equal(payload.powder_id,'bentonite');assert.equal(payload.preset_id,'custom')
  seed.initial.frequency_hz=70;assert.equal(payload.initial.frequency_hz,60)
})
test('queue carries powder name, preset, automatic seed and repeats',()=>{
  const item=dispenseQueueItem('bentonite',1000,config,20)
  assert.equal(item.params.powder_name,'膨润土');assert.equal(item.params.repeat_count,20)
  assert.equal(item.params.preset_id,'bentonite-seed');assert.equal(item.params.frequency_hz,80)
  assert.doesNotThrow(()=>validateBatchQueue([item]))
})
test('queue rejects mixed powders, mixed types and over-limit counts',()=>{
  const item=dispenseQueueItem('bentonite',1000,config,1)
  assert.throws(()=>validateBatchQueue([item,{...item,params:{...item.params,powder_id:'other'}}]))
  assert.throws(()=>validateBatchQueue([item,{type:'constant-rate',params:{...config.initial}}]))
  assert.throws(()=>validateBatchQueue(Array(21).fill(item)))
})
test('invalid actuator seeds are blocked before dispatch',()=>{
  for(const field of ['frequency_hz','duty_permyriad','window_position_units'])assert.throws(()=>dispensePayload('bentonite',1000,config,{initial:{...config.initial,[field]:null}}))
})
test('grid preserves removed and edited rows, never re-expands dimensions',()=>{
  const rows=expandGrid(form);assert.equal(rows.length,4)
  rows.splice(1,1);rows[0].frequency_hz=55
  const payload=gridPayload(rows,form,{powder_id:'bentonite',powder_name:'膨润土'})
  assert.equal(payload.sets.length,3);assert.equal(payload.sets[0].frequency_hz,55)
  assert.equal(payload.dimensions,undefined);assert.equal(payload.sets[0].repeat_count,3)
  rows[0].frequency_hz=60;assert.equal(payload.sets[0].frequency_hz,55)
})
test('grid rejects blank lists, invalid rows, excess combinations and invalid duration',()=>{
  for(const freqs of ['', '40,,60', 'NaN','9','81'])assert.throws(()=>expandGrid({...form,freqs}))
  assert.throws(()=>expandGrid({...form,freqs:'10,20,30,40,50,60,70,80',duties:'10,20,30'}))
  assert.throws(()=>gridPayload(expandGrid(form),{...form,duration_s:121},{}))
  assert.throws(()=>gridPayload([{frequency_hz:null,duty_permyriad:2000,window_position_units:250}],form,{}))
})
test('batch results use source acceptance and mean mass fields',()=>{
  const rows=batchResults({set_results:[{acceptance_passed:false,mean_final_mass_mg:1020},{acceptance_passed:true,mean_final_mass_mg:1001}]})
  assert.equal(rows[0].passed,false);assert.equal(rows[1].passed,true);assert.equal(rows[1].final_mass_mg,1001)
})
test('constant-rate completion does not override failed acceptance',()=>{
  const [row]=batchResults({set_results:[{result:'completed',summary:{overall_passed:false,overall_mean_rate_mg_s:9.2,overall_cv_pct:20}}]})
  assert.equal(row.passed,false);assert.equal(row.avg_rate_mg_s,9.2);assert.equal(row.cv_percent,20)
})
