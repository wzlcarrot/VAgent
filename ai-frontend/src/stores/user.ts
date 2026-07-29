import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface User {
  userId: string
  nickname: string
  avatar: string
  token: string
  tokenExpiresAt: number
  fansCount: number
  currentCoinCount: number
  focusCount: number
}

export const useUserStore = defineStore('user', () => {
  const user = ref<User | null>(null)

  const isLoggedIn = computed(() => !!user.value)

  const nickname = computed(() => user.value?.nickname ?? '')
  const avatar = computed(() => user.value?.avatar ?? '')
  const userId = computed(() => user.value?.userId ?? '')

  function setUser(userData: User) {
    userData.fansCount = Number(userData.fansCount) || 0
    userData.currentCoinCount = Number(userData.currentCoinCount) || 0
    userData.focusCount = Number(userData.focusCount) || 0
    user.value = userData
    try {
      localStorage.setItem('user', JSON.stringify(userData))
    } catch {
      /* localStorage 满或不可用，静默失败 */
    }
  }

  function logout() {
    user.value = null
    try {
      localStorage.removeItem('user')
    } catch {
      /* 静默 */
    }
  }

  function initFromStorage() {
    const storedUser = localStorage.getItem('user')
    if (storedUser) {
      try {
        const parsed = JSON.parse(storedUser) as User
        // tokenExpiresAt 单位是秒（不是毫秒），所以比较时需要 * 1000
        if (parsed.tokenExpiresAt && parsed.tokenExpiresAt * 1000 < Date.now()) {
          localStorage.removeItem('user')
          return
        }
        parsed.fansCount = Number(parsed.fansCount) || 0
        parsed.currentCoinCount = Number(parsed.currentCoinCount) || 0
        parsed.focusCount = Number(parsed.focusCount) || 0
        user.value = parsed
      } catch {
        localStorage.removeItem('user')
      }
    }
  }

  return {
    user,
    isLoggedIn,
    nickname,
    avatar,
    userId,
    setUser,
    logout,
    initFromStorage,
  }
})
