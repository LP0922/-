const FIELD_LABELS = {
  schema_version: '配置格式版本',
  powder_id: '粉末 ID',
  powder_name: '粉末名称',
  status: '验证状态',
  category: '流动性分类',
  selectable: '是否可选择',
  recommended_preset_id: '推荐起始参数预设',
  recommended_controller: '推荐控制器参数',
  validation_evidence: '验证依据',
  validated_at: '验证日期',
  acceptance_rule: '验收规则',
  validated_target_masses_mg: '已验证目标质量（mg）',
  passed_runs: '严格通过次数',
  operator_accepted_runs: '操作员认可次数',
  total_runs: '总测试次数',
  strict_pass_rate_pct: '严格通过率（%）',
  operator_acceptance_rate_pct: '操作验收率（%）',
  source_batch_ids: '来源批次 ID',
  source_run_ids: '来源任务 ID',
  final_masses_mg: '最终质量（mg）',
  errors_mg: '质量误差（mg）',
  durations_s: '任务时长（秒）',
  stop_masses_mg: '停止时质量（mg）',
  post_stop_tail_masses_mg: '停机后尾量（mg）',
  stall_recovery_counts: '堵料恢复次数',
  successful_stall_recovery_count: '堵料恢复成功次数',
  failed_stall_recovery_count: '堵料恢复失败次数',
  mean_final_mass_mg: '平均最终质量（mg）',
  mean_absolute_error_mg: '平均绝对误差（mg）',
  mean_duration_s: '平均任务时长（秒）',
  algorithm_version: '控制算法版本',
  validated_initial_parameters: '已验证起始参数',
  operator_approval_note: '操作员确认说明',
  target_rate_bands: '目标质量分段速率',
  target_profiles: '目标质量配置锚点',
  exact_target_overrides: '指定目标质量覆盖参数',
  generation_warnings: '配置使用注意事项',
  target_mg: '目标质量（mg）',
  preset_id: '起始参数预设 ID',
  initial: '起始执行参数',
  frequency_hz: '振动频率（Hz）',
  duty_permyriad: '占空比（万分值）',
  window_position_units: '窗口位置',
  acceptance_min_mg: '验收下限（mg）',
  acceptance_max_mg: '验收上限（mg）',
  profile: '阶段控制参数',
  controller: '过程控制器参数',
  config_source: '配置来源',
  config_source_label: '配置来源说明',
  control_profile_status: '控制配置验证状态',
  control_profile_warnings: '控制配置使用注意事项',
  target_resolution: '目标参数解析方式',
  resolution: '解析方式',
  anchor_masses_mg: '参数锚点质量（mg）',
  target_rate_band_source: '阶段速率来源',
  minimum_target_mg: '目标质量下限（mg）',
  maximum_target_mg: '目标质量上限（mg）',
  coarse_rate_mg_s: '粗加阶段目标速率（mg/s）',
  fine_rate_mg_s: '细加阶段目标速率（mg/s）',
  precision_rate_mg_s: '精加阶段目标速率（mg/s）',
  settle_rate_mg_s: '稳定阶段目标速率（mg/s）',
  maximum_flow_rate_mg_s: '允许最大流速（mg/s）',
  precision_start_remaining_mg: '进入精加阶段的剩余质量（mg）',
  tail_taper_start_remaining_mg: '开始尾段降速的剩余质量（mg）',
  tail_taper_end_remaining_mg: '结束尾段降速的剩余质量（mg）',
  duty_step_per_update: '每次占空比调整步长',
  emergency_duty_step_per_update: '紧急占空比调整步长',
  position_feedback_enabled: '运行中窗口位置反馈',
  fixed_tail_mass_mg: '固定尾量补偿（mg）',
  force_stop_offset_mg: '强制停止提前量（mg）',
  max_duty_permyriad: '占空比上限（万分值）',
  settle_confirmations_delta: '稳定确认次数增量',
  dead_zone_multiplier: '控制死区倍数',
  fast_predictive_stop_enabled: '快速预测停机',
  fast_predictive_stop_rate_mg_s: '快速预测停机速率阈值（mg/s）',
  fast_predictive_stop_confirmations: '快速预测停机确认次数',
  projected_safety_stop_enabled: '预计质量安全停机',
  projected_safety_stop_offset_mg: '预计质量安全停机提前量（mg）',
  flow_hold_enabled: '轻流量保持',
  flow_hold_window_s: '轻流量观察时间（秒）',
  flow_hold_min_gain_mg: '轻流量最小增量（mg）',
  flow_response_check_s: '流量响应检查时间（秒）',
  flow_response_min_improvement_mg_s: '流量响应最小改善值（mg/s）',
  stall_recovery_enabled: '堵料自动恢复',
  stall_recovery_observation_window_s: '堵料观察时间（秒）',
  stall_recovery_min_gain_mg: '堵料判断最小增量（mg）',
  stall_recovery_rate_threshold_mg_s: '堵料判断速率阈值（mg/s）',
  stall_recovery_resume_rate_mg_s: '恢复出粉速率阈值（mg/s）',
  stall_recovery_retry_s: '堵料恢复重试间隔（秒）',
  stall_recovery_window_step_units: '堵料恢复窗口步长',
  stall_recovery_max_window_position_units: '堵料恢复最大窗口位置',
  stall_recovery_max_attempts: '堵料恢复最大尝试次数',
  stall_recovery_disable_remaining_mg: '停止堵料恢复的剩余质量（mg）',
  tail_pulse_enabled: '尾段脉冲补粉',
  tags: '特征标签',
}

