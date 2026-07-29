<template>
  <a
    v-if="!disabled"
    :href="videoUrl"
    target="_blank"
    rel="noopener noreferrer"
    class="video-card"
  >
    <div class="video-cover">
      <img :src="video.cover || defaultCover" :alt="video.title" loading="lazy" @error="onImgError($event)" />
      <span class="duration" v-if="video.duration">{{ video.duration }}</span>
      <div class="scan-line"></div>
    </div>
    <div class="video-info">
      <h4 class="title">{{ video.title }}</h4>
      <div class="meta">
        <span class="author" v-if="video.author">{{ video.author }}</span>
        <span class="views" v-if="video.views">{{ video.views }}播放</span>
      </div>
      <p class="reason" v-if="reason">{{ reason }}</p>
    </div>
    <div class="actions" @click.stop>
      <button class="action-btn play-btn" title="播放" aria-label="播放" @click="handlePlay">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
          <polygon points="5 3 19 12 5 21 5 3"></polygon>
        </svg>
      </button>
      <button class="action-btn collect-btn" title="收藏" aria-label="收藏">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path>
        </svg>
      </button>
      <button class="action-btn like-btn" title="点赞" aria-label="点赞">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"></path>
        </svg>
      </button>
    </div>
  </a>
  <div v-else class="video-card video-card--disabled">
    <div class="video-cover">
      <img :src="video.cover || defaultCover" :alt="video.title" loading="lazy" @error="onImgError($event)" />
      <span class="duration" v-if="video.duration">{{ video.duration }}</span>
    </div>
    <div class="video-info">
      <h4 class="title">{{ video.title }}</h4>
      <div class="meta">
        <span class="author" v-if="video.author">{{ video.author }}</span>
        <span class="views" v-if="video.views">{{ video.views }}播放</span>
      </div>
      <p class="reason" v-if="reason">{{ reason }}</p>
    </div>
    <div class="actions">
      <button class="action-btn play-btn" title="播放" aria-label="播放" disabled>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
          <polygon points="5 3 19 12 5 21 5 3"></polygon>
        </svg>
      </button>
      <button class="action-btn collect-btn" title="收藏" aria-label="收藏" disabled>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path>
        </svg>
      </button>
      <button class="action-btn like-btn" title="点赞" aria-label="点赞" disabled>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"></path>
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
export interface VideoInfo {
  videoId: string
  title: string
  cover?: string
  author?: string
  duration?: string
  views?: string
}

const defaultCover = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 320 180"%3E%3Crect fill="%230a0a1a" width="320" height="180"/%3E%3Ctext fill="%234a6cf7" font-family="Arial" font-size="14" x="50%25" y="50%25" text-anchor="middle" dy=".3em"%3E%E6%97%A0%E5%9B%BE%E7%89%87%3C/text%3E%3C/svg%3E'

const props = defineProps<{
  video: VideoInfo
  reason?: string
  videoUrl?: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  play: [video: VideoInfo]
}>()

function onImgError(e: Event) {
  const img = e.target as HTMLImageElement
  if (img) img.src = defaultCover
}

function handlePlay(e: Event) {
  e.stopPropagation()
  if (!props.disabled) {
    emit('play', props.video)
  }
}
</script>

<style scoped>
.video-card {
  display: flex;
  gap: var(--space-md);
  padding: var(--space-md);
  background: linear-gradient(135deg, rgba(10, 10, 26, 0.95), rgba(22, 33, 62, 0.95));
  border: 1px solid rgba(74, 108, 247, 0.3);
  border-radius: var(--radius-card);
  cursor: pointer;
  transition: all 0.3s ease;
  text-decoration: none;
  color: inherit;
  position: relative;
  overflow: hidden;
}

.video-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(74, 108, 247, 0.15), transparent);
  transition: left 0.6s ease;
}

.video-card:hover {
  transform: translateY(-3px);
  border-color: rgba(74, 108, 247, 0.8);
  box-shadow:
    0 0 15px rgba(74, 108, 247, 0.4),
    0 0 30px rgba(74, 108, 247, 0.2),
    inset 0 0 15px rgba(74, 108, 247, 0.1);
}

.video-card:hover::before {
  left: 100%;
}

.video-card--disabled {
  opacity: 0.6;
  cursor: not-allowed;
  filter: grayscale(30%);
}

.video-card--disabled:hover {
  transform: none;
  border-color: rgba(74, 108, 247, 0.3);
  box-shadow: none;
}

.video-card--disabled::before {
  display: none;
}

.video-cover {
  position: relative;
  width: 120px;
  height: 68px;
  border-radius: var(--radius-btn);
  overflow: hidden;
  flex-shrink: 0;
  border: 1px solid rgba(74, 108, 247, 0.2);
}

.video-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s ease;
}

.video-card:hover .video-cover img {
  transform: scale(1.05);
}

.duration {
  position: absolute;
  bottom: 4px;
  right: 4px;
  background: rgba(0, 0, 0, 0.8);
  color: #00d9ff;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
  border: 1px solid rgba(0, 217, 255, 0.3);
}

.scan-line {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 2px;
  background: linear-gradient(90deg, transparent, #4a6cf7, transparent);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.video-card:hover .scan-line {
  opacity: 1;
  animation: scan 2s linear infinite;
}

@keyframes scan {
  0% { top: 0; }
  100% { top: 100%; }
}

.video-info {
  flex: 1;
  min-width: 0;
}

.title {
  font-size: 14px;
  font-weight: 500;
  margin-bottom: var(--space-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #e0e0ff;
  text-shadow: 0 0 8px rgba(74, 108, 247, 0.3);
}

.meta {
  display: flex;
  gap: var(--space-sm);
  font-size: 12px;
  color: #8888aa;
  margin-bottom: var(--space-xs);
}

.reason {
  font-size: 12px;
  color: #6a6a8a;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-orient: vertical;
  overflow: hidden;
}

.actions {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}

.action-btn {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-btn);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6a6a8a;
  transition: all 0.2s ease;
  background: rgba(74, 108, 247, 0.1);
  border: 1px solid rgba(74, 108, 247, 0.2);
}

.action-btn:hover:not(:disabled) {
  background: rgba(74, 108, 247, 0.3);
  color: #4a6cf7;
  box-shadow: 0 0 10px rgba(74, 108, 247, 0.4);
}

.action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.play-btn:hover:not(:disabled) {
  color: #00d9ff;
  border-color: rgba(0, 217, 255, 0.5);
  box-shadow: 0 0 10px rgba(0, 217, 255, 0.4);
}
</style>
