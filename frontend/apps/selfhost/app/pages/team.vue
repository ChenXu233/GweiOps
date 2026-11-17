<script setup lang="ts">
// 成员与角色。角色是数据:能建、能改权限、能删(预设除外)。
//
// 工作区在路径里,所以这里的每个调用都过 `scopePath`:它读的是选择器里那一个,
// 不是自己拼一次查询串 —— 一份东西两个写法的下场是两边说不到一起。
import { scopePath } from '@gwei/core/api/typed'

const { user: me, can } = useAuth()

interface Permission { key: string, description: string }
interface Role { id: string, key: string, name: string, description: string, permissions: string[], is_system: boolean, user_count?: number }
interface Member { id: string, email: string, display_name: string, status: string, is_sub_user: boolean, permissions: string[], scoped_permissions?: Record<string, string[]>, roles: { id: string, key: string, name: string }[], created_at: string, last_login_at: string }
interface AuditEntry { id: number, actor_name: string, action: string, target: string, detail: Record<string, unknown>, created_at: string }
interface Invite { id: string, email: string, state: 'pending' | 'accepted' | 'revoked' | 'expired', note: string, roles?: { id: string, key: string, name: string }[], created_at: string, expires_at: string }

const tab = ref<'members' | 'roles' | 'audit'>('members')
const permissions = ref<Permission[]>([])
const roles = ref<Role[]>([])
const members = ref<Member[]>([])
const audit = ref<AuditEntry[]>([])
const invites = ref<Invite[]>([])
const loading = ref(true)
const error = ref('')

const canManageUsers = computed(() => can('users.manage'))

// 能只授给某几个仓库的权限。判据在引擎侧(engine/auth/__init__.py 的
// SCOPED_PERMISSIONS),这里只决定勾选框旁边给不给仓库选择 —— 界面不给的话,
// 「按仓库分工」这个能力就只存在于文档里。
const SCOPED_KEYS = ['changes.read', 'changes.execute', 'changes.approve', 'changes.rollback']

// 当前工作区的仓库与项目:收窄时从这里挑,不让手打 slug。
// 两者共用 projects 的一个名字空间(租户内唯一),所以 scope 写的就是这里的
// slug —— 授权落在项目上时,它下面每一个仓库都算数(含以后新增的)。
const repos = ref<{ slug: string, name: string }[]>([])
const projects = ref<{ slug: string, name: string, repos: number }[]>([])
const scopedDraft = reactive<Record<string, string[]>>({})

function scopedOf(key: string): string[] {
  if (!scopedDraft[key]) scopedDraft[key] = []
  return scopedDraft[key]
}

function toggleScopeRepo(key: string, slug: string) {
  const picked = scopedOf(key)
  const i = picked.indexOf(slug)
  if (i >= 0) picked.splice(i, 1)
  else picked.push(slug)
}
const canManageRoles = computed(() => can('roles.manage'))

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [p, r, u, repoList, projectList] = await Promise.all([
      $fetch<{ permissions: Permission[] }>(scopePath('/api/permissions')),
      $fetch<{ roles: Role[] }>(scopePath('/api/roles')),
      $fetch<{ users: Member[] }>(scopePath('/api/users')),
      $fetch<{ items: { slug: string, name: string }[] }>(scopePath('/api/repos')),
      $fetch<{ items: { slug: string, name: string, repos: number }[] }>(scopePath('/api/projects')),
    ])
    permissions.value = p.permissions
    roles.value = r.roles
    members.value = u.users
    repos.value = repoList.items
    projects.value = projectList.items
    if (can('users.read')) {
      invites.value = (await $fetch<{ items: Invite[] }>(scopePath('/api/invitations'))).items
    }
    if (can('audit.read')) {
      audit.value = (await $fetch<{ entries: AuditEntry[] }>(scopePath('/api/audit'))).entries
    }
  } catch (e) {
    const err = e as { data?: { detail?: string } }
    error.value = err.data?.detail || '读不到成员与角色'
  } finally {
    loading.value = false
  }
}

