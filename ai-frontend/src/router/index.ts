import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '@/views/HomeView.vue'
import { useUserStore } from '@/stores/user'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView,
      meta: { requiresAuth: true },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
    },
    {
      path: '/history',
      name: 'history',
      component: () => import('@/views/HistoryView.vue'),
      meta: { requiresAuth: true },
    },
  ],
})

router.beforeEach((to, _from, next) => {
  const userStore = useUserStore()
  userStore.initFromStorage()

  if (to.meta.requiresAuth && !userStore.isLoggedIn) {
    next({ name: 'login' })
  } else if (to.name === 'login' && userStore.isLoggedIn) {
    next({ name: 'home' })
  } else {
    next()
  }
})

export default router
