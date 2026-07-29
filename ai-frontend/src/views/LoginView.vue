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
      <div class="characters-wrapper">
        <div class="characters-scene">
          <div class="character char-purple" ref="charPurpleRef" :style="purpleStyle">
            <div class="eyes" :style="purpleEyesStyle">
              <div class="eyeball" :style="{ width: '18px', height: purpleEyeLHeight }">
                <div class="pupil" :style="{ width: '7px', height: '7px', transform: purplePupilTransform }"></div>
              </div>
              <div class="eyeball" :style="{ width: '18px', height: purpleEyeRHeight }">
                <div class="pupil" :style="{ width: '7px', height: '7px', transform: purplePupilTransform }"></div>
              </div>
            </div>
          </div>
          <div class="character char-black" ref="charBlackRef" :style="blackStyle">
            <div class="eyes" :style="blackEyesStyle">
              <div class="eyeball" :style="{ width: '16px', height: blackEyeLHeight }">
                <div class="pupil" :style="{ width: '6px', height: '6px', transform: blackPupilTransform }"></div>
              </div>
              <div class="eyeball" :style="{ width: '16px', height: blackEyeRHeight }">
                <div class="pupil" :style="{ width: '6px', height: '6px', transform: blackPupilTransform }"></div>
              </div>
            </div>
          </div>
          <div class="character char-orange" ref="charOrangeRef" :style="orangeStyle">
            <div class="eyes" :style="orangeEyesStyle">
              <div class="bare-pupil" :style="{ transform: orangePupilTransform }"></div>
              <div class="bare-pupil" :style="{ transform: orangePupilTransform }"></div>
            </div>
            <div class="orange-mouth" :class="{ visible: isLoginError }" :style="orangeMouthStyle"></div>
          </div>
          <div class="character char-yellow" ref="charYellowRef" :style="yellowStyle">
            <div class="eyes" :style="yellowEyesStyle">
              <div class="bare-pupil" :style="{ transform: yellowPupilTransform }"></div>
              <div class="bare-pupil" :style="{ transform: yellowPupilTransform }"></div>
            </div>
            <div class="yellow-mouth" :class="{ 'shake-head': showShake }" :style="yellowMouthStyle"></div>
          </div>
        </div>
      </div>
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
            <path d="M12 2L13.5 9H10.5L12 2Z" fill="#1a1a2e" />
            <path d="M12 22L10.5 15H13.5L12 22Z" fill="#1a1a2e" />
            <path d="M2 12L9 10.5V13.5L2 12Z" fill="#1a1a2e" />
            <path d="M22 12L15 13.5V10.5L22 12Z" fill="#1a1a2e" />
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
                @focus="onEmailFocus"
                @blur="onEmailBlur"
                @input="onEmailInput"
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
                @focus="onPasswordFocus"
                @blur="onPasswordBlur"
                @input="onPasswordInput"
                :class="{ error: passwordError }"
              />
              <button type="button" class="toggle-password" @click="togglePassword">
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
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { login } from '@/api/user'

const router = useRouter()
const userStore = useUserStore()

const charPurpleRef = ref<HTMLElement>()
const charBlackRef = ref<HTMLElement>()
const charOrangeRef = ref<HTMLElement>()
const charYellowRef = ref<HTMLElement>()

const mouseX = ref(0)
const mouseY = ref(0)

const isPurplePeeking = ref(false)
const isLookingAtEachOther = ref(false)
const isTyping = ref(false)
const isPasswordFocused = ref(false)
const showPassword = ref(false)
const isLoginError = ref(false)
const isLoading = ref(false)
const errorMessage = ref('')
const emailError = ref(false)
const passwordError = ref(false)
const isLoginSuccess = ref(false)
const successMessage = ref('')
const showShake = ref(false)

const loginForm = reactive({
  email: '',
  password: '',
})

// Character position data (reactive)
const purplePos = reactive({ faceX: 0, faceY: 0, bodySkew: 0 })
const blackPos = reactive({ faceX: 0, faceY: 0, bodySkew: 0 })
const orangePos = reactive({ faceX: 0, faceY: 0, bodySkew: 0 })
const yellowPos = reactive({ faceX: 0, faceY: 0, bodySkew: 0 })

