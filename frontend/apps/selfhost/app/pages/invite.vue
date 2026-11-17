<script setup lang="ts">
// 接一条邀请。被邀请的人这时还没有账号,所以这一页不走登录,也不带工作区段 ——
// 链接里那枚令牌就是凭据,工作区由引擎按它回答。
//
// 三种情形各自说清下一步:
// - 这个邮箱已经有账号了 → 不用再设密码,登录一次就能接(页面先把这件事说出来,
//   不然他会在"设密码"那一栏卡住)
// - 邀请过期 / 用过 / 撤销 → 给出能照着办的下一步,不是一个 404
// - 一切正常 → 设一次密码,接完直接进
definePageMeta({ layout: false })

const route = useRoute()

type State = 'loading' | 'pending' | 'done' | 'blocked'
interface Preview {
  email: string
  workspace: string
  workspace_name: string
  state: 'pending' | 'accepted' | 'revoked' | 'expired'
  note: string
  roles: { id: string, key: string, name: string }[]
  expires_at: string
  existing_account: boolean
}

const token = String(route.query.token || route.params.token || '')
const state = ref<State>('loading')
const invite = ref<Preview | null>(null)
const password = ref('')
const displayName = ref('')
const error = ref('')
const busy = ref(false)

async function load() {
  if (!token) {
    state.value = 'blocked'
    error.value = '这个链接里没有邀请令牌,回去问一下邀请你的人'
    return
  }
  try {
    const seen = await $fetch<Preview>(`/api/invitations/${encodeURIComponent(token)}`)
    invite.value = seen
    state.value = seen.state === 'pending' ? 'pending' : 'blocked'
    if (seen.state !== 'pending') error.value = seen.note
  } catch (e) {
    state.value = 'blocked'
    fail(e)
  }
}

function fail(err: unknown) {
  const e = err as { data?: { detail?: string }; message?: string }
  error.value = e.data?.detail || e.message || '出错了,再试一次'
}

async function accept() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await $fetch(`/api/invitations/${encodeURIComponent(token)}`, {
      method: 'POST',
      body: { password: password.value, display_name: displayName.value },
    })
    state.value = 'done'
    const ws = invite.value?.workspace
    await navigateTo(ws ? `/workspaces/${encodeURIComponent(ws)}/issues` : '/issues', { replace: true })
  } catch (e) {
    fail(e)
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <main class="mx-auto flex min-h-[100dvh] w-full max-w-[420px] flex-col justify-center gap-5 px-5">
    <header>
      <p class="eyebrow">INVITATION</p>
      <h1 class="mt-1 text-[20px] font-semibold tracking-tightest">加入工作区</h1>
      <p v-if="invite" class="mt-1 text-[12.5px] text-ink-soft">
        {{ invite.workspace_name || invite.workspace }} · {{ invite.email }}
      </p>
    </header>

    <p v-if="state === 'loading'" class="text-[12.5px] text-ink-soft">正在打开这条邀请…</p>

    <form v-else-if="state === 'pending' && invite" class="panel flex flex-col gap-3 p-4" @submit.prevent="accept">
      <p class="text-[12.5px] text-ink-soft">
        接完你就是这个工作区的成员<template v-if="invite.roles.length">
          ,角色:
          {{ invite.roles.map((r) => r.name).join(' / ') }}
        </template>。
      </p>
      <label v-if="!invite.existing_account" class="block">
        <span class="mb-1 block text-[11.5px] text-ink-soft">设一个密码(至少 8 位)</span>
        <input
          v-model="password"
          type="password"
          minlength="8"
          required
          class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
        >
      </label>
      <p v-else class="rounded-card border border-line/70 bg-well/50 px-3 py-2 text-[12px] text-ink-soft">
        这个邮箱已经有账号了 —— 接完之后用你自己的密码登录就行,别人的工作区不改你的密码。
      </p>
      <label class="block">
        <span class="mb-1 block text-[11.5px] text-ink-soft">在这个工作区里的名字(可留空)</span>
        <input
          v-model="displayName"
          type="text"
          class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
        >
      </label>
      <p v-if="error" class="text-[12px] text-coral">{{ error }}</p>
      <button type="submit" class="btn-solid h-9 text-[12.5px]" :disabled="busy">
        {{ busy ? '正在加入…' : '接受邀请' }}
      </button>
    </form>

    <div v-else-if="state === 'done'" class="panel p-4 text-[12.5px]">
      已经加入,正在带你进去…
    </div>

    <div v-else class="panel flex flex-col gap-2 p-4">
      <p class="text-[12.5px] text-coral">{{ error || '这条邀请不能用了' }}</p>
      <NuxtLink to="/login" class="text-[12px] text-ink-soft underline">去登录</NuxtLink>
    </div>
  </main>
</template>
