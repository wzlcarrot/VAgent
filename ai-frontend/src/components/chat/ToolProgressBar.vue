<template>
  <div v-if="tools.length" class="tool-progress-bar">
    <div
      v-for="(tool, index) in tools"
      :key="`${tool.name}-${index}`"
      class="tool-item"
      :class="tool.status"
    >
      <span class="tool-dot" />
      <span class="tool-label">{{ tool.label }}</span>
      <span v-if="tool.status === 'running'" class="tool-state">执行中</span>
      <span v-else-if="tool.status === 'done'" class="tool-state ok">
        完成<span v-if="tool.durationMs"> · {{ tool.durationMs }}ms</span>
      </span>
      <span v-else class="tool-state fail">失败</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ToolBlock } from '@/composables/useToolProgress'

defineProps<{
  tools: ToolBlock[]
}>()
</script>

<style scoped>
.tool-progress-bar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: var(--space-sm);
  padding: 8px 12px;
  border: 1px dashed var(--color-border);
  border-radius: 8px;
  background: rgba(74, 108, 247, 0.04);
}

.tool-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.tool-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-border);
}

.tool-item.running .tool-dot {
  background: var(--color-primary);
  animation: pulse 1s ease-in-out infinite;
}

.tool-item.done .tool-dot {
  background: #22c55e;
}

.tool-item.failed .tool-dot {
  background: #ef4444;
}

.tool-label {
  flex: 1;
  color: var(--color-text);
}

.tool-state.ok {
  color: #16a34a;
}

.tool-state.fail {
  color: #dc2626;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
