import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// 集成测试专用配置：仅运行 tests/e2e.integration.test.ts（需要真实后端运行在 :18080）
// 不参与 coverage 门槛，单独触发：npm run test:integration
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
    include: ['tests/e2e.integration.test.ts'],
  },
})