const purpleEyeLHeight = ref('18px')
const purpleEyeRHeight = ref('18px')
const blackEyeLHeight = ref('16px')
const blackEyeRHeight = ref('16px')

const defaultPurpleEyes = { left: '45px', top: '40px' }
const defaultBlackEyes = { left: '26px', top: '32px' }
const defaultOrangeEyes = { left: '82px', top: '90px' }
const defaultYellowEyes = { left: '52px', top: '40px' }

const purpleEyesPos = reactive({ ...defaultPurpleEyes })
const blackEyesPos = reactive({ ...defaultBlackEyes })
const orangeEyesPos = reactive({ ...defaultOrangeEyes })
const yellowEyesPos = reactive({ ...defaultYellowEyes })

const purplePupilTransform = ref('translate(0px, 0px)')
const blackPupilTransform = ref('translate(0px, 0px)')
const orangePupilTransform = ref('translate(0px, 0px)')
const yellowPupilTransform = ref('translate(0px, 0px)')
const yellowMouthPos = reactive({ left: '40px', top: '88px', rotate: '0deg' })

let errorRecoverTimer: number | null = null
let typingTimer: number | null = null
let purpleBlinkTimer: number | null = null
let blackBlinkTimer: number | null = null
let peekTimer: number | null = null

const purpleStyle = computed(() => {
  if (isLoginError.value) return { transform: 'skewX(0deg)', height: '370px' }
  const pwdLen = loginForm.password.length
  const isShowingPwd = pwdLen > 0 && showPassword.value
  const isLookingAway = isPasswordFocused.value && !showPassword.value

  if (isShowingPwd) return { transform: 'skewX(0deg)', height: '370px' }
  if (isLookingAway) return { transform: 'skewX(-14deg) translateX(-20px)', height: '410px' }
  if (isTyping.value) return { transform: `skewX(${purplePos.bodySkew - 12}deg) translateX(40px)`, height: '410px' }
  return { transform: `skewX(${purplePos.bodySkew}deg)`, height: '370px' }
})

const blackStyle = computed(() => {
  if (isLoginError.value) return { transform: 'skewX(0deg)' }
  const isShowingPwd = loginForm.password.length > 0 && showPassword.value
  const isLookingAway = isPasswordFocused.value && !showPassword.value

  if (isShowingPwd) return { transform: 'skewX(0deg)' }
  if (isLookingAway) return { transform: 'skewX(12deg) translateX(-10px)' }
  if (isLookingAtEachOther.value) return { transform: `skewX(${blackPos.bodySkew * 1.5 + 10}deg) translateX(20px)` }
  if (isTyping.value) return { transform: `skewX(${blackPos.bodySkew * 1.5}deg)` }
  return { transform: `skewX(${blackPos.bodySkew}deg)` }
})

const orangeStyle = computed(() => {
  const isShowingPwd = loginForm.password.length > 0 && showPassword.value
  if (isShowingPwd) return { transform: 'skewX(0deg)' }
  return { transform: `skewX(${orangePos.bodySkew}deg)` }
})

const yellowStyle = computed(() => {
  const isShowingPwd = loginForm.password.length > 0 && showPassword.value
  if (isShowingPwd) return { transform: 'skewX(0deg)' }
  return { transform: `skewX(${yellowPos.bodySkew}deg)` }
})

const purpleEyesStyle = computed(() => {
  if (isLoginError.value) return { left: '30px', top: '55px', gap: '28px' }
  const pwdLen = loginForm.password.length
  const isShowingPwd = pwdLen > 0 && showPassword.value
  const isLookingAway = isPasswordFocused.value && !showPassword.value

  if (isLookingAway) return { left: '20px', top: '25px', gap: '28px' }
  if (isShowingPwd) return { left: '20px', top: '35px', gap: '28px' }
  if (isLookingAtEachOther.value) return { left: '55px', top: '65px', gap: '28px' }
  return { left: purpleEyesPos.left, top: purpleEyesPos.top, gap: '28px' }
})

