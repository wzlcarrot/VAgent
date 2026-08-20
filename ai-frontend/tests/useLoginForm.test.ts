import { describe, expect, it } from 'vitest'
import { isValidEmail, useLoginForm } from '@/composables/useLoginForm'

describe('useLoginForm', () => {
  it('rejects empty email', () => {
    const form = useLoginForm()
    expect(form.applyValidationError()).toBe(false)
    expect(form.emailError.value).toBe('请输入邮箱')
  })

  it('rejects invalid email', () => {
    const form = useLoginForm()
    form.loginForm.email = 'not-an-email'
    form.loginForm.password = '123456'
    expect(form.applyValidationError()).toBe(false)
    expect(form.emailError.value).toBe('邮箱格式不正确')
  })

  it('rejects empty password', () => {
    const form = useLoginForm()
    form.loginForm.email = 'a@b.com'
    form.loginForm.password = ''
    expect(form.applyValidationError()).toBe(false)
    expect(form.passwordError.value).toBe('请输入密码')
  })

  it('rejects short password', () => {
    const form = useLoginForm()
    form.loginForm.email = 'a@b.com'
    form.loginForm.password = '123'
    expect(form.applyValidationError()).toBe(false)
    expect(form.passwordError.value).toBe('密码至少 6 位')
  })

  it('accepts valid credentials', () => {
    const form = useLoginForm()
    form.loginForm.email = 'a@b.com'
    form.loginForm.password = '123456'
    expect(form.applyValidationError()).toBe(true)
    expect(form.emailError.value).toBe('')
    expect(form.passwordError.value).toBe('')
  })

  it('records auth failure', () => {
    const form = useLoginForm()
    form.isLoginSuccess.value = true
    form.applyAuthFailure('账号或密码错误')
    expect(form.errorMessage.value).toBe('账号或密码错误')
    expect(form.isLoginSuccess.value).toBe(false)
  })

  it('isValidEmail', () => {
    expect(isValidEmail('a@b.com')).toBe(true)
    expect(isValidEmail('nope')).toBe(false)
  })
})
