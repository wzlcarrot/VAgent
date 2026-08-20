<template>
  <div class="login-page">
    <div class="left-panel">
      <div class="logo">
        <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
          <path d="M12 2L15 9H9L12 2Z" />
          <path d="M12 22L9 15H15L12 22Z" />
          <path d="M2 12L9 9V15L2 12Z" />
          <path d="M22 12L15 15V9L22 12Z" />
        </svg>
        <span>ViewHub AI</span>
      </div>
      <LoginCharacters
        ref="mascotsRef"
        :password="loginForm.password"
        :show-password="showPassword"
      />
      <div class="footer-links">
        <a href="#">隐私政策</a>
        <a href="#">服务条款</a>
        <a href="#">联系我们</a>
      </div>
    </div>

    <div class="right-panel">
      <div class="form-container">
        <div class="sparkle-icon">
          <svg viewBox="0 0 24 24" fill="none">
            <path d="M12 2L13.5 9H10.5L12 2Z" fill="var(--color-primary-strong)" />
            <path d="M12 22L10.5 15H13.5L12 22Z" fill="var(--color-primary-strong)" />
            <path d="M2 12L9 10.5V13.5L2 12Z" fill="var(--color-primary-strong)" />
            <path d="M22 12L15 13.5V10.5L22 12Z" fill="var(--color-primary-strong)" />
          </svg>
        </div>
        <div class="form-header">
          <h1>欢迎回来</h1>
          <p>请输入您的账户信息</p>
        </div>

        <form @submit.prevent="handleLogin">
          <div class="error-msg" :style="{ display: errorMessage ? 'block' : 'none' }" id="error-msg">{{ errorMessage }}</div>

          <div class="form-group">
            <label :class="{ 'error-label': emailError }">邮箱</label>
            <div class="input-wrapper">
              <input
                type="email"
                v-model="loginForm.email"
                placeholder="you@example.com"
                autocomplete="off"
                @focus="mascotsRef?.onEmailFocus()"
                @blur="mascotsRef?.onEmailBlur()"
                @input="mascotsRef?.onEmailInput()"
                :class="{ error: emailError }"
              />
            </div>
          </div>

          <div class="form-group">
            <label :class="{ 'error-label': passwordError }">密码</label>
            <div class="input-wrapper">
              <input
                :type="showPassword ? 'text' : 'password'"
                v-model="loginForm.password"
                placeholder="••••••••"
                @focus="mascotsRef?.onPasswordFocus()"
                @blur="mascotsRef?.onPasswordBlur()"
                @input="mascotsRef?.onPasswordInput()"
                :class="{ error: passwordError }"
              />
              <button type="button" class="toggle-password" @click="showPassword = !showPassword">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path v-if="!showPassword" d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                  <circle v-if="!showPassword" cx="12" cy="12" r="3"></circle>
                  <path v-else d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                  <line v-if="showPassword" x1="1" y1="1" x2="23" y2="23"></line>
                </svg>
              </button>
            </div>
          </div>

          <div class="form-options">
            <label class="remember-me">
              <input type="checkbox" checked /> 记住我 30 天
            </label>
            <a href="#" class="forgot-link">忘记密码？</a>
          </div>

          <button type="submit" class="btn-login" :disabled="isLoading">
            <span class="btn-text">{{ isLoading ? '登录中...' : '登录' }}</span>
            <div class="btn-hover-content">
              <span>登录</span>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="5" y1="12" x2="19" y2="12" />
                <polyline points="12 5 19 12 12 19" />
              </svg>
            </div>
          </button>

          <div class="test-account-hint">
            <div class="hint-label">测试账号（后端预置，直接使用）</div>
            <div class="hint-row">
              <span class="hint-key">邮箱:</span>
              <span class="hint-val">test@viewhub.com</span>
            </div>
            <div class="hint-row">
              <span class="hint-key">密码:</span>
              <span class="hint-val">123456</span>
            </div>
          </div>
        </form>
      </div>
    </div>

    <Transition name="success">
      <div v-if="isLoginSuccess" class="success-overlay">
        <div class="confetti">
          <span v-for="i in 20" :key="i" :style="getConfettiStyle(i)">✨</span>
        </div>
        <div class="success-content">
          <div class="success-icon">🎉</div>
          <p>{{ successMessage }}</p>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { login } from '@/api/user'
