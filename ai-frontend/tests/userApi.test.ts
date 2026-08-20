import { afterEach, describe, expect, it, vi } from 'vitest'
import { login, logout, register } from '@/api/user'

describe('user api', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('login maps counts and succeeds', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        user: {
          userId: 'u1',
          nickname: 'n',
          avatar: '',
          token: 't',
          tokenExpiresAt: 1,
        },
      }),
    }))
    const r = await login({ email: 'a@b.com', password: '123456' })
    expect(r.user.userId).toBe('u1')
    expect(r.user.fansCount).toBe(0)
  })

  it('login throws backend detail', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: '邮箱或密码错误' }),
    }))
    await expect(login({ email: 'a@b.com', password: 'x' })).rejects.toThrow('邮箱或密码错误')
  })

  it('register is unimplemented', async () => {
    await expect(register({
      email: 'a@b.com',
      nickName: 'n',
      registerPassword: 'p',
      checkCodeKey: 'k',
      checkCode: 'c',
    })).rejects.toThrow('注册功能未实现')
  })

  it('logout swallows network errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    await expect(logout()).resolves.toBeUndefined()
  })
})