const blackEyesStyle = computed(() => {
  if (isLoginError.value) return { left: '15px', top: '40px', gap: '20px' }
  const isShowingPwd = loginForm.password.length > 0 && showPassword.value
  const isLookingAway = isPasswordFocused.value && !showPassword.value

  if (isLookingAway) return { left: '10px', top: '20px', gap: '20px' }
  if (isShowingPwd) return { left: '10px', top: '28px', gap: '20px' }
  if (isLookingAtEachOther.value) return { left: '32px', top: '12px', gap: '20px' }
  return { left: blackEyesPos.left, top: blackEyesPos.top, gap: '20px' }
})

const orangeEyesStyle = computed(() => {
  if (isLoginError.value) return { left: '60px', top: '95px', gap: '28px' }
  const isLookingAway = isPasswordFocused.value && !showPassword.value
  const isShowingPwd = loginForm.password.length > 0 && showPassword.value

  if (isLookingAway) return { left: '50px', top: '75px', gap: '28px' }
  if (isShowingPwd) return { left: '50px', top: '85px', gap: '28px' }
  return { left: orangeEyesPos.left, top: orangeEyesPos.top, gap: '28px' }
})

const yellowEyesStyle = computed(() => {
  if (isLoginError.value) return { left: '35px', top: '45px', gap: '20px' }
  const isLookingAway = isPasswordFocused.value && !showPassword.value
  const isShowingPwd = loginForm.password.length > 0 && showPassword.value

  if (isLookingAway) return { left: '20px', top: '30px', gap: '20px' }
  if (isShowingPwd) return { left: '20px', top: '35px', gap: '20px' }
  return { left: yellowEyesPos.left, top: yellowEyesPos.top, gap: '20px' }
})

const orangeMouthStyle = computed(() => {
  if (isLoginError.value) return { left: `${80 + orangePos.faceX}px`, top: '130px' }
  return { left: '90px', top: '120px' }
})

const yellowMouthStyle = computed(() => {
  if (isLoginError.value) return { left: '30px', top: '92px', transform: 'rotate(-8deg)' }
  const isLookingAway = isPasswordFocused.value && !showPassword.value
  const isShowingPwd = loginForm.password.length > 0 && showPassword.value

  if (isLookingAway) return { left: '15px', top: '78px', transform: 'rotate(0deg)' }
  if (isShowingPwd) return { left: '10px', top: '88px', transform: 'rotate(0deg)' }
  return { left: yellowMouthPos.left, top: yellowMouthPos.top, transform: `rotate(${yellowMouthPos.rotate})` }
})

function calcPosition(el: HTMLElement | undefined) {
  if (!el) return { faceX: 0, faceY: 0, bodySkew: 0 }
  const rect = el.getBoundingClientRect()
  const cx = rect.left + rect.width / 2
  const cy = rect.top + rect.height / 3
  const dx = mouseX.value - cx
  const dy = mouseY.value - cy
  const faceX = Math.max(-15, Math.min(15, dx / 20))
  const faceY = Math.max(-10, Math.min(10, dy / 30))
  const bodySkew = Math.max(-6, Math.min(6, -dx / 120))
  return { faceX, faceY, bodySkew }
}

function calcPupilOffset(el: HTMLElement | undefined, maxDist: number) {
  if (!el) return { x: 0, y: 0 }
  const rect = el.getBoundingClientRect()
  const cx = rect.left + rect.width / 2
  const cy = rect.top + rect.height / 2
  const dx = mouseX.value - cx
  const dy = mouseY.value - cy
  const dist = Math.min(Math.sqrt(dx * dx + dy * dy), maxDist)
  const angle = Math.atan2(dy, dx)
  return { x: Math.cos(angle) * dist, y: Math.sin(angle) * dist }
}

