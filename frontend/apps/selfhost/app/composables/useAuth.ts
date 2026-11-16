// 当前登录的人。侧边栏用它显示"谁在操作",退出也走这里。
//
// `/api/me` 回答的是一个人 + 他在每个工作区里的角色:人是全局的(一份凭据、一个
// 名字),角色是工作区给的。顶层的 `permissions` 只对**这次请求落在的那个工作区**
// 算数 —— 把几个工作区的权限并起来,是越权的起点。
export interface AuthMembership {
  workspace: string
  workspace_name: string
  user_id: string
  is_sub_user: boolean
  status: string
  roles: { id: string; key: string; name: string }[]
  permissions: string[]
  scoped_permissions: string[]
}

export interface AuthUser {
  email: string
  display_name: string
  workspace: string
  workspace_name: string
  user_id: string
  person_id: string
  permissions: string[]
  scoped_permissions: string[]
  roles: { id: string; key: string; name: string }[]
  workspaces: AuthMembership[]
  is_sub_user: boolean
}

// 演示模式没有引擎,也就没有身份:/api/me 一定 401。若照实处理,页面上所有写操作
// 都会消失,只能看到半张界面。这里给一个只活在演示里的身份;它同时是服务端与
// 客户端的初始值,否则首屏会和服务端渲染的对不上。
const DEMO_USER: AuthUser = {
  email: 'demo@example.com',
  display_name: '演示身份',
  workspace: 'default',
  workspace_name: '演示工作区',
  user_id: 'demo',
  person_id: 'demo',
  permissions: [],
  scoped_permissions: [],
  roles: [{ id: 'demo', key: 'owner', name: '所有者' }],
  workspaces: [],
  is_sub_user: false,
}

// 界面上的选择器换的是"看哪一道账",而工作区在路径里 —— 所以选择本身就是一次
// 导航:`/workspaces/{slug}/issues`。前端路由只是把 url 里那一段带着走,真正的
// 数据边界在引擎那侧(它按这一段判成员关系)。
let workspaceReader: () => string = () => ''

/** 由 `useWorkspaces()` 注册:`useAuth` 不该自己知道工作区是怎么存的。 */
export function setWorkspaceReader(read: () => string): void {
  workspaceReader = read
}

export function useAuth() {
  const useMock = useRuntimeConfig().public.useMock === true
  const user = useState<AuthUser | null>('auth-user', () => (useMock ? DEMO_USER : null))

  async function load() {
    if (useMock) return user.value
    try {
      // 工作区在路径里由调用层补;这里要的是"我是谁",不带工作区段也答得出来。
      const res = await $fetch<AuthUser>('/api/me')
      user.value = res
    } catch {
      try {
        const legacy = await $fetch<{ user: AuthUser }>('/api/auth/me')
        user.value = legacy.user
      } catch {
        user.value = null
      }
    }
    return user.value
  }

  async function logout() {
    await $fetch('/api/auth/logout', { method: 'POST' }).catch(() => undefined)
    user.value = null
    await navigateTo('/login', { replace: true })
  }

  /** 这个权限在当前工作区里算不算数。带范围的那份不算工作区级权限。 */
  function can(permission: string) {
    if (useMock) return true
    return !!user.value?.permissions.includes(permission)
  }

  /** 这个权限在某个项目 / 仓库上算不算数:`changes.approve@acme` 或工作区级。 */
  function canIn(permission: string, scope: string) {
    if (useMock) return true
    const held = user.value?.permissions ?? []
    if (held.includes(permission)) return true
    return (user.value?.scoped_permissions ?? []).includes(`${permission}@${scope}`)
  }

  return { user, load, logout, can, canIn }
}
