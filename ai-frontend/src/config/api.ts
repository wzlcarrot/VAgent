export const apiConfig = {
  python: {
    baseUrl: import.meta.env.VITE_PYTHON_API || '',
    timeout: 30000,
  },
}

export const interviewMode = {
  enabled: import.meta.env.VITE_INTERVIEW_MODE === 'true',
  pythonApi: import.meta.env.VITE_PYTHON_API || '',
}

import axios from 'axios'

// baseURL 为空字符串 → 同源请求，经由 vite proxy（开发）或 nginx（生产）转发到 Python 后端
export const http = axios.create({
  baseURL: '',
  timeout: 30000,
  // 同源请求默认携带 cookie（httpOnly auth_token）；跨源时也显式带上
  withCredentials: true,
})

// 请求拦截器：优先从 httpOnly cookie 自动鉴权；localStorage 中的旧 token 作为兜底
http.interceptors.request.use(
  (config) => {
    try {
      const stored = localStorage.getItem('user')
      if (stored) {
        const user = JSON.parse(stored)
        if (user.token) {
          config.headers.Authorization = `Bearer ${user.token}`
        }
      }
    } catch {
      /* localStorage 不可用，跳过 */
    }
    return config
  },
  (error) => Promise.reject(error)
)

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      if (!window.location.pathname.startsWith('/login')) {
        localStorage.removeItem('user')
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('auth:unauthorized'))
        }
      }
    }
    return Promise.reject(error)
  }
)
