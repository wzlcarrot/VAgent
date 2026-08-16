/**
 * VideoCard 组件测试 - 渲染、play 事件、disabled 状态、封面兜底
 */
import { describe, it, expect, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import VideoCard from '@/components/video/VideoCard.vue'

const video = {
  videoId: 'v1',
  title: '机器学习入门',
  cover: '/ai/media/cover?sourceName=cover/a.jpg',
  author: '老王',
  views: '1.2万',
}

describe('VideoCard', () => {
  let wrapper: ReturnType<typeof mount>

  afterEach(() => {
    wrapper?.unmount()
  })

  it('渲染标题、作者、播放量', () => {
    wrapper = mount(VideoCard, { props: { video } })
    expect(wrapper.find('.title').text()).toBe('机器学习入门')
    expect(wrapper.find('.author').text()).toBe('老王')
    expect(wrapper.find('.views').text()).toBe('1.2万播放')
  })

  it('无 cover 时使用默认封面', () => {
    wrapper = mount(VideoCard, { props: { video: { ...video, cover: '' } } })
    const img = wrapper.find('img').element as HTMLImageElement
    expect(img.src).toContain('data:image/svg')
  })

  it('渲染 reason 文案', () => {
    wrapper = mount(VideoCard, { props: { video, reason: '与你的偏好匹配' } })
    expect(wrapper.find('.reason').text()).toBe('与你的偏好匹配')
  })

  it('点击播放按钮触发 play 事件并携带 video', async () => {
    wrapper = mount(VideoCard, { props: { video } })
    await wrapper.find('.play-btn').trigger('click')
    expect(wrapper.emitted('play')).toBeTruthy()
    expect(wrapper.emitted('play')![0][0]).toEqual(video)
  })

  it('disabled 时按钮禁用且点击不触发 play', async () => {
    wrapper = mount(VideoCard, { props: { video, disabled: true } })
    expect(wrapper.find('.video-card--disabled').exists()).toBe(true)
    const btn = wrapper.find('.play-btn')
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
    await btn.trigger('click')
    expect(wrapper.emitted('play')).toBeFalsy()
  })

  it('图片加载失败回退默认封面', async () => {
    wrapper = mount(VideoCard, { props: { video: { ...video, cover: 'http://broken/x.jpg' } } })
    const img = wrapper.find('img')
    await img.trigger('error')
    expect((img.element as HTMLImageElement).src).toContain('data:image/svg')
  })
})
