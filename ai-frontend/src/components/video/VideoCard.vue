<template>
  <a
    v-if="!disabled"
    :href="videoUrl"
    target="_blank"
    rel="noopener noreferrer"
    class="video-card"
    @click="onCardNavigate"
  >
    <h4 class="title">{{ titleText }}</h4>
    <p class="reason" v-if="reason">{{ reason }}</p>
    <div class="video-cover">
      <img :src="coverSrc" :alt="video.title" loading="lazy" @error="onImgError($event)" />
      <span class="play-overlay" aria-hidden="true">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="white">
          <polygon points="8 5 19 12 8 19 8 5"></polygon>
        </svg>
      </span>
    </div>
  </a>
  <div v-else class="video-card video-card--disabled">
    <h4 class="title">{{ titleText }}</h4>
    <p class="reason" v-if="reason">{{ reason }}</p>
    <div class="video-cover">
      <img :src="coverSrc" :alt="video.title" loading="lazy" @error="onImgError($event)" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

export interface VideoInfo {
  videoId: string
  title: string
  cover?: string
  author?: string
  duration?: string
  views?: string
}

const palettes = [
  ['#1b2838', '#66c0f4'],
  ['#2d1b4e', '#c77dff'],
  ['#1a3a2a', '#7dcea0'],
  ['#3d1f1f', '#e07a5f'],
  ['#1a2744', '#5b8def'],
]

function escapeXml(s: string): string {
  return s.replace(/[&<>"']/g, (ch) => (
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' } as Record<string, string>)[ch] || ch
  ))
}

function posterFromTitle(title: string): string {
  let h = 0
  for (let i = 0; i < title.length; i++) h = (h * 33 + title.charCodeAt(i)) >>> 0
  const [c1, c2] = palettes[h % palettes.length]
  const line = escapeXml((title || '视频').slice(0, 16))
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="160" height="214" viewBox="0 0 160 214">
    <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${c1}"/><stop offset="1" stop-color="${c2}"/></linearGradient></defs>
    <rect width="160" height="214" rx="12" fill="url(#g)"/>
    <circle cx="80" cy="88" r="22" fill="rgba(255,255,255,0.22)"/>
    <polygon points="74,76 74,100 98,88" fill="#fff"/>
    <text x="80" y="148" text-anchor="middle" fill="#fff" font-size="13" font-family="sans-serif" font-weight="600">${line}</text>
  </svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

const props = withDefaults(defineProps<{
  video: VideoInfo
  reason?: string
  videoUrl?: string
  disabled?: boolean
  index?: number
  heading?: string
}>(), {
  index: 1,
  heading: '推荐',
})

const titleText = computed(() => {
  const name = props.video.title || ''
  const prefix = (props.heading || '').trim()
  return prefix ? `${prefix} ${props.index}：${name}` : `${props.index}：${name}`
})

const emit = defineEmits<{
  play: [video: VideoInfo]
  navigate: [video: VideoInfo]
}>()

const coverSrc = computed(() => (props.video.cover && props.video.cover.trim()) || posterFromTitle(props.video.title || '视频'))

function onImgError(e: Event) {
  const img = e.target as HTMLImageElement
  if (img) img.src = posterFromTitle(props.video.title || '视频')
}

function onCardNavigate() {
  emit('navigate', props.video)
}
</script>

<style scoped>
.video-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  padding: 4px 0 20px;
  text-decoration: none;
  color: inherit;
  max-width: 560px;
}

.video-card--disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.title {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
  line-height: 1.45;
  color: var(--color-text);
}

.reason {
  margin: 0;
  font-size: 14px;
  line-height: 1.65;
  color: var(--color-text-secondary);
}

.video-cover {
  position: relative;
  width: 148px;
  height: 198px;
  border-radius: 12px;
  overflow: hidden;
  flex-shrink: 0;
  background: #222;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.12);
}

.video-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.play-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.18);
}

.video-card:hover .play-overlay {
  background: rgba(0, 0, 0, 0.28);
}
</style>
