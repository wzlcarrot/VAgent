import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSettingsStore } from '@/stores/settings'

describe('settings store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    document.documentElement.className = ''
    document.documentElement.removeAttribute('data-font-size')
  })

  it('setTheme light/dark/auto', () => {
    const store = useSettingsStore()
    store.setTheme('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    store.setTheme('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (q: string) => ({
        matches: q.includes('dark'),
        media: q,
        addEventListener: () => {},
        removeEventListener: () => {},
      }),
    })
    store.setTheme('auto')
    expect(store.theme).toBe('auto')
  })

  it('setFontSize writes data attribute', () => {
    const store = useSettingsStore()
    store.setFontSize('large')
    expect(document.documentElement.getAttribute('data-font-size')).toBe('large')
  })
})
