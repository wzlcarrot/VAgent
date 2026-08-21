import { describe, expect, it } from 'vitest'
import { normalizeVideos, resolveVideoId } from '@/utils/videos'

describe('normalizeVideos', () => {
  it('后端实时流 snake_case（video_id）归一化为 camelCase', () => {
    const out = normalizeVideos([
      { video_id: 'v1', title: '一号', cover: 'c1', author: 'up主A', tags: 'AI,算法' },
      { video_id: 'v2', title: '二号', cover: '', author: 'up主B', tags: '科普' },
    ])
    expect(out[0].videoId).toBe('v1')
    expect(out[0].title).toBe('一号')
    expect(out[0].cover).toBe('c1')
    expect(out[0].author).toBe('up主A')
    expect(out[1].videoId).toBe('v2')
  })

  it('camelCase 输入保持不变（历史/前端已归一化）', () => {
    const out = normalizeVideos([{ videoId: 'v9', title: '九号' }])
    expect(out[0].videoId).toBe('v9')
  })

  it('mixed 字段优先取 videoId', () => {
    const out = normalizeVideos([{ video_id: 'old', videoId: 'new' }])
    expect(out[0].videoId).toBe('new')
  })

  it('非数组返回空数组', () => {
    expect(normalizeVideos(null)).toEqual([])
    expect(normalizeVideos(undefined)).toEqual([])
    expect(normalizeVideos({})).toEqual([])
  })

  it('videoId 缺失时兜底为空字符串，避免 /video/undefined', () => {
    const out = normalizeVideos([{ title: '无ID' }])
    expect(out[0].videoId).toBe('')
  })

  it('tags 逗号字符串归一化为数组', () => {
    const out = normalizeVideos([{ video_id: 'v1', tags: 'AI, 算法 , 科普' }])
    expect(out[0].tags).toEqual(['AI', '算法', '科普'])
  })

  it('tags 已是数组则原样保留并转字符串', () => {
    const out = normalizeVideos([{ video_id: 'v2', tags: ['AI', '算法'] }])
    expect(out[0].tags).toEqual(['AI', '算法'])
  })

  it('tags 缺失/空兜底为空数组', () => {
    expect(normalizeVideos([{ video_id: 'v3' }])[0].tags).toEqual([])
    expect(normalizeVideos([{ video_id: 'v4', tags: '' }])[0].tags).toEqual([])
  })
})

describe('resolveVideoId', () => {
  it('问题里贴了 ID 时优先用问题里的', () => {
    expect(resolveVideoId('id:abcd1234 这个视频讲了什么', 'urlvid99')).toBe('abcd1234')
    expect(resolveVideoId('video_id: efgh5678 是什么', 'urlvid99')).toBe('efgh5678')
  })

  it('问题里没有 ID 时用 URL 带入的当前视频', () => {
    expect(resolveVideoId('这个视频讲了什么', 'urlvid99')).toBe('urlvid99')
    expect(resolveVideoId('讲解一下', 'urlvid99')).toBe('urlvid99')
  })

  it('两者都没有时返回 undefined', () => {
    expect(resolveVideoId('这个视频讲了什么', undefined)).toBeUndefined()
    expect(resolveVideoId('这个视频讲了什么', null)).toBeUndefined()
    expect(resolveVideoId('你好', '')).toBeUndefined()
  })

  it('太短的 ID 不认（防止误匹配普通词）', () => {
    expect(resolveVideoId('id:ab 这个视频', 'urlvid99')).toBe('urlvid99')
  })

  it('「视频 + 年份数字」不误抽成 ID（正则收紧回归）', () => {
    expect(resolveVideoId('这个视频 2024年出的', 'urlvid99')).toBe('urlvid99')
    expect(resolveVideoId('视频 2024 年很火', 'urlvid99')).toBe('urlvid99')
  })

  it('「视频id:」形式仍能识别', () => {
    expect(resolveVideoId('视频id: zzzz1111', 'urlvid99')).toBe('zzzz1111')
    expect(resolveVideoId('视频 id: zzzz1111 是什么', 'urlvid99')).toBe('zzzz1111')
  })
})