import { useLoginForm } from '@/composables/useLoginForm'
import LoginCharacters from '@/components/login/LoginCharacters.vue'

const router = useRouter()
const userStore = useUserStore()
const showPassword = ref(false)
const mascotsRef = ref<InstanceType<typeof LoginCharacters> | null>(null)

const {
  loginForm,
  isLoading,
  errorMessage,
  emailError,
  passwordError,
  isLoginSuccess,
  successMessage,
  applyValidationError,
  applyAuthFailure,
} = useLoginForm()

async function handleLogin() {
  if (!applyValidationError()) {
    mascotsRef.value?.triggerLoginError()
    return
  }

  isLoading.value = true
  try {
    const response = await login({
      email: loginForm.email,
      password: loginForm.password,
    })
    userStore.setUser(response.user)
    isLoginSuccess.value = true
    successMessage.value = '登录成功，正在跳转...'
    setTimeout(() => {
      router.push('/')
    }, 2000)
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : '登录失败，请重试。'
    applyAuthFailure(msg)
    mascotsRef.value?.triggerLoginError()
  } finally {
    isLoading.value = false
  }
}

function getConfettiStyle(_i: number) {
  return {
    left: `${Math.random() * 100}%`,
    animationDelay: `${Math.random() * 2}s`,
    animationDuration: `${2 + Math.random() * 2}s`,
    fontSize: `${12 + Math.random() * 16}px`,
  }
}

onMounted(() => {
  userStore.initFromStorage()
  if (userStore.isLoggedIn) {
    router.push('/')
  }
})
</script>

<style scoped>
.login-page {
  display: grid;
  grid-template-columns: 1fr 1fr;
  height: 100vh;
  font-family: "Inter", -apple-system, BlinkMacSystemFont, sans-serif;
}

.left-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  background: linear-gradient(135deg, #d4d0dc 0%, #c8c4d0 50%, #bbb7c5 100%);
  padding: 40px 48px;
  overflow: hidden;
}

.left-panel .logo {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
  color: #fff;
  z-index: 10;
  position: relative;
}

.left-panel .logo svg {
  width: 28px;
  height: 28px;
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(8px);
  padding: 4px;
  border-radius: 6px;
}

.left-panel::after {
  content: "";
  position: absolute;
  top: 20%;
  right: 15%;
  width: 260px;
  height: 260px;
  background: rgba(180, 170, 200, 0.25);
  border-radius: 50%;
  filter: blur(80px);
}

.left-panel::before {
  content: "";
  position: absolute;
  bottom: 15%;
  left: 10%;
  width: 350px;
  height: 350px;
  background: rgba(200, 195, 210, 0.2);
  border-radius: 50%;
  filter: blur(100px);
}

.footer-links {
  display: flex;
  gap: 28px;
  font-size: 13px;
  color: rgba(80, 70, 90, 0.7);
  z-index: 10;
  position: relative;
}

.footer-links a {
  color: inherit;
  text-decoration: none;
  transition: color 0.2s;
}

.footer-links a:hover {
  color: #333;
}

.right-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
  padding: 40px;
}

.form-container {
  width: 100%;
  max-width: 400px;
}

.sparkle-icon {
  display: flex;
  justify-content: center;
  margin-bottom: 24px;
}

.sparkle-icon svg {
  width: 32px;
  height: 32px;
}

.form-header {
  text-align: center;
  margin-bottom: 36px;
}

.form-header h1 {
  font-size: 28px;
  font-weight: 700;
  color: var(--color-primary-strong);
  letter-spacing: -0.5px;
  margin-bottom: 6px;
}

.form-header p {
  font-size: 14px;
  color: #888;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: #333;
  margin-bottom: 8px;
  transition: color 0.3s;
}

.form-group label.error-label {
  color: #dc2626;
}

.input-wrapper {
  position: relative;
}

