export const isValidTarget = value => Number.isInteger(value) && value >= 100 && value <= 1000
export const isValidLargeTarget = value => Number.isInteger(value) && value >= 1000 && value <= 10000

export function recordQuery(filters) {
  const query = {}
  if (filters.type) query.test_type = filters.type
  if (filters.dateFrom) query.date_from = filters.dateFrom.replaceAll('-', '')
  if (filters.dateTo) query.date_to = filters.dateTo.replaceAll('-', '')
  if (filters.result) query.result = filters.result
  return query
}

function integer(value, min, max, label) {
  if (!Number.isInteger(value) || value < min || value > max) throw new Error(`${label}必须是 ${min}–${max} 之间的整数`)
}

export function validateInitial(initial) {
  integer(initial.frequency_hz, 10, 80, '频率')
  integer(initial.duty_permyriad, 1000, 5000, '占空比万分值')
  if (!Number.isInteger(initial.window_position_units)) throw new Error('窗口位置必须是整数')
}

export function dispensePayload(powderId, targetMg, config, manual = null) {
  if (!powderId) throw new Error('请先选择粉末类型')
  if (!isValidTarget(targetMg)) throw new Error('目标质量需为 100–1000 mg 整数')
  if (!config || config.powder_id !== powderId || config.target_mg !== targetMg) throw new Error('请等待当前粉末与目标的控制配置加载完成')
  const payload = { powder_id: powderId, powder_name: config.powder_name, target_mg: targetMg }
  // Preserve the standard seed while allowing the API layer to offset only
  // the outgoing request copy.
  if (config.initial) payload.initial = { ...config.initial }
  if (manual) {
    validateInitial(manual.initial)
    payload.initial = { ...manual.initial }
    if (manual.preset_id) payload.preset_id = manual.preset_id
  }
  return payload
}

export const LARGE_DEFAULT_DUTY_PERMYRIAD = 2000

export function largeDispensePayload(powderId, targetMg, windowPositionUnits = 600, dutyPermyriad = LARGE_DEFAULT_DUTY_PERMYRIAD) {
  if (!powderId) throw new Error('请先选择粉末类型')
  if (!isValidLargeTarget(targetMg)) throw new Error('大重量目标需为 1000–10000 mg 整数')
  if (!Number.isInteger(windowPositionUnits)) throw new Error('大重量窗口位置必须是整数')
  integer(dutyPermyriad, 1000, 5000, '大重量预加粉占空比万分值')
  return {
    powder_id: powderId,
    target_mg: targetMg,
    initial: { window_position_units: windowPositionUnits, duty_permyriad: dutyPermyriad },
  }
}

export function dispenseQueueItem(powderId, targetMg, config, repeats, manual = null) {
  integer(repeats, 1, 20, '重复次数')
  const payload = dispensePayload(powderId, targetMg, config, manual)
  const initial = payload.initial || config.initial
  validateInitial(initial)
  return {
    type: 'dispense', typeLabel: '加粉',
    params: { powder_id: powderId, powder_name: config.powder_name, target_mg: targetMg,
      preset_id: payload.preset_id || config.preset_id, ...initial, repeat_count: repeats },
  }
}

export function validateBatchQueue(queue) {
  if (!queue.length || queue.length > 20) throw new Error('批量队列需为 1–20 组')
  const types = new Set(queue.map(item => item.type))
  if (types.size !== 1) throw new Error('定速测试与加粉任务请分批执行，不能混合运行')
  if (!['constant-rate', 'dispense'].includes(queue[0].type)) throw new Error('未知批量类型')
  for (const item of queue) {
    validateInitial(item.params)
    integer(item.params.repeat_count || 1, 1, 20, '重复次数')
  }
  if (queue[0].type === 'dispense') {
    if (queue.some(item => !item.params.powder_id || !isValidTarget(item.params.target_mg))) throw new Error('加粉批量任务缺少粉末类型或有效目标')
    if (new Set(queue.map(item => item.params.powder_id)).size !== 1) throw new Error('同一批量队列只能使用一种粉末，请先清空现有加粉任务')
  }
}

function parseNumbers(value, label) {
  const parts = value.split(/[,，]/).map(x => x.trim())
  if (!parts.length || parts.some(x => !x || !Number.isFinite(Number(x)))) throw new Error(`${label}列表含空值或无效数字`)
  return [...new Set(parts.map(Number))]
}

export function expandGrid(form) {
  const freqs = parseNumbers(form.freqs, '频率'), duties = parseNumbers(form.duties, '占空比'), windows = parseNumbers(form.windows, '窗口')
  if (freqs.length * duties.length * windows.length > 20) throw new Error('网格最多允许20组，请缩小参数列表')
  const rows = []
  for (const frequency_hz of freqs) for (const duty of duties) for (const window_position_units of windows) {
    const row = { frequency_hz, duty_permyriad: Math.round(duty * 100), window_position_units }
    validateInitial(row)
    rows.push(row)
  }
  return rows
}

export function gridPayload(rows, form, powder) {
  if (!rows.length || rows.length > 20) throw new Error('请先生成1–20组网格预览')
  if (!Number.isFinite(form.duration_s) || form.duration_s < 1 || form.duration_s > 120) throw new Error('每组时长需为1–120秒')
  integer(form.repeat_count, 1, 20, '重复次数')
  const sets = rows.map(row => {
    validateInitial(row)
    return { frequency_hz: row.frequency_hz, duty_permyriad: row.duty_permyriad,
      window_position_units: row.window_position_units, duration_s: form.duration_s, repeat_count: form.repeat_count }
  })
  return { experiment_type: 'constant_rate', powder_id: powder.powder_id || 'custom',
    powder_name: powder.powder_name || 'custom', experiment_id: powder.powder_id || 'custom-scan',
    sets, duration_s: form.duration_s, repeat_count: form.repeat_count,
    tare_between_sets: form.tare_between_sets, auto_collect: form.auto_collect }
}

export function batchResults(result) {
  return (result.set_results || result.batch_results || []).map(row => ({
    ...row, passed: row.acceptance_passed ?? row.passed ?? row.summary?.overall_passed ?? row.acceptance?.passed ?? (row.result === 'completed'),
    avg_rate_mg_s: row.avg_rate_mg_s ?? row.summary?.overall_mean_rate_mg_s,
    cv_percent: row.cv_percent ?? row.summary?.overall_cv_pct,
    final_mass_mg: row.final_mass_mg ?? row.mean_final_mass_mg,
  }))
}