function updateCharacters() {
  const p = calcPosition(charPurpleRef.value)
  const b = calcPosition(charBlackRef.value)
  const o = calcPosition(charOrangeRef.value)
  const y = calcPosition(charYellowRef.value)
  Object.assign(purplePos, p)
  Object.assign(blackPos, b)
  Object.assign(orangePos, o)
  Object.assign(yellowPos, y)

  const pwdLen = loginForm.password.length
  const isShowingPwd = pwdLen > 0 && showPassword.value
  const isLookingAway = isPasswordFocused.value && !showPassword.value

  // Purple pupils
  if (isLoginError.value) {
    purplePupilTransform.value = 'translate(-3px, 4px)'
  } else if (isLookingAway) {
    purplePupilTransform.value = 'translate(-5px, -5px)'
  } else if (isShowingPwd) {
    const px = isPurplePeeking.value ? 4 : -4
    const py = isPurplePeeking.value ? 5 : -4
    purplePupilTransform.value = `translate(${px}px, ${py}px)`
  } else if (isLookingAtEachOther.value) {
    purplePupilTransform.value = 'translate(3px, 4px)'
  } else {
    const po = calcPupilOffset(charPurpleRef.value?.querySelector('.eyeball') as HTMLElement, 5)
    purplePupilTransform.value = `translate(${po.x}px, ${po.y}px)`
  }

  // Black pupils
  if (isLoginError.value) {
    blackPupilTransform.value = 'translate(-3px, 4px)'
  } else if (isLookingAway) {
    blackPupilTransform.value = 'translate(-4px, -5px)'
  } else if (isShowingPwd) {
    blackPupilTransform.value = 'translate(-4px, -4px)'
  } else if (isLookingAtEachOther.value) {
    blackPupilTransform.value = 'translate(0px, -4px)'
  } else {
    const bo = calcPupilOffset(charBlackRef.value?.querySelector('.eyeball') as HTMLElement, 4)
    blackPupilTransform.value = `translate(${bo.x}px, ${bo.y}px)`
  }

  // Orange pupils
  if (isLoginError.value) {
    orangePupilTransform.value = 'translate(-3px, 4px)'
  } else if (isLookingAway) {
    orangePupilTransform.value = 'translate(-5px, -5px)'
  } else if (isShowingPwd) {
    orangePupilTransform.value = 'translate(-5px, -4px)'
  } else {
    const oo = calcPupilOffset(charOrangeRef.value?.querySelector('.bare-pupil') as HTMLElement, 5)
    orangePupilTransform.value = `translate(${oo.x}px, ${oo.y}px)`
  }

  // Yellow pupils
  if (isLoginError.value) {
    yellowPupilTransform.value = 'translate(-3px, 4px)'
  } else if (isLookingAway) {
    yellowPupilTransform.value = 'translate(-5px, -5px)'
  } else if (isShowingPwd) {
    yellowPupilTransform.value = 'translate(-5px, -4px)'
  } else {
    const yo = calcPupilOffset(charYellowRef.value?.querySelector('.bare-pupil') as HTMLElement, 5)
    yellowPupilTransform.value = `translate(${yo.x}px, ${yo.y}px)`
  }

  // Eye positions (idle tracking)
  if (!isLoginError.value && !isLookingAway && !isShowingPwd && !isLookingAtEachOther.value) {
    purpleEyesPos.left = `${45 + purplePos.faceX}px`
    purpleEyesPos.top = `${40 + purplePos.faceY}px`
    blackEyesPos.left = `${26 + blackPos.faceX}px`
    blackEyesPos.top = `${32 + blackPos.faceY}px`
    orangeEyesPos.left = `${82 + orangePos.faceX}px`
    orangeEyesPos.top = `${90 + orangePos.faceY}px`
    yellowEyesPos.left = `${52 + yellowPos.faceX}px`
    yellowEyesPos.top = `${40 + yellowPos.faceY}px`
  }

  // Yellow mouth
  if (!isLoginError.value && !isLookingAway && !isShowingPwd) {
    yellowMouthPos.left = `${40 + yellowPos.faceX}px`
    yellowMouthPos.top = `${88 + yellowPos.faceY}px`
  }
}

