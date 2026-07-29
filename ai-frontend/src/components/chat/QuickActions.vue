<template>
  <div class="quick-actions" v-if="visible">
    <div class="actions-header">
      <span class="hint-text">快捷操作 👇</span>
    </div>
    <div class="actions-grid">
      <button
        class="action-btn"
        @click="$emit('select', '推荐一些适合我的视频')"
      >
        <span class="action-icon">🎬</span>
        <span class="action-text">视频推荐</span>
      </button>
      <button
        class="action-btn"
        @click="$emit('select', '这个网站有哪些特色功能？')"
      >
        <span class="action-icon">🌐</span>
        <span class="action-text">网站介绍</span>
      </button>
      <button
        class="action-btn"
        @click="$emit('select', '这个平台怎么使用？')"
      >
        <span class="action-icon">❓</span>
        <span class="action-text">使用帮助</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  visible?: boolean
}>(), {
  visible: true,
})

defineEmits<{
  select: [prompt: string]
}>()
</script>

<style scoped>
.quick-actions {
  width: 100%;
  max-width: 500px;
  padding: var(--space-md);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
}

.actions-header {
  margin-bottom: var(--space-sm);
}

.hint-text {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.actions-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-sm);
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-btn);
  cursor: pointer;
  transition: all 0.3s ease;
}

.action-btn:hover {
  background: var(--color-primary);
  color: white;
  border-color: var(--color-primary);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.action-icon {
  font-size: 16px;
}

.action-text {
  font-size: 13px;
  font-weight: 500;
}

@media (max-width: 768px) {
  .actions-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
