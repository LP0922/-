import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { categoryZh, localizedConfigText, statusZh, warningZh, warningsZh } from '../src/utils/configI18n.js'

test('configuration status and powder categories have customer-facing Chinese labels', () => {
  assert.equal(statusZh('draft'), '草稿（待验证）')
  assert.equal(statusZh('validated'), '已验证')
  assert.equal(categoryZh('Low-flow'), '低流动性')
  assert.equal(categoryZh('Medium-flow'), '中等流动性')
  assert.equal(categoryZh('High-flow'), '高流动性')
})

test('every currently stored control-profile warning has a Chinese display', () => {
  const directory = resolve(import.meta.dirname, '../../server/data/control_profiles')
  const warnings = readdirSync(directory)
    .filter(name => name.endsWith('.json'))
    .flatMap(name => JSON.parse(readFileSync(resolve(directory, name), 'utf8')).generation_warnings || [])
  assert.ok(warnings.length > 30)
  for (const warning of warnings) {
    const translated = warningZh(warning)
    assert.notEqual(translated, warning)
    assert.match(translated, /[\u3400-\u9fff]/)
    assert.doesNotMatch(translated, /尚未提供中文翻译/, warning)
  }
  assert.equal(warningsZh(warnings).length, warnings.length)
})

test('complete resolved configuration uses Chinese field names and values without mutation', () => {
  const config = {
    powder_id: 'bentonite',
    powder_name: '膨润土',
    control_profile_status: 'validated',
    initial: { frequency_hz: 80, duty_permyriad: 2200, window_position_units: 300 },
    profile: { coarse_rate_mg_s: 25, precision_start_remaining_mg: 70 },
    controller: { flow_hold_enabled: false, stall_recovery_enabled: true },
    target_resolution: { resolution: 'exact', anchor_masses_mg: [100, 300, 500] },
    target_rate_band_source: 'powder_profile',
    control_profile_warnings: ['5 scan points are still pending'],
  }
  const text = localizedConfigText(config)
  assert.match(text, /粉末 ID/)
  assert.match(text, /控制配置验证状态/)
  assert.match(text, /已验证/)
  assert.match(text, /振动频率（Hz）/)
  assert.match(text, /粗加阶段目标速率/)
  assert.match(text, /轻流量保持/)
  assert.match(text, /堵料自动恢复/)
  assert.match(text, /解析方式/)
  assert.match(text, /参数锚点质量/)
  assert.match(text, /粉末专属阶段速率/)
  assert.match(text, /仍有 5 个参数扫描点尚未完成/)
  assert.doesNotMatch(text, /"powder_id"|"control_profile_status"|"flow_hold_enabled"|其他配置参数/)
  assert.equal(config.controller.stall_recovery_enabled, true)
})

test('unknown future warnings do not leak untranslated English to the customer page', () => {
  assert.equal(warningZh('future internal warning text'), '该技术说明尚未提供中文翻译，请联系技术人员核对原始配置记录。')
})

test('all fields in current stored profiles have defined Chinese names', () => {
  const directory = resolve(import.meta.dirname, '../../server/data/control_profiles')
  for (const name of readdirSync(directory).filter(name => name.endsWith('.json'))) {
    const profile = JSON.parse(readFileSync(resolve(directory, name), 'utf8'))
    assert.doesNotMatch(localizedConfigText(profile), /其他配置参数（/, name)
  }
})