function onMouseMove(e: MouseEvent) {
  mouseX.value = e.clientX
  mouseY.value = e.clientY
  if (!isTyping.value && !isLoginError.value) {
    updateCharacters()
  }
}

function onEmailFocus() {
  isTyping.value = true
  isLookingAtEachOther.value = true
  clearTypingTimer()
  typingTimer = window.setTimeout(() => {
    isLookingAtEachOther.value = false
    updateCharacters()
  }, 800)
  updateCharacters()
}

function onEmailBlur() {
  isTyping.value = false
  isLookingAtEachOther.value = false
  clearTypingTimer()
  updateCharacters()
}

function onEmailInput() {
  updateCharacters()
}

function onPasswordFocus() {
  isPasswordFocused.value = true
  updateCharacters()
}

function onPasswordBlur() {
  isPasswordFocused.value = false
  updateCharacters()
}

function onPasswordInput() {
  updateCharacters()
}

function togglePassword() {
  showPassword.value = !showPassword.value
  if (showPassword.value) schedulePeek()
  updateCharacters()
}

function clearTypingTimer() {
  if (typingTimer !== null) {
    clearTimeout(typingTimer)
    typingTimer = null
  }
}

// Blinking
function scheduleBlinkPurple() {
  purpleBlinkTimer = window.setTimeout(() => {
    purpleEyeLHeight.value = '2px'
    purpleEyeRHeight.value = '2px'
    window.setTimeout(() => {
      purpleEyeLHeight.value = '18px'
      purpleEyeRHeight.value = '18px'
      scheduleBlinkPurple()
    }, 150)
  }, Math.random() * 4000 + 3000)
}

function scheduleBlinkBlack() {
  blackBlinkTimer = window.setTimeout(() => {
    blackEyeLHeight.value = '2px'
    blackEyeRHeight.value = '2px'
    window.setTimeout(() => {
      blackEyeLHeight.value = '16px'
      blackEyeRHeight.value = '16px'
      scheduleBlinkBlack()
    }, 150)
  }, Math.random() * 4000 + 3000)
}

function schedulePeek() {
  if (loginForm.password.length > 0 && showPassword.value) {
    peekTimer = window.setTimeout(() => {
      if (loginForm.password.length > 0 && showPassword.value) {
        isPurplePeeking.value = true
        updateCharacters()
        window.setTimeout(() => {
          isPurplePeeking.value = false
          updateCharacters()
          schedulePeek()
        }, 800)
      }
    }, Math.random() * 3000 + 2000)
  }
}

function triggerLoginError() {
  if (errorRecoverTimer !== null) {
    clearTimeout(errorRecoverTimer)
    errorRecoverTimer = null
  }
  showShake.value = false
  void document.body.offsetHeight

  isLoginError.value = true
  isPasswordFocused.value = false
  updateCharacters()

  window.setTimeout(() => {
    showShake.value = true
  }, 350)

  errorRecoverTimer = window.setTimeout(() => {
    isLoginError.value = false
    showShake.value = false
    errorRecoverTimer = null
    updateCharacters()
  }, 2500)
}

async function handleLogin() {
  errorMessage.value = ''
  emailError.value = false
  passwordError.value = false

  if (!loginForm.email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(loginForm.email)) {
    emailError.value = true
    errorMessage.value = '请输入有效的邮箱地址。'
    triggerLoginError()
    return
  }

  if (!loginForm.password || loginForm.password.length < 6) {
    passwordError.value = true
    errorMessage.value = '密码至少需要 6 个字符。'
    triggerLoginError()
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
    const err = error as { message?: string }
    const msg = error instanceof Error ? error.message : '登录失败，请重试。'
    errorMessage.value = msg
    if (err.message?.includes('邮箱')) {
      emailError.value = true
    } else {
      passwordError.value = true
    }
    triggerLoginError()
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
  document.addEventListener('mousemove', onMouseMove)
  scheduleBlinkPurple()
  scheduleBlinkBlack()
})

