import { IssuesApi } from '@gwei/core/api/client'
import { mockIssueBoard } from '@gwei/core/mock/index'

export interface NavItem {
  to: string
  label: string
  icon: string
  /** 侧边徽标:显示需要人处理的条数。全站只有一个徽标。 */
  badge?: 'waiting'
  /** 一句话说明,鼠标悬停与命令面板里显示 */
  hint?: string
}

export interface NavGroup {
  title: string
  items: NavItem[]
}

/**
 * 全站唯一的导航表:三组,命令面板也直接读它。
 * 顶栏不再放导航——功能一律进侧边,顶栏只留全局动作。
 *
 * 这些页面都在"当前工作区"之内:侧边栏最上面那个选择器换的是工作区,
 * 换完还是同一张导航表。理由见[工作区模型](../../../../../docs/explanation/workspace-model.md)。
 *
 * 控制室、待放行、执行记录都不在这里了:它们问的都是"要我做什么 / 做了什么",
 * 答案在议题板的三段与议题详情的时间线里。页面文件还在,但没有入口——要不要
 * 删掉它们是个单独的决定,见工作分解。
 */
export const navGroups: NavGroup[] = [
  {
    title: '工作区',
    items: [
      { to: '/issues', label: '议题', icon: 'issues', badge: 'waiting', hint: '要你处理的和正在跑的' },
      { to: '/changes', label: '变更账本', icon: 'changes', hint: '每一次改变都是可回滚事件' },
    ],
  },
  {
    title: '接入',
    items: [
      { to: '/repos', label: '仓库', icon: 'repos', hint: '这个工作区里有哪些仓库' },
      { to: '/signals', label: '信号源', icon: 'signals', hint: '从哪儿接收外部信号' },
      { to: '/marketplace', label: '插件', icon: 'plugins', hint: '能力由插件提供' },
      { to: '/mcp', label: 'MCP 接入', icon: 'key-round', hint: '给外界的 agent 发密钥' },
    ],
  },
  {
    title: '工作区管理',
    items: [
      { to: '/workspaces', label: '工作区', icon: 'layers', hint: '这个账号能进的工作区与开通进度' },
      { to: '/observability', label: '指标观测', icon: 'observability', hint: '引擎与插件上报的实时指标' },
      { to: '/team', label: '成员', icon: 'users', hint: '谁在用、能做什么、做过什么' },
      { to: '/settings', label: '设置', icon: 'settings', hint: '这个工作区的接入、密钥与外观' },
    ],
  },
]

export function flattenNav(groups: NavGroup[] = navGroups): NavItem[] {
  return groups.flatMap((g) => g.items)
}

/**
 * 侧边徽标计数:只有"等我"这一条。
 * 拉不到就保持 0——徽标只是提示,不该因为后端不在就让整页报错。
 */
export function useNavCounts() {
  const useMock = useRuntimeConfig().public.useMock === true
  const waiting = ref(0)

  async function fetch() {
    try {
      waiting.value = useMock
        ? mockIssueBoard.counts.waiting ?? 0
        : (await IssuesApi.board({ limit: 200 })).counts.waiting ?? 0
    } catch {
      waiting.value = 0
    }
  }

  if (import.meta.client) {
    fetch()
    const timer = setInterval(fetch, 30_000)
    onUnmounted(() => clearInterval(timer))
  }

  function countFor(badge?: NavItem['badge']) {
    return badge === 'waiting' ? waiting.value : 0
  }

  return { waiting, countFor, refresh: fetch }
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
