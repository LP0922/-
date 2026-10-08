import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// Convert the position shown in the UI to the LA10 device coordinate system.
// The server receives the absolute coordinate used by the motion controller.
const WINDOW_POSITION_OFFSET_UNITS = 750

function withWindowPositionOffset(payload) {
  if (!payload || typeof payload !== 'object') return payload
  const copy = structuredClone(payload)
  const offset = value => (
    Number.isInteger(value) ? value + WINDOW_POSITION_OFFSET_UNITS : value
  )
  if (copy.initial && typeof copy.initial === 'object') {
    copy.initial.window_position_units = offset(copy.initial.window_position_units)
  }
  if (Number.isInteger(copy.window_position_units)) {
    copy.window_position_units = offset(copy.window_position_units)
  }
  if (Array.isArray(copy.sets)) {
    copy.sets = copy.sets.map(item => {
      if (!item || typeof item !== 'object') return item
      return Number.isInteger(item.window_position_units)
        ? { ...item, window_position_units: offset(item.window_position_units) }
        : item
    })
  }
  if (Array.isArray(copy.position_schedule)) {
    copy.position_schedule = copy.position_schedule.map(offset)
  }
  return copy
}

export async function getSnapshot() {
  const { data } = await api.get('/snapshot', { timeout: 3000 })
  return data
}

export async function tareBalance() {
  const { data } = await api.post('/balance/tare')
  return data
}

export async function closeWindow() {
  const { data } = await api.post('/window/minimum')
  return data
}

export async function moveWindowToMinimum() {
  const { data } = await api.post('/window/minimum')
  return data
}

export async function startDispense(payload) {
  const { data } = await api.post('/dispense/start', withWindowPositionOffset(payload))
  return data
}

export async function startLargeDispense(payload) {
  const { data } = await api.post('/dispense/large/start', withWindowPositionOffset(payload))
  return data
}

export async function cancelDispense() {
  const { data } = await api.post('/dispense/cancel')
  return data
}

export async function startLegacy500mg(payload) {
  const { data } = await api.post('/dispense-500mg/start', payload)
  return data
}

export async function cancelLegacy500mg() {
  const { data } = await api.post('/dispense-500mg/cancel')
  return data
}

export async function startContinuousTaper() {
  const { data } = await api.post('/continuous-taper/start')
  return data
}

export async function cancelContinuousTaper() {
  const { data } = await api.post('/continuous-taper/cancel')
  return data
}

export async function startWindowPid() {
  const { data } = await api.post('/window-pid/start')
  return data
}

export async function cancelWindowPid() {
  const { data } = await api.post('/window-pid/cancel')
  return data
}

export async function startConstantRate(payload) {
  const { data } = await api.post('/constant-rate/start', withWindowPositionOffset(payload))
  return data
}

export async function startConstantRateBatch(payload) {
  const { data } = await api.post('/constant-rate/batch', withWindowPositionOffset(payload))
  return data
}

export async function cancelConstantRate() {
  const { data } = await api.post('/constant-rate/cancel')
  return data
}

export async function startDispenseBatch(payload) {
  const { data } = await api.post('/dispense/batch', withWindowPositionOffset(payload))
  return data
}

export async function startVibrationTest(payload) {
  const { data } = await api.post('/vibration-test', payload)
  return data
}

export async function cancelVibrationTest() {
  const { data } = await api.post('/vibration-test/cancel')
  return data
}

export async function startWindowSweep(payload) {
  const { data } = await api.post('/window-position-sweep', withWindowPositionOffset(payload))
  return data
}

export async function writeLa10Register(address, value) {
  const { data } = await api.post('/la10/register', { address, value })
  return data
}

export async function saveTestResult() {
  const { data } = await api.post('/test-result/save')
  return data
}

export async function getTestRecords(params = {}) {
  const { data } = await api.get('/test-records', { params })
  return data
}

export async function getDispensePlans() {
  const { data } = await api.get('/dispense-plans')
  return data
}

export async function getDispensePresets() {
  const { data } = await api.get('/dispense/presets')
  return data
}

export const getPowderFingerprints = async () => (await api.get('/powder/fingerprints')).data
export const getPowderStatus = async () => (await api.get('/powder/status')).data
export const startPowderProbe = async payload => (await api.post('/powder/probe/start', withWindowPositionOffset(payload))).data
export const startRateSearch = async payload => (await api.post('/powder/rate-search/start', payload)).data
export const applyPowderFingerprint = async id => (await api.post(`/powder/fingerprints/${encodeURIComponent(id)}/apply`, {})).data
export const deletePowderFingerprint = async id => (await api.post(`/powder/fingerprints/${encodeURIComponent(id)}`, {})).data
export const setPowderCategory = async category => (await api.post('/powder/category', { category })).data
export const getGridTemplates = async () => (await api.get('/experiment/grid/templates')).data
export const startGridExperiment = async payload => (await api.post('/experiment/grid/start', withWindowPositionOffset(payload))).data
export const collectGridExperiment = async payload => (await api.post('/experiment/grid/collect', payload)).data

export const getDispensePowders = async () => (await api.get('/dispense/powders')).data
export const getDispenseConfig = async (powderId, targetMg) => (await api.get('/dispense/config', { params: { powder_id: powderId, target_mg: targetMg } })).data
export const getControlProfiles = async () => (await api.get('/control-profiles')).data

export function errorMessage(error) {
  return error?.response?.data?.error || error?.message || '请求失败'
}

export default api

