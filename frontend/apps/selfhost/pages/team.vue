<script setup lang="ts">
// 成员与角色。角色是数据:能建、能改权限、能删(预设除外)。
const { user: me, can } = useAuth()

interface Permission { key: string, description: string }
interface Role { id: string, key: string, name: string, description: string, permissions: string[], is_system: boolean, user_count?: number }
interface Member { id: string, email: string, display_name: string, status: string, is_sub_user: boolean, permissions: string[], roles: { id: string, key: string, name: string }[], created_at: string, last_login_at: string }
interface AuditEntry { id: number, actor_name: string, action: string, target: string, detail: Record<string, unknown>, created_at: string }

const tab = ref<'members' | 'roles' | 'audit'>('members')
const permissions = ref<Permission[]>([])
const roles = ref<Role[]>([])
const members = ref<Member[]>([])
const audit = ref<AuditEntry[]>([])
const loading = ref(true)
const error = ref('')

const canManageUsers = computed(() => can('users.manage'))
const canManageRoles = computed(() => can('roles.manage'))

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [p, r, u] = await Promise.all([
      $fetch<{ permissions: Permission[] }>('/api/permissions'),
      $fetch<{ roles: Role[] }>('/api/roles'),
      $fetch<{ users: Member[] }>('/api/users'),
    ])
    permissions.value = p.permissions
    roles.value = r.roles
    members.value = u.users
    if (can('audit.read')) {
      audit.value = (await $fetch<{ entries: AuditEntry[] }>('/api/audit')).entries
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
const invite = reactive({ email: '', password: '', display_name: '', role_ids: [] as string[] })
const inviteError = ref('')
const inviteBusy = ref(false)

function toggleInviteRole(id: string) {
  const i = invite.role_ids.indexOf(id)
  if (i >= 0) invite.role_ids.splice(i, 1)
  else invite.role_ids.push(id)
}

async function submitInvite() {
  inviteBusy.value = true
  inviteError.value = ''
  try {
    await $fetch('/api/users', {
      method: 'POST',
      body: {
        email: invite.email,
        password: invite.password,
        display_name: invite.display_name,
        role_ids: invite.role_ids,
      },
    })
    inviteOpen.value = false
    invite.email = ''
    invite.password = ''
    invite.display_name = ''
    invite.role_ids = []
    await loadAll()
  } catch (e) {
    const err = e as { data?: { detail?: string } }
    inviteError.value = err.data?.detail || '建不出来'
  } finally {
    inviteBusy.value = false
  }
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
  draft.permissions = [...role.permissions]
  roleError.value = ''
}

function togglePerm(key: string) {
  const i = draft.permissions.indexOf(key)
  if (i >= 0) draft.permissions.splice(i, 1)
  else draft.permissions.push(key)
}

async function saveRole() {
  if (!editing.value) return
  roleBusy.value = true
  roleError.value = ''
  try {
    await $fetch(`/api/roles/${editing.value.id}`, {
      method: 'PUT',
      body: { name: draft.name, description: draft.description, permissions: draft.permissions },
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
    await $fetch('/api/roles', {
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
          <label class="block">
            <span class="mb-1 block text-[11.5px] text-ink-soft">初始密码</span>
            <input v-model="invite.password" type="password" required minlength="8" class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong">
          </label>
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
        <p v-if="inviteError" class="text-[11.5px] text-coral">{{ inviteError }}</p>
        <div class="flex items-center gap-2">
          <button type="submit" class="btn-solid h-8 px-3 text-[12px]" :disabled="inviteBusy">
            {{ inviteBusy ? '创建中…' : '创建' }}
          </button>
          <button type="button" class="btn-outline h-8 px-3 text-[12px]" @click="inviteOpen = false">取消</button>
        </div>
      </form>

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
          <span v-for="p in r.permissions" :key="p" class="chip font-mono text-[10.5px]">{{ p }}</span>
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
            <span class="min-w-0">
              <span class="block font-mono text-[11.5px]">{{ p.key }}</span>
              <span class="block text-[11px] text-ink-faint">{{ p.description }}</span>
            </span>
          </label>
        </div>
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