// ---- 新建成员 -----------------------------------------------------------
const inviteOpen = ref(false)
const invite = reactive({ email: '', display_name: '', role_ids: [] as string[] })
const inviteError = ref('')
const inviteBusy = ref(false)

function toggleInviteRole(id: string) {
  const i = invite.role_ids.indexOf(id)
  if (i >= 0) invite.role_ids.splice(i, 1)
  else invite.role_ids.push(id)
}

// 发一条邀请。**不替他设密码**:密码是那个人自己的事,管理员替他想的那个
// 只能靠带外通道告诉他,还得在两处维护 —— 邀请链接把这两件事一起拿掉。
const inviteLink = ref('')
async function submitInvite() {
  inviteBusy.value = true
  inviteError.value = ''
  inviteLink.value = ''
  try {
    const res = await $fetch<{ invitation: Invite, token: string }>(
      scopePath('/api/invitations'),
      { method: 'POST', body: { email: invite.email, role_ids: invite.role_ids } },
    )
    // 链接拼在界面上,不靠发信:部署没配发信通道时这条路照样能用
    const base = import.meta.client ? window.location.origin : ''
    inviteLink.value = `${base}/invite?token=${encodeURIComponent(res.token)}`
    invite.email = ''
    invite.role_ids = []
    await loadAll()
  } catch (e) {
    const err = e as { data?: { detail?: string } }
    inviteError.value = err.data?.detail || '发不出去'
  } finally {
    inviteBusy.value = false
  }
}

async function copyInviteLink() {
  if (!import.meta.client || !inviteLink.value) return
  try {
    await navigator.clipboard.writeText(inviteLink.value)
    inviteError.value = '链接已复制'
  } catch {
    inviteError.value = '复制不了,手动选中上面的链接'
  }
}

async function revokeInvite(row: Invite) {
  try {
    await $fetch(scopePath(`/api/invitations/${row.id}`), { method: 'DELETE' })
    await loadAll()
  } catch (e) {
    const err = e as { data?: { detail?: string } }
    inviteError.value = err.data?.detail || '撤不回来'
  }
}

const STATE_LABEL: Record<Invite['state'], string> = {
  pending: '等对方接',
  accepted: '已接受',
  revoked: '已撤销',
  expired: '已过期',
}

// ---- 角色编辑 -----------------------------------------------------------
const editing = ref<Role | null>(null)
const draft = reactive({ name: '', description: '', permissions: [] as string[] })
const roleError = ref('')
const roleBusy = ref(false)

function openRole(role: Role) {
  editing.value = role
  draft.name = role.name
  draft.description = role.description
  draft.permissions = role.permissions.filter((p) => !p.includes('@'))
  for (const key of Object.keys(scopedDraft)) delete scopedDraft[key]
  for (const entry of role.permissions) {
    const [key = '', scope] = entry.split('@')
    if (key && scope) scopedOf(key).push(scope)
  }
  roleError.value = ''
}

function togglePerm(key: string) {
  const i = draft.permissions.indexOf(key)
  if (i >= 0) draft.permissions.splice(i, 1)
  else draft.permissions.push(key)
}

// 勾选框只勾"有没有这个权限";收窄的仓库写在旁边的 chips 上。两者拼成一份清单
// 交给服务端,格式 `权限@仓库slug`。
function collectedPermissions(): string[] {
  const out = [...draft.permissions]
  for (const key of SCOPED_KEYS) {
    const picked = draft.permissions.includes(key) ? [] : scopedDraft[key] || []
    for (const slug of picked) out.push(`${key}@${slug}`)
  }
  return out
}

