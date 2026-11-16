// packages/core/composables/useMcpKeys.ts
//
// MCP 接入的三份数据:密钥清单、这个部署里有哪些资源、有哪些工具可授予。
// 三份都来自引擎 —— 资源名与工具清单是插件声明的,前端不自己编一套。
import { computed, ref } from 'vue'
import { ApiKeysApi } from '../api/client'

/** 一把密钥的事实。明文只在签发那一次的响应里,这里永远没有。 */
export interface McpKey {
  id: string
  name: string
  hint: string
  permissions: string[]
  tools: string[]
  bindings: string[]
  status: string
  created_at: string
  created_by: string
  last_used_at: string
  expires_at: string
}

/** 一个下游目标,以及它上面能执行哪些能力。 */
export interface McpResource {
  key: string
  capabilities: string[]
}

/** 一个可授予的工具:要什么权限、能作用在哪些资源上。 */
export interface McpTool {
  name: string
  label: string
  permission: string
  resources: string[]
  mutating: boolean
}

export interface PermissionOption {
  key: string
  description: string
}

/** 签发时勾的三样。空 bindings = 不限资源;空 tools = 不额外收窄。 */
export interface McpKeyDraft {
  name: string
  permissions: string[]
  bindings: string[]
  tools: string[]
  expires_at: string
}

/**
 * 一把密钥最终看得见哪些工具。三关与引擎的判据一一对应:
 * 权限够、资源够、白名单没把它排除。页面拿它做即时预览 —— 签之前就能看见
 * 对方会拿到什么清单,不用签完再去试。
 */
export function visibleTools(
  tools: McpTool[],
  draft: Pick<McpKeyDraft, 'permissions' | 'bindings' | 'tools'>,
): McpTool[] {
  const permissions = new Set(draft.permissions)
  const bindings = new Set(draft.bindings)
  const narrowed = new Set(draft.tools)
  return tools.filter((tool) => {
    if (!permissions.has(tool.permission)) return false
    // 工具说不出自己在哪个资源上(只读口就是这种):资源这一关不适用
    if (bindings.size && tool.resources.length) {
      if (!tool.resources.some((r) => bindings.has(r))) return false
    }
    if (narrowed.size && !narrowed.has(tool.name)) return false
    return true
  })
}

/** 从工具清单里反推权限名:兜底用,说明文字退化成了权限名本身。 */
function permissionOptionsFromTools(tools: McpTool[]): PermissionOption[] {
  const seen = new Set<string>()
  const out: PermissionOption[] = []
  for (const tool of tools) {
    if (!tool.permission || seen.has(tool.permission)) continue
    seen.add(tool.permission)
    out.push({ key: tool.permission, description: tool.permission })
  }
  return out
}

export function useMcpKeys() {
  const useMock = useRuntimeConfig().public.useMock === true
  const keys = ref<McpKey[]>([])
  const resources = ref<McpResource[]>([])
  const tools = ref<McpTool[]>([])
  const permissions = ref<PermissionOption[]>([])
  const defaultResource = ref('')
  const loading = ref(false)
  const error = ref('')

  // 接口给的是人话(哪里不合法);这里只去掉 "API error: 422" 这种前缀。
  function friendly(raw: string): string {
    return raw.replace(/^API error:\s*\d{3}\s*/, '').trim()
  }

  async function load() {
    if (useMock) return
    loading.value = true
    error.value = ''
    try {
      const [listed, resourceList, toolList] = await Promise.all([
        ApiKeysApi.list(),
        ApiKeysApi.resources(),
        ApiKeysApi.tools(),
      ])
      keys.value = (listed.items as unknown as McpKey[]) ?? []
      resources.value = (resourceList.resources as unknown as McpResource[]) ?? []
      defaultResource.value = resourceList.default ?? ''
      tools.value = (toolList.tools as unknown as McpTool[]) ?? []
      // 权限目录要会话身份才读得到;读不到就拿工具自己带的权限名兜住 ——
      // 少一段人话说明,不该让整页签不出密钥。
      try {
        const permList = await $fetch<{ permissions: PermissionOption[] }>('/api/permissions')
        permissions.value = permList.permissions ?? []
      } catch {
        permissions.value = permissionOptionsFromTools(tools.value)
      }
    } catch (e) {
      error.value = friendly(e instanceof Error ? e.message : String(e))
    } finally {
      loading.value = false
    }
  }

  async function issue(draft: McpKeyDraft) {
    const body = {
      name: draft.name.trim(),
      permissions: draft.permissions,
      tools: draft.tools,
      bindings: draft.bindings,
      expires_at: draft.expires_at,
    }
    const issued = (await ApiKeysApi.issue(body)) as unknown as McpKey & { key?: string }
    await load()
    return issued
  }

  async function revoke(id: string) {
    await ApiKeysApi.revoke(id)
    await load()
  }

  function permissionLabel(key: string): string {
    return permissions.value.find((p) => p.key === key)?.description ?? key
  }

  function toolLabel(name: string): string {
    return tools.value.find((t) => t.name === name)?.label ?? name
  }

  // 吊销的记录留着:谁签的、什么时候用过还看得见,只是不再进门
  const activeKeys = computed(() => keys.value.filter((k) => k.status !== 'revoked'))
  const revokedKeys = computed(() => keys.value.filter((k) => k.status === 'revoked'))

  return {
    useMock,
    keys,
    resources,
    tools,
    permissions,
    defaultResource,
    activeKeys,
    revokedKeys,
    loading,
    error,
    load,
    issue,
    revoke,
    permissionLabel,
    toolLabel,
    friendly,
  }
}
