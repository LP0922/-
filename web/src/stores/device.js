import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getSnapshot } from '../api/index.js'

export const useDeviceStore = defineStore('device', () => {
  const snapshot = ref({
    timestamp_utc: null,
    at8811c: { online: false, error: '等待首次采样' },
    la10: { online: false, error: '等待首次采样' },
    test: { status: 'idle' },
  })

  const balance = computed(() => snapshot.value.at8811c)
  const actuator = computed(() => snapshot.value.la10)
  const testState = computed(() => snapshot.value.test)
  const isRunning = computed(() => testState.value.status === 'running')

  const snapshotError = ref('')
  let pollTimer = null
  let pendingSnapshot = null

  function fetchSnapshot() {
    // Share an in-flight request so slow responses cannot overwrite newer data.
    if (pendingSnapshot) return pendingSnapshot
    pendingSnapshot = getSnapshot()
      .then(data => {
        snapshot.value = data
        snapshotError.value = ''
      })
      .catch(() => {
        // Keep task state for stop controls, but do not present stale balance data as live.
        snapshotError.value = '无法获取最新设备状态'
      })
      .finally(() => { pendingSnapshot = null })
    return pendingSnapshot
  }

  function startPolling(intervalMs = 200) {
    stopPolling()
    fetchSnapshot()
    pollTimer = setInterval(fetchSnapshot, intervalMs)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  const la10WritableRegisters = new Set([0, 1, 2, 3, 4, 12, 13, 14])

  return {
    snapshot,
    snapshotError,
    balance,
    actuator,
    testState,
    isRunning,
    la10WritableRegisters,
    fetchSnapshot,
    startPolling,
    stopPolling,
  }
})