async function saveRole() {
  if (!editing.value) return
  roleBusy.value = true
  roleError.value = ''
  try {
    await $fetch(scopePath(`/api/roles/${editing.value.id}`), {
      method: 'PUT',
      body: { name: draft.name, description: draft.description, permissions: collectedPermissions() },
    })
    editing.value = null
    await loadAll()
  } catch (e) {
    const err = e as { data?: { detail?: string } }
    roleError.value = err.data?.detail || '保存失败'
  } finally {
    roleBusy.value = false
  }
}

// 新建角色
const newRoleOpen = ref(false)
const newRole = reactive({ key: '', name: '', description: '' })
async function createRole() {
  roleError.value = ''
  try {
    await $fetch(scopePath('/api/roles'), {
      method: 'POST',
      body: { ...newRole, permissions: [] },
    })
    newRoleOpen.value = false
    newRole.key = ''
    newRole.name = ''
    newRole.description = ''
    await loadAll()
  } catch (e) {
    const err = e as { data?: { detail?: string } }
    roleError.value = err.data?.detail || '建不出来'
  }
}

// ---- 成员操作:停用 / 删除 / 改角色 --------------------------------------
const memberForRoles = ref<Member | null>(null)
const memberRoleIds = ref<string[]>([])
const memberScoped = ref<Record<string, string[]>>({})
const memberError = ref('')

function openMemberRoles(m: Member) {
  memberForRoles.value = m
  memberRoleIds.value = m.roles.map((r) => r.id)
  // 成员这一行自己的范围授权:与角色里那份是两栏,这里改的是他这一份
  memberScoped.value = {}
  for (const key of SCOPED_KEYS) {
    const picked = m.permissions.filter((p) => p.startsWith(`${key}@`)).map((p) => p.split('@')[1] ?? '')
    if (picked.length) memberScoped.value[key] = picked
  }
  memberError.value = ''
}

function toggleMemberScope(key: string, slug: string) {
  const picked = memberScoped.value[key] ?? (memberScoped.value[key] = [])
  const i = picked.indexOf(slug)
  if (i >= 0) picked.splice(i, 1)
  else picked.push(slug)
}

function toggleMemberRole(id: string) {
  const i = memberRoleIds.value.indexOf(id)
  if (i >= 0) memberRoleIds.value.splice(i, 1)
  else memberRoleIds.value.push(id)
}

async function saveMemberRoles() {
  if (!memberForRoles.value) return
  try {
    // 工作区级那份照旧;带范围的那份拼成 `权限@范围`,与角色里的写法一致
    const whole = memberForRoles.value.permissions.filter((p) => !p.includes('@'))
    const scoped: string[] = []
    for (const key of SCOPED_KEYS) {
      for (const slug of memberScoped.value[key] ?? []) scoped.push(`${key}@${slug}`)
    }
    await $fetch(scopePath(`/api/users/${memberForRoles.value.id}`), {
      method: 'PUT',
      body: { role_ids: memberRoleIds.value, permissions: [...whole, ...scoped] },
    })
    memberForRoles.value = null
    await loadAll()
  } catch (e) {
    const err = e as { data?: { detail?: string } }
    memberError.value = err.data?.detail || '保存失败'
  }
}

async function toggleStatus(m: Member) {
  try {
    await $fetch(scopePath(`/api/users/${m.id}`), {
      method: 'PUT',
      body: { status: m.status === 'active' ? 'disabled' : 'active' },
    })
    await loadAll()
  } catch (e) {
    const err = e as { data?: { detail?: string } }
    error.value = err.data?.detail || '改不了状态'
  }
}

async function removeMember(m: Member) {
  if (!window.confirm(`删掉 ${m.display_name || m.email}?这个动作不可撤销。`)) return
  try {
    await $fetch(scopePath(`/api/users/${m.id}`), { method: 'DELETE' })
    await loadAll()
  } catch (e) {
    const err = e as { data?: { detail?: string } }
    error.value = err.data?.detail || '删不掉'
  }
}

function when(iso: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso.slice(0, 16) : d.toLocaleString()
}

const permLabel = computed(() => {
  const map: Record<string, string> = {}
  for (const p of permissions.value) map[p.key] = p.description
  return map
})