.form-group input {
  width: 100%;
  height: 48px;
  border: none;
  border-bottom: 1.5px solid #e0e0e0;
  padding: 0 40px 0 0;
  font-size: 15px;
  font-family: inherit;
  color: var(--color-primary-strong);
  background: transparent;
  outline: none;
  transition: border-color 0.3s;
}

.form-group input:focus {
  border-bottom-color: var(--color-primary-strong);
}

.form-group input.error {
  border-bottom-color: #dc2626;
}

.form-group input::placeholder {
  color: #ccc;
}

.form-group input[type="password"]:not(:placeholder-shown) {
  font-family: inherit;
  letter-spacing: 2px;
}

.form-group input[type="password"]::-ms-reveal,
.form-group input[type="password"]::-ms-clear {
  display: none;
}

.toggle-password {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  cursor: pointer;
  color: #666;
  padding: 6px;
  transition: color 0.2s;
}

.toggle-password:hover {
  color: #333;
}

.form-options {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.remember-me {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #555;
  cursor: pointer;
}

.remember-me input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: var(--color-primary-strong);
  cursor: pointer;
}

.forgot-link {
  font-size: 13px;
  color: var(--color-primary-strong);
  text-decoration: none;
  font-weight: 500;
  transition: opacity 0.2s;
}

.forgot-link:hover {
  opacity: 0.8;
}

.btn-login {
  position: relative;
  width: 100%;
  height: 50px;
  border-radius: 25px;
  border: 1.5px solid var(--color-primary-strong);
  background: var(--color-primary-strong);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  overflow: hidden;
  transition: all 0.3s;
}

.btn-login:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}

.test-account-hint {
  margin-top: 16px;
  padding: 10px 14px;
  background: #f0f7ff;
  border: 1px dashed #7bb8ff;
  border-radius: 8px;
  text-align: center;

  .hint-label {
    font-size: 12px;
    font-weight: 600;
    color: #409eff;
    margin-bottom: 4px;
  }

  .hint-row {
    font-size: 13px;
    color: #606266;

    .hint-key {
      color: #909399;
      margin-right: 4px;
    }

    .hint-val {
      color: #303133;
      font-weight: 500;
      font-family: monospace;
    }
  }
}

.btn-login .btn-text {
  display: inline-block;
  transition: all 0.3s;
}

.btn-login .btn-hover-content {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: var(--color-primary-strong);
  color: #fff;
  opacity: 0;
  transition: all 0.3s;
  border-radius: 25px;
}

.btn-login:hover:not(:disabled) .btn-text {
  transform: translateX(40px);
  opacity: 0;
}

.btn-login:hover:not(:disabled) .btn-hover-content {
  opacity: 1;
}

.error-msg {
  display: none;
  padding: 10px 14px;
  font-size: 13px;
  color: #dc2626;
  background: rgba(220, 38, 38, 0.08);
  border: 1px solid rgba(220, 38, 38, 0.2);
  border-radius: 10px;
  margin-bottom: 16px;
}

.success-overlay {
  position: fixed;
  inset: 0;
  background: linear-gradient(135deg, rgba(102,126,234,0.95) 0%, rgba(118,75,162,0.95) 100%);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.confetti {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.confetti span {
  position: absolute;
  top: -20px;
  animation: confettiFall 3s ease-in-out infinite;
}

@keyframes confettiFall {
  0% { transform: translateY(0) rotate(0deg); opacity: 1; }
  100% { transform: translateY(100vh) rotate(720deg); opacity: 0; }
}

.success-content {
  text-align: center;
  z-index: 10;
}

.success-icon {
  font-size: 80px;
  animation: successBounce 0.6s ease-in-out infinite;
}

@keyframes successBounce {
  0%, 100% { transform: scale(1) rotate(-5deg); }
  50% { transform: scale(1.1) rotate(5deg); }
}

.success-overlay p {
  margin-top: 20px;
  font-size: 20px;
  color: white;
  font-weight: 500;
}

.success-enter-active,
.success-leave-active {
  transition: opacity 0.5s ease;
}

.success-enter-from,
.success-leave-to {
  opacity: 0;
}

@media (max-width: 900px) {
  .login-page {
    grid-template-columns: 1fr;
  }

  .left-panel {
    display: none;
  }
}
</style>
