<template>
  <el-card class="panel-section" shadow="never">
    <template #header>
      <div class="panel-header">
        <span class="panel-title">{{ title }}</span>
        <div class="panel-header-actions">
          <slot name="header-actions" />
        </div>
      </div>
    </template>
    <slot />
  </el-card>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
})
</script>

<style scoped>
.panel-section {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  margin-bottom: 0;
}

.panel-section :deep(.el-card__header) {
  padding: 14px 20px;
  border-bottom: 1px solid #ebeef5;
  background: #fff;
}

.panel-section :deep(.el-card__body) {
  padding: 20px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  position: relative;
  padding-left: 12px;
}

.panel-title::before {
  content: '';
  position: absolute;
  left: 0;
  top: 2px;
  bottom: 2px;
  width: 3px;
  background: #409eff;
  border-radius: 2px;
}

.panel-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