onUnmounted(() => {
  document.removeEventListener('mousemove', onMouseMove)
  if (purpleBlinkTimer !== null) clearTimeout(purpleBlinkTimer)
  if (blackBlinkTimer !== null) clearTimeout(blackBlinkTimer)
  if (peekTimer !== null) clearTimeout(peekTimer)
  if (errorRecoverTimer !== null) clearTimeout(errorRecoverTimer)
  clearTypingTimer()
})
</script>

<style scoped>
.login-page {
  display: grid;
  grid-template-columns: 1fr 1fr;
  height: 100vh;
  font-family: "Inter", -apple-system, BlinkMacSystemFont, sans-serif;
}

/* ============ LEFT PANEL ============ */
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

.characters-wrapper {
  position: relative;
  z-index: 10;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  height: 420px;
}

.characters-scene {
  position: relative;
  width: 480px;
  height: 360px;
}

.character {
  position: absolute;
  bottom: 0;
  transition: all 0.7s ease-in-out;
  transform-origin: bottom center;
}

.char-purple {
  left: 60px;
  width: 170px;
  height: 370px;
  background: #6c3ff5;
  border-radius: 10px 10px 0 0;
  z-index: 1;
}

.char-black {
  left: 220px;
  width: 115px;
  height: 290px;
  background: #2d2d2d;
  border-radius: 8px 8px 0 0;
  z-index: 2;
}

.char-orange {
  left: 0;
  width: 230px;
  height: 190px;
  background: #ff9b6b;
  border-radius: 115px 115px 0 0;
  z-index: 3;
}

.char-yellow {
  left: 290px;
  width: 135px;
  height: 215px;
  background: #e8d754;
  border-radius: 68px 68px 0 0;
  z-index: 4;
}

.eyes {
  position: absolute;
  display: flex;
  transition: all 0.7s ease-in-out;
}

.eyeball {
  border-radius: 50%;
  background: white;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: height 0.15s ease;
  overflow: hidden;
}

.pupil {
  border-radius: 50%;
  background: #2d2d2d;
  transition: transform 0.1s ease-out;
}

.bare-pupil {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #2d2d2d;
  transition: transform 0.7s ease-in-out;
}

.yellow-mouth {
  position: absolute;
  width: 50px;
  height: 4px;
  background: #2d2d2d;
  border-radius: 2px;
  transition: all 0.7s ease-in-out;
}

@keyframes shakeHead {
  0%, 100% { translate: 0 0; }
  10% { translate: -9px 0; }
  20% { translate: 7px 0; }
  30% { translate: -6px 0; }
  40% { translate: 5px 0; }
  50% { translate: -4px 0; }
  60% { translate: 3px 0; }
  70% { translate: -2px 0; }
  80% { translate: 1px 0; }
  90% { translate: -0.5px 0; }
}

:deep(.eyes.shake-head),
:deep(.yellow-mouth.shake-head),
:deep(.orange-mouth.shake-head) {
  animation: shakeHead 0.8s cubic-bezier(0.36, 0.07, 0.19, 0.97) both;
}

.orange-mouth {
  position: absolute;
  width: 28px;
  height: 14px;
  border: 3px solid #2d2d2d;
  border-top: none;
  border-radius: 0 0 14px 14px;
  opacity: 0;
  transition: all 0.7s ease-in-out;
}

.orange-mouth.visible {
  opacity: 1;
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

/* ============ RIGHT PANEL ============ */
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
  color: #1a1a2e;
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
  color: #1a1a2e;
  background: transparent;
  outline: none;
  transition: border-color 0.3s;
}

.form-group input:focus {
  border-bottom-color: #5b21b6;
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
  accent-color: #5b21b6;
  cursor: pointer;
}

.forgot-link {
  font-size: 13px;
  color: #5b21b6;
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
  border: 1.5px solid #1a1a2e;
  background: #1a1a2e;
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
  background: #5b21b6;
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

/* ============ SUCCESS OVERLAY ============ */
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

/* ============ RESPONSIVE ============ */
@media (max-width: 900px) {
  .login-page {
    grid-template-columns: 1fr;
  }

  .left-panel {
    display: none;
  }
}
</style>
