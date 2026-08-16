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
      // 集成胶水层（依赖路由/全局状态/复杂交互，单测成本远高于收益）不参与门槛
      exclude: [
        'src/**/*.{test,spec}.ts',
        'src/main.ts',
        'src/views/**',
        'src/router/**',
        'src/App.vue',
        'src/config/**',
        'src/vite-env.d.ts',
      ],
      thresholds: {
        lines: 60,
        functions: 45,
        statements: 60,
        branches: 45,
      },
    },
  },
})