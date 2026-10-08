<template>
  <div class="monitor-view">
    <div class="view-grid-2col">
      <BalancePanel />
      <ActuatorPanel />
    </div>
    <FeedRealtimePanel style="margin-top: 16px" />
  </div>
</template>

<script setup>
import BalancePanel from '../components/BalancePanel.vue'
import ActuatorPanel from '../components/ActuatorPanel.vue'
import FeedRealtimePanel from '../components/FeedRealtimePanel.vue'
</script>

<style scoped>
.view-grid-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 1200px) {
  .view-grid-2col {
    grid-template-columns: 1fr;
  }
}
</style>
