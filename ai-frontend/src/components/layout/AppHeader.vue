<template>
  <header class="header">
    <div class="header-left">
      <div class="logo" @click="$router.push('/')">
        <span class="logo-icon">🎬</span>
        <span class="logo-text">ViewHub AI</span>
      </div>
    </div>
    <div class="header-right">
      <div class="user-menu" v-if="userStore.isLoggedIn" @click="showUserMenu = !showUserMenu">
        <img :src="userStore.user?.avatar || '/default-avatar.png'" alt="avatar" class="avatar" />
        <span class="username">{{ userStore.user?.nickname }}</span>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
        
        <Transition name="dropdown">
          <div v-if="showUserMenu" class="dropdown-menu" @click.stop>
            <button class="dropdown-item" @click="$router.push('/history'); showUserMenu = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <polyline points="12 6 12 12 16 14"></polyline>
              </svg>
              历史记录
            </button>
            <button class="dropdown-item logout" @click="handleLogout">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                <polyline points="16 17 21 12 16 7"></polyline>
                <line x1="21" y1="12" x2="9" y2="12"></line>
              </svg>
              退出登录
            </button>
          </div>
        </Transition>
      </div>
      <button v-else class="login-btn" @click="$router.push('/login')">
        登录
      </button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useChatStore } from '@/stores/chat'

const router = useRouter()
const userStore = useUserStore()
const chatStore = useChatStore()
const showUserMenu = ref(false)

async function handleLogout() {
  const { logout: apiLogout } = await import('@/api/user')
  await apiLogout()  // 清 httpOnly cookie
  userStore.logout()
  chatStore.reset()  // 清空会话状态，避免新用户看到旧用户历史
  showUserMenu.value = false
  router.push('/login')
}

function handleClickOutside(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (!target.closest('.user-menu')) {
    showUserMenu.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<style scoped>
.header {
  height: var(--header-height);
  background: var(--color-bg-card);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-md);
}

.header-left {
  display: flex;
  align-items: center;
}

.logo {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  cursor: pointer;
  transition: opacity 0.3s;
}

.logo:hover {
  opacity: 0.8;
}

.logo-icon {
  font-size: 24px;
}

.logo-text {
  font-size: 18px;
  font-weight: 600;
  background: linear-gradient(135deg, var(--color-primary), var(--color-secondary));
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.icon-btn {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-btn);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-secondary);
  transition: all var(--transition-fast);
}

.icon-btn:hover {
  background: var(--color-bg);
  color: var(--color-text);
}

.user-menu {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-xs) var(--space-sm);
  border-radius: var(--radius-btn);
  cursor: pointer;
  position: relative;
  transition: background 0.3s;
}

.user-menu:hover {
  background: var(--color-bg);
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  object-fit: cover;
}

.username {
  font-size: 14px;
  color: var(--color-text);
}

.dropdown-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  width: 180px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15);
  padding: var(--space-xs);
  z-index: 100;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  width: 100%;
  padding: var(--space-sm) var(--space-md);
  background: none;
  border: none;
  border-radius: var(--radius-btn);
  font-size: 14px;
  color: var(--color-text);
  cursor: pointer;
  transition: all 0.3s;
}

.dropdown-item:hover {
  background: var(--color-bg);
}

.dropdown-item.logout {
  color: var(--color-danger);
}

.dropdown-item.logout:hover {
  background: var(--color-danger-bg);
}

.dropdown-divider {
  height: 1px;
  background: var(--color-border);
  margin: var(--space-xs) 0;
}

.login-btn {
  padding: var(--space-xs) var(--space-md);
  background: var(--color-primary);
  color: white;
  border: none;
  border-radius: var(--radius-btn);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s;
}

.login-btn:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}

.dropdown-enter-active,
.dropdown-leave-active {
  transition: all 0.2s ease;
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
