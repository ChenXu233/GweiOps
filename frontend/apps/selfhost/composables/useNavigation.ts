import { ChangesApi, IssuesApi } from '@gwei/core/api/client'
import { mockChanges, mockIssues } from '@gwei/core/mock/index'

export interface NavItem {
  to: string
  label: string
  icon: string
  /** 侧边徽标:显示需要人处理的条数 */
  badge?: 'approvals' | 'issues'
  /** 一句话说明,鼠标悬停与命令面板里显示 */
  hint?: string
}

export interface NavGroup {
  title: string
  items: NavItem[]
}

/**
 * 全站唯一的导航表。
 * 顶栏不再放导航——功能一律进侧边,顶栏只留全局动作。
 */
export const navGroups: NavGroup[] = [
  {
    title: '工作区',
    items: [
      { to: '/dashboard', label: '控制室', icon: 'dashboard', hint: '系统态势与昨夜回顾' },
      { to: '/issues', label: '议题', icon: 'issues', badge: 'issues', hint: '从信号到方案的每一步' },
      { to: '/approvals', label: '待放行', icon: 'approvals', badge: 'approvals', hint: '不可逆或被策略拦下的变更' },
      { to: '/changes', label: '变更账本', icon: 'changes', hint: '每一次改变都是可回滚事件' },
    ],
  },
  {
    title: '接入',
    items: [
      { to: '/repos', label: '仓库', icon: 'repos', hint: '引擎订阅的仓库' },
      { to: '/signals', label: '信号源', icon: 'signals', hint: '从哪儿接收外部信号' },
      { to: '/marketplace', label: '插件', icon: 'plugins', hint: '能力由插件提供' },
    ],
  },
  {
    title: '系统',
    items: [
      { to: '/runs', label: '执行记录', icon: 'runs', hint: '每次执行会话的来龙去脉' },
      { to: '/observability', label: '指标观测', icon: 'observability', hint: '引擎与插件上报的实时指标' },
      { to: '/team', label: '成员与角色', icon: 'users', hint: '谁在用、能做什么、做过什么' },
      { to: '/settings', label: '设置', icon: 'settings', hint: '租户、通知与外观' },
    ],
  },
]

export function flattenNav(groups: NavGroup[] = navGroups): NavItem[] {
  return groups.flatMap((g) => g.items)
}

/**
 * 侧边徽标计数:待放行 + 待审。
 * 拉不到就保持 0——徽标只是提示,不该因为后端不在就让整页报错。
 */
export function useNavCounts() {
  const useMock = useRuntimeConfig().public.useMock === true
  const approvals = ref(0)
  const issues = ref(0)

  async function fetch() {
    try {
      if (useMock) {
        approvals.value = mockChanges.filter((c) => c.verdict === 'blocked').length
        issues.value = mockIssues.filter((i) => i.status === 'pending_review').length
        return
      }
      const [changes, issueRows] = await Promise.all([
        ChangesApi.list({ verdict: 'blocked', limit: 100 }),
        IssuesApi.list(),
      ])
      approvals.value = changes.total ?? changes.items.length
      issues.value = issueRows.filter((i) => i.status === 'pending_review').length
    } catch {
      approvals.value = 0
      issues.value = 0
    }
  }

  if (import.meta.client) {
    fetch()
    const timer = setInterval(fetch, 30_000)
    onUnmounted(() => clearInterval(timer))
  }

  function countFor(badge?: NavItem['badge']) {
    if (badge === 'approvals') return approvals.value
    if (badge === 'issues') return issues.value
    return 0
  }

  return { approvals, issues, countFor, refresh: fetch }
}

/** 命令面板开关:侧边栏与顶栏共用同一份状态。 */
export function usePalette() {
  const open = useState<boolean>('gwei-palette-open', () => false)
  function show() {
    open.value = true
  }
  function hide() {
    open.value = false
  }
  function toggle() {
    open.value = !open.value
  }
  return { open, show, hide, toggle }
}
