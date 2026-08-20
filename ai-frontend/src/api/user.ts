import { interviewMode } from '../config/api'

export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  nickName: string
  registerPassword: string
  checkCodeKey: string
  checkCode: string
}

export interface AuthResponse {
  user: {
    userId: string
    nickname: string
    avatar: string
    token: string
    tokenExpiresAt: number
    fansCount: number
    currentCoinCount: number
    focusCount: number
  }
}

function getBaseUrl(): string {
  return interviewMode.enabled
    ? interviewMode.pythonApi
    : ''  // 相对路径 → 经由 proxy/nginx 转发
}

export async function login(data: LoginRequest): Promise<AuthResponse> {
  const response = await fetch(`${getBaseUrl()}/ai/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
  })

  if (!response.ok) {
    let detail = ''
    try {
      const error = await response.json()
      detail = error.detail || ''
    } catch {
      const text = await response.text().catch(() => '')
      throw new Error(`登录失败 (${response.status})${text ? ': ' + text.slice(0, 100) : ''}`)
    }
    throw new Error(detail || '登录失败')
  }

  interface LoginRawResponse {
    user: AuthResponse['user']
  }

  let result: LoginRawResponse
  try {
    result = await response.json() as LoginRawResponse
  } catch {
    const text = await response.text().catch(() => '')
    throw new Error(`服务器返回了非 JSON 响应${text ? ': ' + text.slice(0, 120) : ''}`)
  }

  return {
    user: {
      ...result.user,
      fansCount: result.user.fansCount ?? 0,
      currentCoinCount: result.user.currentCoinCount ?? 0,
      focusCount: result.user.focusCount ?? 0,
    },
  }
}

export async function register(_data: RegisterRequest): Promise<AuthResponse> {
  throw new Error('注册功能未实现，请联系管理员')
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${getBaseUrl()}/ai/logout`, {
      method: 'POST',
      credentials: 'include',  // 携带/清除 httpOnly cookie
    })
  } catch {
    /* 网络异常时本地状态仍会清理，后端 cookie 靠 TTL 过期 */
  }
}