<template>
  <div class="quick-actions" v-if="visible">
    <div class="actions-header">
      <span class="hint-text">{{ headerText }}</span>
    </div>
    <div class="actions-grid" :class="{ 'video-mode': !!currentVideoId }">
      <button
        v-for="action in actions"
        :key="action.key"
        class="action-btn"
        @click="$emit('select', action.prompt)"
      >
        <span class="action-icon">{{ action.icon }}</span>
        <span class="action-text">{{ action.label }}</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  visible?: boolean
  /** 播放页 URL 带入的 video_id，有值时展示当前视频问答快捷入口 */
  currentVideoId?: string
}>(), {
  visible: true,
  currentVideoId: '',
})

defineEmits<{
  select: [prompt: string]
}>()

const headerText = computed(() =>
  props.currentVideoId
    ? '当前视频已带入上下文，试试视频问答 👇'
    : '快捷操作 👇',
)

const defaultActions = [
  { key: 'recommend', icon: '🎬', label: '视频推荐', prompt: '推荐一些适合我的视频' },
  { key: 'intro', icon: '🌐', label: '网站介绍', prompt: '这个网站有哪些特色功能？' },
  { key: 'help', icon: '❓', label: '使用帮助', prompt: '这个平台怎么使用？' },
]

const videoActions = [
  { key: 'video-qa', icon: '📺', label: '视频讲了什么', prompt: '这个视频讲了什么' },
  { key: 'similar', icon: '🎯', label: '推荐类似', prompt: '推荐和当前视频类似的视频' },
  { key: 'help', icon: '❓', label: '使用帮助', prompt: '这个平台怎么使用？' },
]

const actions = computed(() => (props.currentVideoId ? videoActions : defaultActions))
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

.actions-grid.video-mode {
  grid-template-columns: repeat(3, 1fr);
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