const VALUE_LABELS = {
  draft: '草稿（待验证）',
  validated: '已验证',
  'fingerprint-default': '指纹默认配置',
  dedicated_profile: '专属控制配置',
  fingerprint_with_product_defaults: '粉末指纹＋统一默认参数',
  product_default: '产品统一默认速率',
  powder_profile: '粉末专属阶段速率',
  interpolated: '根据质量锚点插值',
  exact: '使用目标质量精确配置',
  'Low-flow': '低流动性',
  'Medium-flow': '中等流动性',
  'High-flow': '高流动性',
}

const COMMON_WARNINGS = {
  'safe_fine_region has low confidence': '安全细加区域的数据可信度较低。',
  'coarse and fine regions have low confidence': '粗加与细加区域的数据可信度较低。',
  'existing runs show stalls and variable post-stop tail': '已有测试出现过堵料，且停机后的尾量波动较大。',
  'targets above 500 mg are extrapolated until experiments are completed': '500 mg 以上的目标参数目前由外推获得，需等待实验完成后验证。',
  'draft profile: operator supervision is required': '此配置仍处于草稿状态，使用时需要操作员现场监督。',
  'workspace scan is incomplete': '现有实验数据尚未完成全部扫描。',
  'fine-flow and transition behavior require repeated validation': '细流量与阶段切换行为仍需重复验证。',
  'draft only: no validation of this dedicated profile has been performed': '此专属控制配置尚未完成验证，只能在监督下试用。',
}

export function statusZh(value) {
  return VALUE_LABELS[value] || value || '--'
}

export function categoryZh(value) {
  return VALUE_LABELS[value] || value || '--'
}

