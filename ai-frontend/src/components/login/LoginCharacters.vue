<template>
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
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { calcFaceOffset, calcPupilOffset, rectCenter } from '@/composables/useLoginMascots'

const props = defineProps<{
  password: string
  showPassword: boolean
}>()

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
const isLoginError = ref(false)
const showShake = ref(false)

const purplePos = reactive({ faceX: 0, faceY: 0, bodySkew: 0 })
const blackPos = reactive({ faceX: 0, faceY: 0, bodySkew: 0 })
const orangePos = reactive({ faceX: 0, faceY: 0, bodySkew: 0 })
const yellowPos = reactive({ faceX: 0, faceY: 0, bodySkew: 0 })

const purpleEyeLHeight = ref('18px')
const purpleEyeRHeight = ref('18px')
const blackEyeLHeight = ref('16px')
const blackEyeRHeight = ref('16px')

const purpleEyesPos = reactive({ left: '45px', top: '40px' })
const blackEyesPos = reactive({ left: '26px', top: '32px' })
const orangeEyesPos = reactive({ left: '82px', top: '90px' })
const yellowEyesPos = reactive({ left: '52px', top: '40px' })
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

const isShowingPwd = computed(() => props.password.length > 0 && props.showPassword)
const isLookingAway = computed(() => isPasswordFocused.value && !props.showPassword)

const purpleStyle = computed(() => {
  if (isLoginError.value) return { transform: 'skewX(0deg)', height: '370px' }
  if (isShowingPwd.value) return { transform: 'skewX(0deg)', height: '370px' }
  if (isLookingAway.value) return { transform: 'skewX(-14deg) translateX(-20px)', height: '410px' }
  if (isTyping.value) return { transform: `skewX(${purplePos.bodySkew - 12}deg) translateX(40px)`, height: '410px' }
  return { transform: `skewX(${purplePos.bodySkew}deg)`, height: '370px' }
})

const blackStyle = computed(() => {
  if (isLoginError.value) return { transform: 'skewX(0deg)' }
  if (isShowingPwd.value) return { transform: 'skewX(0deg)' }
  if (isLookingAway.value) return { transform: 'skewX(12deg) translateX(-10px)' }
  if (isLookingAtEachOther.value) return { transform: `skewX(${blackPos.bodySkew * 1.5 + 10}deg) translateX(20px)` }
  if (isTyping.value) return { transform: `skewX(${blackPos.bodySkew * 1.5}deg)` }
  return { transform: `skewX(${blackPos.bodySkew}deg)` }
})

const orangeStyle = computed(() => {
  if (isShowingPwd.value) return { transform: 'skewX(0deg)' }
  return { transform: `skewX(${orangePos.bodySkew}deg)` }
})

const yellowStyle = computed(() => {
  if (isShowingPwd.value) return { transform: 'skewX(0deg)' }
  return { transform: `skewX(${yellowPos.bodySkew}deg)` }
})

const purpleEyesStyle = computed(() => {
  if (isLoginError.value) return { left: '30px', top: '55px', gap: '28px' }
  if (isLookingAway.value) return { left: '20px', top: '25px', gap: '28px' }
  if (isShowingPwd.value) return { left: '20px', top: '35px', gap: '28px' }
  if (isLookingAtEachOther.value) return { left: '55px', top: '65px', gap: '28px' }
  return { left: purpleEyesPos.left, top: purpleEyesPos.top, gap: '28px' }
})

const blackEyesStyle = computed(() => {
  if (isLoginError.value) return { left: '15px', top: '40px', gap: '20px' }
  if (isLookingAway.value) return { left: '10px', top: '20px', gap: '20px' }
  if (isShowingPwd.value) return { left: '10px', top: '28px', gap: '20px' }
  if (isLookingAtEachOther.value) return { left: '32px', top: '12px', gap: '20px' }
  return { left: blackEyesPos.left, top: blackEyesPos.top, gap: '20px' }
})

const orangeEyesStyle = computed(() => {
  if (isLoginError.value) return { left: '60px', top: '95px', gap: '28px' }
  if (isLookingAway.value) return { left: '50px', top: '75px', gap: '28px' }
  if (isShowingPwd.value) return { left: '50px', top: '85px', gap: '28px' }
  return { left: orangeEyesPos.left, top: orangeEyesPos.top, gap: '28px' }
})

const yellowEyesStyle = computed(() => {
  if (isLoginError.value) return { left: '35px', top: '45px', gap: '20px' }
  if (isLookingAway.value) return { left: '20px', top: '30px', gap: '20px' }
  if (isShowingPwd.value) return { left: '20px', top: '35px', gap: '20px' }
  return { left: yellowEyesPos.left, top: yellowEyesPos.top, gap: '20px' }
})

const orangeMouthStyle = computed(() => {
  if (isLoginError.value) return { left: `${80 + orangePos.faceX}px`, top: '130px' }
  return { left: '90px', top: '120px' }
})

const yellowMouthStyle = computed(() => {
  if (isLoginError.value) return { left: '30px', top: '92px', transform: 'rotate(-8deg)' }
  if (isLookingAway.value) return { left: '15px', top: '78px', transform: 'rotate(0deg)' }
  if (isShowingPwd.value) return { left: '10px', top: '88px', transform: 'rotate(0deg)' }
  return { left: yellowMouthPos.left, top: yellowMouthPos.top, transform: `rotate(${yellowMouthPos.rotate})` }
})

