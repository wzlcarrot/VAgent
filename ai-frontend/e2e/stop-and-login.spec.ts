/**
 * 登录页不得展示测试账密。
 */
import { test, expect } from '@playwright/test'

test('登录页不含测试密码', async ({ page }) => {
  await page.goto('/login')
  await expect(page.locator('body')).not.toContainText('123456')
  await expect(page.locator('body')).not.toContainText('test@viewhub.com')
})