export function warningZh(warning) {
  const text = String(warning || '').trim()
  if (!text) return ''
  if (COMMON_WARNINGS[text]) return COMMON_WARNINGS[text]
  const scans = text.match(/^(\d+) scan points are still pending$/)
  if (scans) return `仍有 ${scans[1]} 个参数扫描点尚未完成。`
  if (text.includes('stage target rates use the operator-selected')) return '各阶段目标速率使用操作员选定的 100–500 mg 与 501–1000 mg 两个质量区间。'
  if (text.includes('validated only for predictive-stop-v3-bentonite-fast-tail')) return '1000 mg 仅在记录的 predictive-stop-v3-bentonite-fast-tail 算法及控制器参数下完成验证。'
  if (text.includes('strict product-window performance was 9 of 10')) return '严格产品窗口测试 10 次通过 9 次；操作员明确接受其中一次 1011 mg 结果。'
  if (text.includes('operator confirmed 润滑剂1 is the same powder')) return '操作员于 2026-08-26 确认“润滑剂1”与“润滑剂-text”为同一种粉末；保留原粉末 ID，历史记录不改写。'
  if (text.includes('historical logs lack powder identity')) return '历史记录缺少粉末标识；润滑剂归属根据 2026-08-17 的本地探针测试时段推断，并非来自明确的粉末字段。'
  if (text.includes('34 historical 100 mg runs')) return '历史 100 mg 测试共 34 次：完成 12 次、超重 2 次、取消 20 次；取消不能作为堵料证据。'
  if (text.includes('70 Hz, 20%, p300 completed')) return '历史测试中 70 Hz、20%、p300 有一次以 105 mg 完成；70 Hz、22%、p300 在 75 mg 时取消，因此 p300 仅作为监督下的起始候选，不是已确认的稳定窗口。'
  if (text.includes('old 70 Hz, 20%, p100 seed')) return '旧的 70 Hz、20%、p100 起始参数来自自动低流量分类，且该位置的多次历史测试被取消，不应作为已验证默认值。'
  if (text.includes('large-particle blockage even at p550')) return '操作员报告大颗粒在 p550 仍可能堵塞；候选占空比上限已由 25% 提至 35%，但尚未验证，不能保证安全或有效。'
  if (text.includes('accidental hand pressure during the 12:01 p400 run')) return '操作员确认 12:01 的 p400 测试受到意外手压干扰并触发 2115 mg 异常读数；保留原始记录，但从精度、流量和尾量拟合中排除。35% 候选值仍需监督下单次验证。'
  if (text.includes('legacy fingerprint tail, stop, settling')) return '保留旧指纹的尾量、停机、稳定和控制步长设置，以及当前产品阶段速率；包括 1000 mg 在内的质量锚点是软件初始值，并非实测标定结果。'
  if (text.includes('position feedback, stall-recovery window movement')) return '已关闭位置反馈、堵料恢复窗口移动和尾段脉冲；仅保留运行前定位，尚未解决的 LA10 运动错误仍可能发生。'
  if (text.includes('prolonged no-flow has no new automatic recovery')) return '长时间无流量时没有新增自动恢复或专用停止逻辑；应手动停止并安全检查，不要等待总超时。'
  if (text.includes('historical 80 Hz, 25%, window 300 runs')) return '旧控制器在 80 Hz、25%、窗口 300 下的历史结果为 1006、1003、1010 和 1013 mg。'
  if (text.includes('current powder batch did not flow at window 300')) return '当前粉末批次在窗口 300 时不出粉；操作测试确认窗口 400 可用、窗口 450 不安全，因此首个监督候选调整为 80 Hz、22%、窗口 400。'
  if (text.includes('flow hold and a 25% duty ceiling')) return '由于历史占空比曾累积至 34.6%，当前启用轻流量保持，并将占空比上限设为 25%。'
  if (text.includes('first correctly identified run timed out at 945 mg')) return '首个正确识别的历史测试在 945 mg 超时，并出现多次零增量平台；之后曾试用 p425 堵料恢复，但现已按操作员要求关闭。'
  if (text.includes('1000 mg duty taper still starts at 80 mg')) return '1000 mg 任务仍在剩余 80 mg 时开始占空比渐降；所有目标质量均已关闭堵料恢复窗口扩张。'
  if (text.includes('after the p425 recovery test finished at 1015 mg')) return 'p425 恢复测试以 1015 mg 完成后，启用了 20 mg/s、一次确认的快速预测停机；记录回放将停机请求由 981 mg 提前至 971 mg。'
  if (text.includes('three fast-stop validation runs finished')) return '三次快速停机验证结果为 1020、1025 和 1033 mg，停机后尾量为 35–62 mg；1000 mg 专用参数现采用 15 mg 固定尾量、剩余 80 mg 开始预测，并在 960 mg 强制停止。'
  if (text.includes('supervised p375 run stalled at 924 mg')) return '一次监督下的 p375 测试在 924 mg 堵塞 93.86 秒，随后恢复至 968 mg 并以 1016 mg 完成；p375 限制过强，而连续 p400 仍容易突增。'
  if (text.includes('fingerprint display name was normalized')) return '粉末指纹显示名称已统一为“封堵剂2”；历史记录未改写。'
  if (text.includes('cancelled the 700 mg stop-and-pulse method')) return '操作员于 2026-08-26 取消 700 mg 停止加脉冲方案；已移除全部尾段脉冲覆盖参数并恢复连续闭环加粉。'
  if (text.includes('disabled all in-run automatic window adjustment')) return '操作员于 2026-08-26 关闭封堵剂2运行中的全部自动窗口调整；仅保留运行前定位，长时间无流量可能由现有总超时结束。'
  if (text.includes('profile validated on 2026-08-25')) return '1000 mg 配置已于 2026-08-25 使用记录的 v4 控制器参数完成验证。'
  if (text.includes('1000 mg baseline produced')) return '1000 mg 基线在旧的三次确认指纹参数下得到 1004、1019 和 1004 mg。'
  if (text.includes('three-run hardware validation produced 986')) return '2026-08-25 的三次硬件验证结果为 986、1010 和 1004 mg；986 mg 结果表明单次确认停机不适用于该粉末。'
  if (text.includes('fast single-confirmation stopping is disabled')) return '已关闭快速单次确认停机；所有预测停机均使用正常的两次确认。'
  if (text.includes('second three-run validation produced')) return '第二组三次验证结果为 988、987 和 992 mg；固定尾量补偿由 5 mg 降至 0 mg，以修正持续偏轻。'
  if (text.includes('stall recovery is enabled for hardware validation')) return '硬件验证启用堵料恢复：正常保持窗口 350，临时最多调整至 375、400，并在最后 50 mg 内停止扩窗。'
  if (text.includes('first v4 three-run batch produced')) return '首组 v4 三次批量结果为 1011、996 和 1022 mg；启用轻流量保持、占空比上限 30%，最大流速降至 30 mg/s，以减少突破前的占空比累积。'
  if (text.includes('11:17 run stopped at 691 mg')) return '2026-08-25 11:17 的测试在 691 mg 停止，原因是成功恢复错误消耗了全局尝试次数；现已在每次恢复后重置次数，并将 4 秒轻流量增量阈值设为 20 mg。'
  if (text.includes('counter-fix three-run batch produced')) return '计数修复后的三次批量结果为 1004、1004 和 1002 mg；七次独立堵料均在第 1 次尝试恢复，因此正式七次验证保持参数不变。'
  if (text.includes('final seven-run batch produced')) return '最终七次批量结果为 993、998、998、999、1007、1011 和 1000 mg；严格窗口通过 6/7，计入操作员认可的 1011 mg 后，操作验收为 7/7。'
  if (text.includes('across the final three-plus-seven validation')) return '最终三次加七次验证中，共检测到 19 次堵料，均成功恢复，没有耗尽恢复次数。'
  if (text.includes('historical powder ID powder-20260817')) return '历史粉末 ID 已迁移为 water_loss_agent_2；历史记录未改写。'
  return '该技术说明尚未提供中文翻译，请联系技术人员核对原始配置记录。'
}

