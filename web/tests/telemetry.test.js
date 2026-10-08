import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { balanceReading, taskStatusLabel } from '../src/utils/telemetry.js'

test('idle balance is visible without any dispensing task', () => {
  const reading = balanceReading({ online: true, raw_weight_mg: 123.4, stable: true })
  assert.equal(reading.text, '123.4')
  assert.equal(reading.available, true)
  assert.equal(reading.status, '已稳定')
})

test('running samples use refreshed raw_weight_mg instead of stale mass_mg', () => {
  for (const mass of [10, 150.5, 498.2]) {
    assert.equal(balanceReading({ online: true, raw_weight_mg: mass, mass_mg: 999 }).text, mass.toFixed(1))
  }
})

test('zero and negative balance readings are retained', () => {
  assert.equal(balanceReading({ online: true, raw_weight_mg: 0, mass_mg: 99 }).text, '0.0')
  assert.equal(balanceReading({ online: true, raw_weight_mg: -0.5 }).text, '-0.5')
})

test('mass_mg is a compatible fallback, invalid data never displays NaN', () => {
  assert.equal(balanceReading({ online: true, mass_mg: 25.3 }).text, '25.3')
  for (const value of [undefined, null, '', NaN, Infinity, false, 'invalid']) {
    assert.equal(balanceReading({ online: true, raw_weight_mg: value }).text, '--')
    assert.equal(balanceReading({ online: true, raw_weight_mg: value, mass_mg: 0 }).text, '0.0')
  }
})

test('offline hardware and failed snapshot requests hide previous readings', () => {
  assert.equal(balanceReading({ online: false, raw_weight_mg: 500 }).available, false)
  assert.equal(balanceReading({ online: true, raw_weight_mg: 500 }, 'network error').text, '--')
  assert.equal(balanceReading(null).status, '未连接')
  assert.equal(balanceReading({ online: true }).status, '等待读数')
})

test('unstable or unknown stability is not presented as stable', () => {
  assert.equal(balanceReading({ online: true, raw_weight_mg: 10, stable: false }).status, '读数变化中')
  assert.equal(balanceReading({ online: true, raw_weight_mg: 10 }).status, '在线')
})

test('uncalibrated data is marked as raw counts, calibrated data uses mg', () => {
  for (const calibration of [{ configured: false }, { configured: true, valid: false }]) {
    const reading = balanceReading({ online: true, raw_weight_mg: 200, calibration })
    assert.equal(reading.unit, 'count')
    assert.equal(reading.note, '')
  }
  assert.equal(balanceReading({ online: true, raw_weight_mg: 200, calibration: { configured: true, valid: true } }).unit, 'mg')
})

test('customer-facing task labels distinguish completion and active operation', () => {
  assert.equal(taskStatusLabel('completed'), '已完成')
  assert.equal(taskStatusLabel('running'), '运行中')
  assert.equal(taskStatusLabel('failed'), '任务异常')
  assert.equal(taskStatusLabel('cancelled'), '已停止')
})

test('dispense route mounts only the two retained panels', () => {
  const page = readFileSync(new URL('../src/views/DispenseControl.vue', import.meta.url), 'utf8')
  assert.match(page, /<FeedbackDispensePanel\s*\//)
  assert.match(page, /<ConstantRatePanel\s*\//)
  assert.doesNotMatch(page, /WindowSweepPanel|ContinuousTaperPanel|WindowPidPanel/)
})
