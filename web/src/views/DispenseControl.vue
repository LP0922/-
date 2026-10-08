<template>
  <div class="dispense-view">
    <FeedbackDispensePanel />
    <ConstantRatePanel />
  </div>
</template>

<script setup>
import FeedbackDispensePanel from '../components/FeedbackDispensePanel.vue'
import ConstantRatePanel from '../components/ConstantRatePanel.vue'
</script>

<style scoped>
.dispense-view { display: grid; gap: 20px; min-width: 0; }
</style>
