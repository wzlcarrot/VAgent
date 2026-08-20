import { reactive, ref } from 'vue'

export function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
}

export function useLoginForm() {
  const loginForm = reactive({
    email: '',
    password: '',
  })
  const isLoading = ref(false)
  const errorMessage = ref('')
  const emailError = ref('')
  const passwordError = ref('')
  const isLoginSuccess = ref(false)
  const successMessage = ref('')

  function applyValidationError(): boolean {
    emailError.value = ''
    passwordError.value = ''
    errorMessage.value = ''
    if (!loginForm.email) {
      emailError.value = '请输入邮箱'
      return false
    }
    if (!isValidEmail(loginForm.email)) {
      emailError.value = '邮箱格式不正确'
      return false
    }
    if (!loginForm.password) {
      passwordError.value = '请输入密码'
      return false
    }
    if (loginForm.password.length < 6) {
      passwordError.value = '密码至少 6 位'
      return false
    }
    return true
  }

  function applyAuthFailure(msg: string) {
    errorMessage.value = msg || '登录失败，请重试。'
    isLoginSuccess.value = false
  }

  return {
    loginForm,
    isLoading,
    errorMessage,
    emailError,
    passwordError,
    isLoginSuccess,
    successMessage,
    applyValidationError,
    applyAuthFailure,
  }
}
