import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ApprovalsApi, describeFailure, statusOf } from '../api/approvals'
import { mockApprovals, mockApprove, mockVeto } from '../mock/approvals'
import type {
  ApprovalAction,
  ApprovalFailure,
  ApprovalItem,
  ApprovalNotice,
  ApprovalOutcome,
  BlockReasonKind,
  BlockReasonMeta,
} from '../types/approvals'
import type { Tone } from '../utils/tone'

/**
 * 阻断原因的读法。引擎只给一段自由文本 reason,
 * 这里按关键词把它归到几类里;归不进去的就归"其他",不硬套。
 */
const BLOCK_RULES: { kind: BlockReasonKind; label: string; tone: Tone; test: RegExp }[] = [
  {
    kind: 'irreversible',
    label: '不可逆',
    tone: 'bad',
    test: /不可逆|没有撤销|没有回滚|无法回滚|不可撤销|只能阻断/,
  },
  {
    kind: 'policy',
    label: '策略拦截',
    tone: 'warn',
    test: /策略|规则|不允许|禁止|合规|双人复核/,
  },
  {
    kind: 'window',
    label: '观察窗口',
    tone: 'info',
    test: /观察窗口|反应时间|等人工|等一个人|人工放行/,
  },
]

const OTHER_REASON: BlockReasonMeta = { kind: 'other', label: '其他阻断', tone: 'idle' }

const REASON_ORDER: BlockReasonKind[] = ['irreversible', 'policy', 'window', 'other']

/** 这条为什么停在这里。 */
export function blockReasonOf(row: ApprovalItem): BlockReasonMeta {
  if (row.verdict === 'irreversible') {
    return { kind: 'irreversible', label: '不可逆', tone: 'bad' }
  }
  const reason = row.reason || ''
  for (const rule of BLOCK_RULES) {
    if (rule.test.test(reason)) {
      return { kind: rule.kind, label: rule.label, tone: rule.tone }
    }
  }
  return OTHER_REASON
}

/** 成功之后的一句回执:照引擎自己的结论说话。 */
function describeOutcome(action: ApprovalAction, outcome: ApprovalOutcome): string {
  if (action === 'veto') return '已否决:这条不会执行,否决本身也写进了账本。'
  const verdict = outcome.latest.verdict
  if (verdict === 'irreversible') return '已放行。这条没有回滚能力,引擎如实记成不可逆。'
  if (verdict === 'rolled_back') return '已放行,但验证没过,引擎把它回滚了。'
  return '已放行。引擎照常读了窗口、照常验了结果。'
}

/**
 * 待放行队列。
 * 队列只有一类东西:引擎夜里做不了主、只能等人点头的改变。
 */
export function useApprovals() {
  const useMock = useRuntimeConfig().public.useMock === true

  const items = ref<ApprovalItem[]>([])
  const total = ref(0)
  const loading = ref(true)
  const error = ref<string | null>(null)

  /** 正在处理的那一条(哪一条、什么动作)。同一时刻只处理一条。 */
  const actingId = ref<string | null>(null)
  const actingAction = ref<ApprovalAction | null>(null)

  /** 一次失败的说明,以及成功之后的回执。 */
  const failure = ref<ApprovalFailure | null>(null)
  const notice = ref<ApprovalNotice | null>(null)

  let noticeTimer: ReturnType<typeof setTimeout> | null = null

  function clearNoticeTimer() {
    if (noticeTimer) {
      clearTimeout(noticeTimer)
      noticeTimer = null
    }
  }

  function pushNotice(text: string) {
    notice.value = { tone: 'ok', text }
    clearNoticeTimer()
    if (import.meta.client) {
      noticeTimer = setTimeout(() => {
        notice.value = null
        noticeTimer = null
      }, 6000)
    }
  }

  async function refresh() {
    loading.value = true
    error.value = null
    try {
      if (useMock) {
        items.value = mockApprovals.map((row) => ({ ...row }))
        total.value = items.value.length
        return
      }
      const data = await ApprovalsApi.list(100)
      items.value = data.items
      total.value = data.total
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  /**
   * 放行或否决。乐观更新:先把这条从队列里拿走,失败再放回原位。
   * 返回 true 表示引擎那边真的落账了。
   */
  async function act(action: ApprovalAction, id: string): Promise<boolean> {
    if (actingId.value) return false

    actingId.value = id
    actingAction.value = action
    failure.value = null
    notice.value = null
    clearNoticeTimer()

    const index = items.value.findIndex((row) => row.id === id)
    const snapshot = index >= 0 ? items.value[index] : null
    if (index >= 0) items.value.splice(index, 1)

    try {
      const outcome: ApprovalOutcome = useMock
        ? action === 'approve'
          ? await mockApprove(id)
          : await mockVeto(id)
        : action === 'approve'
          ? await ApprovalsApi.approve(id)
          : await ApprovalsApi.veto(id)

      total.value = Math.max(0, total.value - 1)
      pushNotice(describeOutcome(action, outcome))
      return true
    } catch (e) {
      if (snapshot) items.value.splice(Math.min(index, items.value.length), 0, snapshot)
      const status = statusOf(e)
      failure.value = { action, id, message: describeFailure(action, status), status }
      return false
    } finally {
      actingId.value = null
      actingAction.value = null
    }
  }

  function approve(id: string): Promise<boolean> {
    return act('approve', id)
  }

  function veto(id: string): Promise<boolean> {
    return act('veto', id)
  }

  /** 按阻断原因归类,给页首那排胶囊用。 */
  const groups = computed<(BlockReasonMeta & { count: number })[]>(() => {
    const counts = new Map<BlockReasonKind, number>()
    for (const row of items.value) {
      const kind = blockReasonOf(row).kind
      counts.set(kind, (counts.get(kind) ?? 0) + 1)
    }
    return REASON_ORDER.filter((kind) => counts.has(kind)).map((kind) => {
      const meta = BLOCK_RULES.find((rule) => rule.kind === kind) ?? OTHER_REASON
      return { ...meta, count: counts.get(kind) ?? 0 }
    })
  })

  onMounted(() => {
    void refresh()
  })
  onUnmounted(clearNoticeTimer)

  return {
    items,
    total,
    loading,
    error,
    actingId,
    actingAction,
    failure,
    notice,
    groups,
    refresh,
    approve,
    veto,
  }
}
