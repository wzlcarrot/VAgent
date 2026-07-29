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
})

// 请求拦截器：自动从 localStorage 注入 Authorization 头
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
