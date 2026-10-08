function finiteNumber(value) {
  if (value == null || value === '' || typeof value === 'boolean') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

// During dispensing the server refreshes raw_weight_mg from each control sample;
// mass_mg can still contain the last idle reading. Preserve zero and negatives.
export function balanceReading(balance = {}, snapshotError = '') {
  balance = balance || {}
  const uncalibrated = balance.calibration?.configured === false || balance.calibration?.valid === false
  const unit = uncalibrated ? 'count' : 'mg'
  const empty = { available: false, text: '--', unit, tagType: 'info' }
  if (snapshotError) return { ...empty, status: '连接中断', note: '无法获取最新读数，请检查服务连接。' }
  if (!balance.online) return { ...empty, status: '未连接', note: balance.error || '等待天平连接与首次采样。' }
  const value = finiteNumber(balance.raw_weight_mg) ?? finiteNumber(balance.mass_mg)
  if (value == null) return { ...empty, status: '等待读数', note: '天平已连接，等待有效采样。' }
  return {
    available: true,
    text: value.toFixed(1),
    unit,
    status: balance.stable === true ? '已稳定' : balance.stable === false ? '读数变化中' : '在线',
    tagType: balance.stable === true ? 'success' : 'warning',
    note: uncalibrated ? '' : '自动刷新 · 请等待读数稳定后操作。',
  }
}

export function taskStatusLabel(status) {
  return { running: '运行中', completed: '已完成', cancelled: '已停止', failed: '任务异常', error: '任务异常', idle: '待命' }[status] || '待命'
}
