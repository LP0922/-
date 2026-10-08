import { ref } from 'vue'

const batchQueue = ref([])
const autoTareBetweenGroups = ref(true)
const closeWindowBetweenRuns = ref(false)
let nextId = 1

export function useBatchQueue() {
  function addToQueue(item) {
    batchQueue.value.push({
      id: nextId++,
      ...item,
    })
  }

  function removeFromQueue(id) {
    const idx = batchQueue.value.findIndex((q) => q.id === id)
    if (idx !== -1) {
      batchQueue.value.splice(idx, 1)
    }
  }

  function clearQueue() {
    batchQueue.value.length = 0
  }

  return {
    batchQueue,
    autoTareBetweenGroups,
    closeWindowBetweenRuns,
    addToQueue,
    removeFromQueue,
    clearQueue,
  }
}