onMounted(loadAll)
</script>

<template>
  <div class="flex flex-col gap-4 p-6">
    <header class="flex items-end justify-between gap-4">
      <div>
        <p class="eyebrow">ACCESS</p>
        <h1 class="mt-1 text-[20px] font-semibold tracking-tightest">成员与角色</h1>
        <p class="mt-1 text-[12.5px] text-ink-soft">角色是数据:能建、能改权限、能删。子账号的权限不会超过建它的人。</p>
      </div>
      <div class="flex items-center gap-2">
        <button
          v-if="tab === 'members' && canManageUsers"
          class="btn-solid h-8 px-3 text-[12px]"
          @click="inviteOpen = !inviteOpen"
        >
          添加成员
        </button>
        <button
          v-if="tab === 'roles' && canManageRoles"
          class="btn-solid h-8 px-3 text-[12px]"
          @click="newRoleOpen = !newRoleOpen"
        >
          新建角色
        </button>
      </div>
    </header>

    <div class="flex items-center gap-1 rounded-card border border-line p-1 text-[12px]">
      <button
        v-for="t in (['members', 'roles', 'audit'] as const)"
        :key="t"
        class="rounded-[6px] px-3 py-1.5"
        :class="tab === t ? 'bg-ink text-paper' : 'text-ink-soft hover:bg-line/40'"
        @click="tab = t"
      >
        {{ t === 'members' ? '成员' : t === 'roles' ? '角色' : '审计' }}
      </button>
    </div>

    <p v-if="error" class="rounded-card border border-coral/40 bg-coral/5 px-3 py-2 text-[12px] text-coral">{{ error }}</p>

    <!-- 成员 -->
    <section v-if="tab === 'members'" class="flex flex-col gap-3">
      <form
        v-if="inviteOpen"
        class="panel flex flex-col gap-3 p-4"
        @submit.prevent="submitInvite"
      >
        <div class="grid gap-3 sm:grid-cols-3">
          <label class="block">
            <span class="mb-1 block text-[11.5px] text-ink-soft">邮箱</span>
            <input v-model="invite.email" type="email" required class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong">
          </label>
          <label class="block">
            <span class="mb-1 block text-[11.5px] text-ink-soft">名字</span>
            <input v-model="invite.display_name" type="text" class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong">
          </label>
          <div class="block">
            <span class="mb-1 block text-[11.5px] text-ink-soft">密码</span>
            <p class="rounded-card border border-line/70 bg-well/50 px-3 py-2 text-[11.5px] text-ink-soft">
              由他自己设 —— 邀请链接里不存密码
            </p>
          </div>
        </div>
        <div>
          <span class="mb-1.5 block text-[11.5px] text-ink-soft">角色</span>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="r in roles"
              :key="r.id"
              type="button"
              class="chip"
              :class="invite.role_ids.includes(r.id) ? 'border-ink bg-ink text-paper' : ''"
              @click="toggleInviteRole(r.id)"
            >
              {{ r.name }}
            </button>
          </div>
        </div>
        <p v-if="inviteError" class="text-[11.5px]" :class="inviteError === '链接已复制' ? 'text-ink-soft' : 'text-coral'">{{ inviteError }}</p>
        <div v-if="inviteLink" class="flex flex-col gap-1.5">
          <p class="text-[11.5px] text-ink-soft">把这条链接交给对方,他自己设密码。链接只能用一次。</p>
          <code class="block break-all rounded-card border border-line bg-well px-3 py-2 text-[11px]">{{ inviteLink }}</code>
          <button type="button" class="btn-outline h-7 w-fit px-2.5 text-[11.5px]" @click="copyInviteLink">复制链接</button>
        </div>
        <div class="flex items-center gap-2">
          <button type="submit" class="btn-solid h-8 px-3 text-[12px]" :disabled="inviteBusy">
            {{ inviteBusy ? '发送中…' : '发出邀请' }}
          </button>
          <button type="button" class="btn-outline h-8 px-3 text-[12px]" @click="inviteOpen = false; inviteLink = ''">关闭</button>
        </div>
      </form>

      <!-- 发出去还没接的邀请。用它回答"我上礼拜明明发了邀请"。 -->
      <div v-if="invites.filter((i) => i.state === 'pending').length" class="panel flex flex-col divide-y divide-line/60">
        <div class="px-3.5 py-2 text-[11.5px] text-ink-soft">还没接的邀请</div>
        <div v-for="i in invites.filter((x) => x.state === 'pending')" :key="i.id" class="flex items-center gap-3 px-3.5 py-2.5">
          <span class="min-w-0 flex-1 truncate text-[12.5px]">{{ i.email }}</span>
          <span class="chip">{{ STATE_LABEL[i.state] }}</span>
          <span class="hidden text-[11px] text-ink-faint sm:block">{{ when(i.expires_at) }} 到期</span>
          <button v-if="canManageUsers" class="btn-outline h-7 px-2 text-[11.5px] text-coral" @click="revokeInvite(i)">
            撤销
          </button>
        </div>
      </div>

      <div v-for="m in members" :key="m.id" class="panel flex items-center gap-3 p-3.5">
        <span class="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-ink text-[12px] font-semibold text-paper">
          {{ (m.display_name || m.email).slice(0, 1) }}
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <span class="truncate text-[13px] font-medium">{{ m.display_name || m.email }}</span>
            <span v-if="m.is_sub_user" class="chip">子账号</span>
            <span v-if="m.status !== 'active'" class="chip border-coral/40 text-coral">已停用</span>
            <span v-if="me?.user_id === m.id" class="chip">你</span>
          </div>
          <div class="mt-0.5 truncate text-[11.5px] text-ink-faint">{{ m.email }}</div>
        </div>
        <div class="hidden flex-wrap justify-end gap-1 sm:flex">
          <span v-for="r in m.roles" :key="r.id" class="chip">{{ r.name }}</span>
        </div>
        <div class="w-32 shrink-0 text-right text-[11px] text-ink-faint">
          {{ m.last_login_at ? when(m.last_login_at) : '从未登录' }}
        </div>
        <div v-if="canManageUsers && me?.user_id !== m.id" class="flex shrink-0 items-center gap-1">
          <button class="btn-outline h-7 px-2 text-[11.5px]" @click="openMemberRoles(m)">角色</button>
          <button class="btn-outline h-7 px-2 text-[11.5px]" @click="toggleStatus(m)">
            {{ m.status === 'active' ? '停用' : '启用' }}
          </button>
          <button class="btn-outline h-7 px-2 text-[11.5px] text-coral" @click="removeMember(m)">删除</button>
        </div>
      </div>
    </section>

    <!-- 角色 -->
    <section v-else-if="tab === 'roles'" class="grid gap-3 sm:grid-cols-2">
      <form v-if="newRoleOpen" class="panel flex flex-col gap-2 p-4" @submit.prevent="createRole">
        <input v-model="newRole.key" required placeholder="key(小写,如 oncall)" class="rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong">
        <input v-model="newRole.name" required placeholder="显示名" class="rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong">
        <input v-model="newRole.description" placeholder="一句话说明" class="rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong">
        <div class="flex gap-2">
          <button type="submit" class="btn-solid h-8 px-3 text-[12px]">创建</button>
          <button type="button" class="btn-outline h-8 px-3 text-[12px]" @click="newRoleOpen = false">取消</button>
        </div>
        <p class="text-[11px] text-ink-faint">建完在卡片上勾权限。</p>
      </form>

      <div v-for="r in roles" :key="r.id" class="panel flex flex-col gap-2 p-4">
        <div class="flex items-center gap-2">
          <span class="text-[13px] font-medium">{{ r.name }}</span>
          <span class="chip">{{ r.key }}</span>
          <span v-if="r.is_system" class="chip">预设</span>
          <span class="ml-auto text-[11px] text-ink-faint">{{ r.user_count ?? 0 }} 人</span>
        </div>
        <p class="text-[11.5px] text-ink-faint">{{ r.description || '没有说明' }}</p>
        <div class="flex flex-wrap gap-1">
          <span v-for="p in r.permissions" :key="p" class="chip font-mono text-[10.5px]">{{ p.replace('@', ' · ') }}</span>
          <span v-if="!r.permissions.length" class="text-[11px] text-ink-faint">还没有权限</span>
        </div>
        <button v-if="canManageRoles" class="btn-outline mt-1 h-7 w-fit px-2.5 text-[11.5px]" @click="openRole(r)">
          编辑权限
        </button>
      </div>
    </section>

    <!-- 审计 -->
    <section v-else class="flex flex-col gap-1.5">
      <div v-for="a in audit" :key="a.id" class="panel flex items-center gap-3 px-3.5 py-2.5 text-[12px]">
        <span class="mono-label w-32 shrink-0">{{ when(a.created_at) }}</span>
        <span class="w-28 shrink-0 truncate font-medium">{{ a.actor_name || '—' }}</span>
        <span class="chip font-mono text-[10.5px]">{{ a.action }}</span>
        <span class="truncate text-ink-soft">{{ a.target }}</span>
      </div>
      <p v-if="!audit.length" class="text-[12px] text-ink-faint">还没有审计记录。</p>
    </section>

    <!-- 成员角色弹层 -->
    <div v-if="memberForRoles" class="fixed inset-0 z-40 grid place-items-center bg-ink/30 p-4" @click.self="memberForRoles = null">
      <div class="panel w-full max-w-[420px] p-5">
        <h2 class="text-[15px] font-semibold">改角色 · {{ memberForRoles.display_name || memberForRoles.email }}</h2>
        <div class="mt-3 flex flex-wrap gap-1.5">
          <button
            v-for="r in roles"
            :key="r.id"
            type="button"
            class="chip"
            :class="memberRoleIds.includes(r.id) ? 'border-ink bg-ink text-paper' : ''"
            @click="toggleMemberRole(r.id)"
          >
            {{ r.name }}
          </button>
        </div>

        <!-- 这一行自己的范围授权。与角色里那份是两栏:角色说"他大概是运维",
             这里说"他在这一个项目上能放行"。 -->
        <div class="mt-4 flex flex-col gap-2 border-t border-line/60 pt-3">
          <p class="text-[11.5px] text-ink-soft">只对某几个项目 / 仓库生效的权限</p>
          <div v-for="key in SCOPED_KEYS" :key="key" class="flex flex-col gap-1">
            <span class="font-mono text-[11px] text-ink-faint">{{ key }}</span>
            <span class="flex flex-wrap gap-1">
              <button
                v-for="project in projects"
                :key="`p-${project.slug}`"
                type="button"
                class="chip text-[10.5px]"
                :class="(memberScoped[key] ?? []).includes(project.slug) ? 'border-ink bg-ink text-paper' : ''"
                :title="`只在这个项目上给 ${key}(含以后新增的仓库)`"
                @click="toggleMemberScope(key, project.slug)"
              >
                {{ project.name }} · {{ project.repos }} 仓
              </button>
              <button
                v-for="repo in repos"
                :key="`r-${repo.slug}`"
                type="button"
                class="chip text-[10.5px]"
                :class="(memberScoped[key] ?? []).includes(repo.slug) ? 'border-ink bg-ink text-paper' : ''"
                :title="`只在这个仓库上给 ${key}`"
                @click="toggleMemberScope(key, repo.slug)"
              >
                {{ repo.name }}
              </button>
            </span>
          </div>
          <p class="text-[10.5px] text-ink-faint">
            都不勾就是这个工作区都能用。勾了就只在那里算数 —— 项目档覆盖它下面每个仓库,包括以后新加的。
          </p>
        </div>

        <p v-if="memberError" class="mt-2 text-[11.5px] text-coral">{{ memberError }}</p>
        <div class="mt-4 flex items-center gap-2">
          <button class="btn-solid h-8 px-3 text-[12px]" @click="saveMemberRoles">保存</button>
          <button class="btn-outline h-8 px-3 text-[12px]" @click="memberForRoles = null">取消</button>
        </div>
      </div>
    </div>

    <!-- 角色编辑弹层 -->
    <div v-if="editing" class="fixed inset-0 z-40 grid place-items-center bg-ink/30 p-4" @click.self="editing = null">
      <div class="panel w-full max-w-[560px] p-5">
        <div class="flex items-center gap-2">
          <h2 class="text-[15px] font-semibold">编辑角色 · {{ editing.name }}</h2>
          <button class="ml-auto text-[12px] text-ink-faint" @click="editing = null">关闭</button>
        </div>
        <div class="mt-3 grid gap-2">
          <input v-model="draft.name" class="rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong">
          <input v-model="draft.description" class="rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong">
        </div>
        <div class="mt-3 grid max-h-[40vh] gap-1 overflow-auto">
          <label
            v-for="p in permissions"
            :key="p.key"
            class="flex cursor-pointer items-start gap-2 rounded-card px-2 py-1.5 hover:bg-line/30"
          >
            <input
              type="checkbox"
              class="mt-0.5"
              :checked="draft.permissions.includes(p.key)"
              @change="togglePerm(p.key)"
            >
            <span class="min-w-0 flex-1">
              <span class="block font-mono text-[11.5px]">{{ p.key }}</span>
              <span class="block text-[11px] text-ink-faint">{{ p.description }}</span>
              <!-- 项目一档在上面:授在一个项目上,它下面每个仓库都算数,
                   包括以后新加进来的那个。 -->
              <span v-if="SCOPED_KEYS.includes(p.key) && projects.length > 1" class="mt-1 flex flex-wrap gap-1">
                <button
                  v-for="project in projects"
                  :key="project.slug"
                  type="button"
                  class="chip text-[10.5px]"
                  :class="scopedOf(p.key).includes(project.slug) ? 'border-ink bg-ink text-paper' : ''"
                  :title="`只在这个项目上给 ${p.key}(含以后新增的仓库)`"
                  @click.prevent="toggleScopeRepo(p.key, project.slug)"
                >
                  {{ project.name }} · {{ project.repos }} 仓
                </button>
              </span>
              <span v-if="SCOPED_KEYS.includes(p.key) && repos.length > 1" class="mt-1 flex flex-wrap gap-1">
                <button
                  v-for="repo in repos"
                  :key="repo.slug"
                  type="button"
                  class="chip text-[10.5px]"
                  :class="scopedOf(p.key).includes(repo.slug) ? 'border-ink bg-ink text-paper' : ''"
                  :title="`只在这个仓库上给 ${p.key}`"
                  @click.prevent="toggleScopeRepo(p.key, repo.slug)"
                >
                  {{ repo.name }}
                </button>
              </span>
            </span>
          </label>
        </div>
        <p class="mt-2 text-[11px] text-ink-faint">
          上一行是项目,下一行是仓库:勾了就只在那里算数,这个权限在别处仍然没有。项目档覆盖它下面每一个仓库,包括以后新加的;都不勾就是整个工作区。
        </p>
        <p v-if="roleError" class="mt-2 text-[11.5px] text-coral">{{ roleError }}</p>
        <div class="mt-4 flex items-center gap-2">
          <button class="btn-solid h-8 px-3 text-[12px]" :disabled="roleBusy" @click="saveRole">
            {{ roleBusy ? '保存中…' : '保存' }}
          </button>
          <button class="btn-outline h-8 px-3 text-[12px]" @click="editing = null">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>
