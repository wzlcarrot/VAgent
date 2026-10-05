import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['tests/**/*.{test,spec}.{ts,js}'],
    // 真实后端集成测试：需要后端运行在 :18080，手动触发，不纳入默认 run
    exclude: ['tests/e2e.integration.test.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['src/**/*.{ts,vue}'],
      // layout/login 壳不进门槛；views 进 20% 挂载门槛，其余目录 75%
      exclude: [
        'src/**/*.{test,spec}.ts',
        'src/main.ts',
        'src/components/login/**',
        'src/components/layout/**',
        'src/types/**',
        'src/router/**',
        'src/App.vue',
        'src/config/**',
        'src/vite-env.d.ts',
        'src/components/chat/HarnessDebugPanel.vue',
      ],
      thresholds: {
        // 页面壳单独门槛：纳入统计但不稀释核心 75%
        'src/{api,components,composables,stores,utils}/**': {
          lines: 75,
          functions: 60,
          statements: 75,
          branches: 55,
        },
        'src/views/**': {
          lines: 20,
          functions: 8,
          statements: 20,
          branches: 10,
        },
      },
    },
  },
})