function valueZh(key, value) {
  if (typeof value === 'boolean') return value ? '启用' : '停用'
  if (value == null) return '无'
  if (key === 'generation_warnings' || key === 'control_profile_warnings') {
    return Array.isArray(value) ? value.map(warningZh) : warningZh(value)
  }
  if (typeof value === 'string' && VALUE_LABELS[value]) return VALUE_LABELS[value]
  if (key === 'acceptance_rule' && value === 'target ± 10 mg') return '目标质量允许误差 ±10 mg'
  if (key === 'acceptance_rule' && value.includes('strict product window 990-1010 mg')) {
    return '目标 1000 mg；严格产品窗口为 990–1010 mg，操作员另行认可一次 1011 mg 结果'
  }
  if (key === 'operator_approval_note' && value.includes('requested formalization on 2026-08-24')) {
    return '操作员明确接受 1011 mg 结果，并于 2026-08-24 要求将该配置正式化。'
  }
  if (key === 'operator_approval_note' && value.includes('formal seven-run batch')) {
    return '操作员此前认可 1011 mg；正式七次批量验证中出现一次 1011 mg，且没有控制故障。'
  }
  return value
}

function keyZh(key) {
  if (FIELD_LABELS[key]) return FIELD_LABELS[key]
  if (/^\d+$/.test(key)) return `${key} mg 目标配置`
  return `其他配置参数（${key}）`
}

export function localizeConfig(config) {
  if (Array.isArray(config)) return config.map(item => localizeConfig(item))
  if (!config || typeof config !== 'object') return config
  return Object.fromEntries(Object.entries(config).map(([key, raw]) => {
    const value = valueZh(key, raw)
    return [keyZh(key), value && typeof value === 'object' ? localizeConfig(value) : value]
  }))
}

export function localizedConfigText(config) {
  return JSON.stringify(localizeConfig(config), null, 2)
}

export function warningsZh(warnings) {
  return (warnings || []).map(warningZh).filter(Boolean)
}
