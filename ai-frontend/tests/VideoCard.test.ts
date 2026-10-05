/**
 * VideoCard 组件测试 - 渲染、navigate、disabled、封面兜底
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

  it('渲染推荐序号、标题和简介', () => {
    wrapper = mount(VideoCard, { props: { video, index: 1, reason: '用三个例子讲变量。' } })
    expect(wrapper.find('.title').text()).toBe('推荐 1：机器学习入门')
    expect(wrapper.find('.reason').text()).toBe('用三个例子讲变量。')
    expect(wrapper.find('.author').exists()).toBe(false)
  })

  it('观看名单不使用「推荐」前缀', () => {
    wrapper = mount(VideoCard, { props: { video, index: 1, heading: '' } })
    expect(wrapper.find('.title').text()).toBe('1：机器学习入门')
  })

  it('无 cover 时用标题生成封面，不显示「无封面」', () => {
    wrapper = mount(VideoCard, { props: { video: { ...video, cover: '' } } })
    const img = wrapper.find('img').element as HTMLImageElement
    expect(img.src).toContain('data:image/svg')
    expect(wrapper.text()).not.toContain('无封面')
  })

  it('点击卡片触发 navigate', async () => {
    wrapper = mount(VideoCard, { props: { video, videoUrl: 'http://localhost:3000/video/v1' } })
    await wrapper.find('.video-card').trigger('click')
    expect(wrapper.emitted('navigate')).toBeTruthy()
    expect(wrapper.emitted('navigate')![0][0]).toEqual(video)
  })

  it('disabled 时不渲染链接', () => {
    wrapper = mount(VideoCard, { props: { video, disabled: true } })
    expect(wrapper.find('.video-card--disabled').exists()).toBe(true)
    expect(wrapper.find('a.video-card').exists()).toBe(false)
  })

  it('图片加载失败回退默认封面', async () => {
    wrapper = mount(VideoCard, { props: { video: { ...video, cover: 'http://broken/x.jpg' } } })
    const img = wrapper.find('img')
    await img.trigger('error')
    expect((img.element as HTMLImageElement).src).toContain('data:image/svg')
  })
})
