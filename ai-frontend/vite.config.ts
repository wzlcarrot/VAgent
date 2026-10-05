import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

async function resolveApiProxy(): Promise<string> {
  const fromEnv = (process.env.VITE_API_PROXY || '').trim()
  if (fromEnv) return fromEnv
  const candidates = [
    'http://127.0.0.1:9090',
    'http://127.0.0.1:8001',
    'http://127.0.0.1:19090',
  ]
  for (const base of candidates) {
    try {
      const ctrl = new AbortController()
      const timer = setTimeout(() => ctrl.abort(), 400)
      const res = await fetch(`${base}/ai/login`, { method: 'GET', signal: ctrl.signal })
      clearTimeout(timer)
      // 本仓 FastAPI：GET /ai/login → 405；ViewHub 旧服务常见 404
      if (res.status === 405 || res.status === 422 || res.status === 200) {
        return base
      }
    } catch {
      /* 试下一个端口 */
    }
  }
  return 'http://127.0.0.1:9090'
}

export default defineConfig(async () => {
  const apiProxy = await resolveApiProxy()
  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src'),
      },
    },
    server: {
      port: 4000,
      proxy: {
        '/ai': {
          target: apiProxy,
          changeOrigin: true,
        },
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            'vue-vendor': ['vue', 'vue-router', 'pinia'],
            'http-vendor': ['axios'],
            'markdown-vendor': ['markdown-it', 'highlight.js', 'dompurify'],
          },
        },
      },
    },
  }
})
