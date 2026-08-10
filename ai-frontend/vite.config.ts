import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 4000,
    proxy: {
      // 开发环境：将所有 /ai 请求代理到 Python 后端
      '/ai': {
        target: 'http://localhost:9090',
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
})
