import { defineStore } from 'pinia'
import { ref } from 'vue'

export type Theme = 'light' | 'dark' | 'auto'
export type FontSize = 'small' | 'medium' | 'large'

export const useSettingsStore = defineStore('settings', () => {
  const theme = ref<Theme>('light')
  const fontSize = ref<FontSize>('medium')

  function setTheme(newTheme: Theme) {
    theme.value = newTheme
    applyTheme(newTheme)
  }

  function setFontSize(newSize: FontSize) {
    fontSize.value = newSize
    applyFontSize(newSize)
  }

  function applyTheme(t: Theme) {
    const root = document.documentElement
    if (t === 'dark') {
      root.classList.add('dark')
    } else if (t === 'light') {
      root.classList.remove('dark')
    } else {
      if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
        root.classList.add('dark')
      } else {
        root.classList.remove('dark')
      }
    }
  }

  function applyFontSize(size: FontSize) {
    const root = document.documentElement
    root.setAttribute('data-font-size', size)
  }

  return {
    theme,
    fontSize,
    setTheme,
    setFontSize,
    applyTheme,
    applyFontSize,
  }
})