function faceFromEl(el: HTMLElement | undefined) {
  if (!el) return { faceX: 0, faceY: 0, bodySkew: 0 }
  const { cx, cy } = rectCenter(el.getBoundingClientRect(), 1 / 3)
  return calcFaceOffset(cx, cy, mouseX.value, mouseY.value)
}

function pupilFromEl(el: HTMLElement | undefined, maxDist: number) {
  if (!el) return { x: 0, y: 0 }
  const { cx, cy } = rectCenter(el.getBoundingClientRect())
  return calcPupilOffset(cx, cy, mouseX.value, mouseY.value, maxDist)
}

function updateCharacters() {
  Object.assign(purplePos, faceFromEl(charPurpleRef.value))
  Object.assign(blackPos, faceFromEl(charBlackRef.value))
  Object.assign(orangePos, faceFromEl(charOrangeRef.value))
  Object.assign(yellowPos, faceFromEl(charYellowRef.value))

  const lookingAway = isLookingAway.value
  const showingPwd = isShowingPwd.value

  if (isLoginError.value) {
    purplePupilTransform.value = 'translate(-3px, 4px)'
  } else if (lookingAway) {
    purplePupilTransform.value = 'translate(-5px, -5px)'
  } else if (showingPwd) {
    const px = isPurplePeeking.value ? 4 : -4
    const py = isPurplePeeking.value ? 5 : -4
    purplePupilTransform.value = `translate(${px}px, ${py}px)`
  } else if (isLookingAtEachOther.value) {
    purplePupilTransform.value = 'translate(3px, 4px)'
  } else {
    const po = pupilFromEl(charPurpleRef.value?.querySelector('.eyeball') as HTMLElement, 5)
    purplePupilTransform.value = `translate(${po.x}px, ${po.y}px)`
  }

  if (isLoginError.value) {
    blackPupilTransform.value = 'translate(-3px, 4px)'
  } else if (lookingAway) {
    blackPupilTransform.value = 'translate(-4px, -5px)'
  } else if (showingPwd) {
    blackPupilTransform.value = 'translate(-4px, -4px)'
  } else if (isLookingAtEachOther.value) {
    blackPupilTransform.value = 'translate(0px, -4px)'
  } else {
    const bo = pupilFromEl(charBlackRef.value?.querySelector('.eyeball') as HTMLElement, 4)
    blackPupilTransform.value = `translate(${bo.x}px, ${bo.y}px)`
  }

  if (isLoginError.value) {
    orangePupilTransform.value = 'translate(-3px, 4px)'
  } else if (lookingAway) {
    orangePupilTransform.value = 'translate(-5px, -5px)'
  } else if (showingPwd) {
    orangePupilTransform.value = 'translate(-5px, -4px)'
  } else {
    const oo = pupilFromEl(charOrangeRef.value?.querySelector('.bare-pupil') as HTMLElement, 5)
    orangePupilTransform.value = `translate(${oo.x}px, ${oo.y}px)`
  }

  if (isLoginError.value) {
    yellowPupilTransform.value = 'translate(-3px, 4px)'
  } else if (lookingAway) {
    yellowPupilTransform.value = 'translate(-5px, -5px)'
  } else if (showingPwd) {
    yellowPupilTransform.value = 'translate(-5px, -4px)'
  } else {
    const yo = pupilFromEl(charYellowRef.value?.querySelector('.bare-pupil') as HTMLElement, 5)
    yellowPupilTransform.value = `translate(${yo.x}px, ${yo.y}px)`
  }

  if (!isLoginError.value && !lookingAway && !showingPwd && !isLookingAtEachOther.value) {
    purpleEyesPos.left = `${45 + purplePos.faceX}px`
    purpleEyesPos.top = `${40 + purplePos.faceY}px`
    blackEyesPos.left = `${26 + blackPos.faceX}px`
    blackEyesPos.top = `${32 + blackPos.faceY}px`
    orangeEyesPos.left = `${82 + orangePos.faceX}px`
    orangeEyesPos.top = `${90 + orangePos.faceY}px`
    yellowEyesPos.left = `${52 + yellowPos.faceX}px`
    yellowEyesPos.top = `${40 + yellowPos.faceY}px`
  }

  if (!isLoginError.value && !lookingAway && !showingPwd) {
    yellowMouthPos.left = `${40 + yellowPos.faceX}px`
    yellowMouthPos.top = `${88 + yellowPos.faceY}px`
  }
}

function onMouseMove(e: MouseEvent) {
  mouseX.value = e.clientX
  mouseY.value = e.clientY
  if (!isTyping.value && !isLoginError.value) updateCharacters()
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

function clearTypingTimer() {
  if (typingTimer !== null) {
    clearTimeout(typingTimer)
    typingTimer = null
  }
}

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
  if (props.password.length > 0 && props.showPassword) {
    peekTimer = window.setTimeout(() => {
      if (props.password.length > 0 && props.showPassword) {
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

watch(
  () => props.showPassword,
  (shown) => {
    if (shown) schedulePeek()
    updateCharacters()
  },
)

onMounted(() => {
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

defineExpose({
  onEmailFocus,
  onEmailBlur,
  onEmailInput,
  onPasswordFocus,
  onPasswordBlur,
  onPasswordInput,
  triggerLoginError,
  updateCharacters,
})
</script>

<style scoped>
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

.yellow-mouth.shake-head {
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
</style>
