<script setup lang="ts">
// 登录 / 首启初始化 / 自助注册 / 找回密码。四种部署档位都走这一页。
// 注册与找回能不能用,由引擎的 /api/auth/registration/policy 说 —— 页面不猜。
definePageMeta({ layout: false })

const route = useRoute()

type Mode = 'loading' | 'setup' | 'login' | 'register' | 'reset' | 'reset-confirm'
interface Policy {
  enabled: boolean
  methods: string[]
  requires_verification: boolean
  code_ttl_minutes: number
  oidc: { available: boolean, label: string }
}

const mode = ref<Mode>('loading')
const policy = ref<Policy | null>(null)
const email = ref('')
const phone = ref('')
const method = ref<'email' | 'phone'>('email')
const password = ref('')
const displayName = ref('')
const code = ref('')
const resetToken = ref('')
const newPassword = ref('')
const error = ref('')
const busy = ref(false)
const notice = ref('')

const identifier = computed(() => (method.value === 'email' ? email.value : phone.value))
const canOidc = computed(() => !!policy.value?.oidc.available)

// 文案跟着模式走一处定义,模板里不再堆三目
const COPY: Record<string, { title: string, subtitle: string, submit: string, busy: string }> = {
  setup: {
    title: '创建管理员',
    subtitle: '这台实例还没有用户,先建一个所有者。',
    submit: '创建管理员并进入',
    busy: '创建中…',
  },
  login: { title: '登录既未', subtitle: '夜里发生的事,早上只做判断。', submit: '登录', busy: '登录中…' },
  register: {
    title: '注册既未',
    subtitle: '注册完成后按默认角色进来,权限由管理员再调。',
    submit: '注册并进入',
    busy: '注册中…',
  },
  reset: {
    title: '找回密码',
    subtitle: '填注册用的邮箱,我们会发一封带链接的信。',
    submit: '发送重置邮件',
    busy: '发送中…',
  },
  'reset-confirm': {
    title: '设置新密码',
    subtitle: '这一链接只能用一次,设置完自动登录。',
    submit: '设置新密码',
    busy: '提交中…',
  },
}
const FALLBACK = {
  title: '登录既未',
  subtitle: '',
  submit: '登录',
  busy: '处理中…',
}
const copy = computed(() => COPY[mode.value] ?? FALLBACK)
const title = computed(() => copy.value.title)
const subtitle = computed(() => copy.value.subtitle)
const submitLabel = computed(() => copy.value.submit)
const busyLabel = computed(() => copy.value.busy)
const footer = computed(() => {
  if (mode.value === 'setup') return '这个入口只在没有任何用户时出现,创建完成后自动关闭。'
  if (mode.value === 'register') return '注册开着的时候才有这一页;管理员可以在设置里关掉它。'
  return '会话存在 HttpOnly cookie 里,退出即失效。'
})

async function loadStatus() {
  try {
    const [s, p] = await Promise.all([
      $fetch<{ needs_setup: boolean; authenticated: boolean }>('/api/auth/status'),
      $fetch<Policy>('/api/auth/registration/policy').catch(() => null),
    ])
    policy.value = p
    if (method.value === 'phone' && !p?.methods.includes('phone')) method.value = 'email'
    if (s.authenticated) {
      await navigateTo('/issues', { replace: true })
      return
    }
    resetToken.value = String(route.query.reset || '')
    if (resetToken.value) {
      mode.value = 'reset-confirm'
      return
    }
    if (route.query.oauth_error) {
      error.value = String(route.query.oauth_error)
    }
    mode.value = s.needs_setup ? 'setup' : 'login'
  } catch {
    mode.value = 'login'
  }
}

function fail(err: unknown) {
  // 引擎的 detail 就是给人看的那句话,原样显示
  const e = err as { data?: { detail?: string; message?: string }; message?: string }
  error.value = e.data?.detail || e.data?.message || e.message || '出错了,再试一次'
}

async function to(mode_: Mode) {
  error.value = ''
  notice.value = ''
  mode.value = mode_
}

// ---- 登录 / 首启 ----
async function submitAuth() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    if (mode.value === 'setup') {
      await $fetch('/api/auth/setup', {
        method: 'POST',
        body: { email: email.value, password: password.value, display_name: displayName.value },
      })
    } else {
      await $fetch('/api/auth/login', {
        method: 'POST',
        body: { email: email.value, password: password.value },
      })
    }
    await navigateTo('/issues', { replace: true })
  } catch (err) {
    fail(err)
  } finally {
    busy.value = false
  }
}

// ---- 注册:先要码,再核验建号 ----
async function requestCode() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const res = await $fetch<{ ttl_minutes: number; test_code?: string }>(
      '/api/auth/register/start',
      { method: 'POST', body: { method: method.value, contact: identifier.value, purpose: 'register' } },
    )
    // 配了固定码的实例会回显;那是有意为之,直接填上省一步
    if (res.test_code) code.value = res.test_code
    notice.value = `验证码已发到 ${identifier.value},${res.ttl_minutes} 分钟内有效`
  } catch (err) {
    fail(err)
  } finally {
    busy.value = false
  }
}

async function submitRegister() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await $fetch('/api/auth/register/verify', {
      method: 'POST',
      body: {
        method: method.value,
        contact: identifier.value,
        code: code.value,
        display_name: displayName.value,
        password: password.value,
      },
    })
    await navigateTo('/issues', { replace: true })
  } catch (err) {
    fail(err)
  } finally {
    busy.value = false
  }
}

// ---- 找回密码 ----
async function requestReset() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const res = await $fetch<{ note: string }>('/api/auth/password/reset', {
      method: 'POST',
      body: { email: email.value },
    })
    notice.value = res.note
  } catch (err) {
    fail(err)
  } finally {
    busy.value = false
  }
}

async function submitReset() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await $fetch('/api/auth/password/reset/complete', {
      method: 'POST',
      body: { token: resetToken.value, new_password: newPassword.value },
    })
    await navigateTo('/issues', { replace: true })
  } catch (err) {
    fail(err)
  } finally {
    busy.value = false
  }
}

function oidcLogin() {
  window.location.href = '/api/auth/oidc/authorize'
}

onMounted(loadStatus)
</script>

<template>
  <div class="relative flex min-h-screen items-center justify-center overflow-hidden bg-paper px-5">
    <div class="grid-bg pointer-events-none absolute inset-0" />

    <div class="relative w-full max-w-[400px]">
      <div class="mb-6 flex flex-col items-center gap-3">
        <span class="relative grid h-11 w-11 place-items-center rounded-[14px] bg-ink text-paper">
          <span class="font-mono text-[15px] font-semibold leading-none">未</span>
          <span class="absolute right-[4px] top-[4px] h-[6px] w-[6px] rounded-full bg-lime" />
        </span>
        <div class="text-center">
          <h1 class="text-[17px] font-semibold tracking-tightest">{{ title }}</h1>
          <p class="mt-1 text-[12.5px] text-ink-soft">{{ subtitle }}</p>
        </div>
      </div>

      <form
        v-if="mode !== 'loading'"
        class="glass rounded-panel border border-line/70 p-6 shadow-xl shadow-ink/5"
        @submit.prevent="
          mode === 'register'
            ? submitRegister()
            : mode === 'reset'
              ? requestReset()
              : mode === 'reset-confirm'
                ? submitReset()
                : submitAuth()
        "
      >
        <!-- 注册方式:邮箱 / 手机号。没有第二种方式时不显示切换。 -->
        <div
          v-if="mode === 'register' && (policy?.methods.length || 0) > 1"
          class="mb-3 flex gap-1 rounded-card border border-line bg-well p-1"
        >
          <button
            v-for="m in policy?.methods.filter((x) => x !== 'oidc') || []"
            :key="m"
            type="button"
            class="flex-1 rounded-[6px] py-1.5 text-[12px] transition-colors"
            :class="method === m ? 'bg-ink text-paper' : 'text-ink-soft hover:text-ink'"
            @click="method = m === 'phone' ? 'phone' : 'email'"
          >
            {{ m === 'email' ? '邮箱' : '手机号' }}
          </button>
        </div>

        <label v-if="mode === 'setup' || mode === 'register'" class="mb-3 block">
          <span class="mb-1 block text-[11.5px] text-ink-soft">名字</span>
          <input
            v-model="displayName"
            type="text"
            autocomplete="name"
            placeholder="怎么称呼你"
            class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
          >
        </label>

        <label v-if="mode !== 'reset-confirm'" class="mb-3 block">
          <span class="mb-1 block text-[11.5px] text-ink-soft">
            {{ mode === 'register' && method === 'phone' ? '手机号' : '邮箱' }}
          </span>
          <input
            v-if="mode === 'register' && method === 'phone'"
            v-model="phone"
            type="tel"
            required
            autocomplete="tel"
            placeholder="+86 138 0000 0000"
            class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
          >
          <input
            v-else
            v-model="email"
            type="email"
            required
            autocomplete="username"
            placeholder="you@example.com"
            class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
          >
        </label>

        <label v-if="mode === 'login' || mode === 'setup'" class="mb-4 block">
          <span class="mb-1 block text-[11.5px] text-ink-soft">密码</span>
          <input
            v-model="password"
            type="password"
            required
            :autocomplete="mode === 'setup' ? 'new-password' : 'current-password'"
            :placeholder="mode === 'setup' ? '至少 8 位' : ''"
            class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
          >
        </label>

        <template v-if="mode === 'register'">
          <label class="mb-3 block">
            <span class="mb-1 block text-[11.5px] text-ink-soft">密码</span>
            <input
              v-model="password"
              type="password"
              required
              autocomplete="new-password"
              placeholder="至少 8 位"
              class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
            >
          </label>

          <label v-if="policy?.requires_verification" class="mb-3 block">
            <span class="mb-1 flex items-center justify-between text-[11.5px] text-ink-soft">
              <span>验证码</span>
              <button type="button" class="text-ink-faint hover:text-ink" :disabled="busy" @click="requestCode">
                获取验证码
              </button>
            </span>
            <input
              v-model="code"
              type="text"
              inputmode="numeric"
              required
              autocomplete="one-time-code"
              placeholder="6 位数字"
              class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
            >
          </label>
        </template>

        <label v-if="mode === 'reset-confirm'" class="mb-4 block">
          <span class="mb-1 block text-[11.5px] text-ink-soft">新密码</span>
          <input
            v-model="newPassword"
            type="password"
            required
            autocomplete="new-password"
            placeholder="至少 8 位"
            class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
          >
        </label>

        <p v-if="notice" class="mb-3 rounded-card border border-lime/40 bg-lime/5 px-3 py-2 text-[11.5px] text-ink-soft">
          {{ notice }}
        </p>
        <p v-if="error" class="mb-3 rounded-card border border-coral/40 bg-coral/5 px-3 py-2 text-[11.5px] text-coral">
          {{ error }}
        </p>

        <button type="submit" class="btn-solid h-10 w-full text-[13px]" :disabled="busy">
          <span v-if="busy">{{ busyLabel }}</span>
          <span v-else>{{ submitLabel }}</span>
        </button>

        <button
          v-if="mode === 'login' && canOidc"
          type="button"
          class="mt-2 h-10 w-full rounded-card border border-line text-[12.5px] text-ink-soft hover:text-ink"
          @click="oidcLogin"
        >
          {{ policy?.oidc.label || '用统一身份登录' }}
        </button>

        <div v-if="mode !== 'setup' && mode !== 'reset-confirm'" class="mt-3 flex justify-between text-[11.5px] text-ink-faint">
          <button
            v-if="mode === 'login' && policy?.enabled"
            type="button"
            class="hover:text-ink"
            @click="to('register')"
          >
            没有账号?注册
          </button>
          <span v-else-if="mode === 'register'" />
          <button
            v-if="mode === 'login' && policy?.enabled"
            type="button"
            class="hover:text-ink"
            @click="to('reset')"
          >
            忘记密码
          </button>
          <button
            v-if="mode === 'register' || mode === 'reset'"
            type="button"
            class="hover:text-ink"
            @click="to('login')"
          >
            返回登录
          </button>
        </div>
      </form>

      <p v-else class="text-center text-[12px] text-ink-faint">正在确认这台实例的状态…</p>

      <p class="mt-5 text-center text-[12px] leading-relaxed text-ink-faint">{{ footer }}</p>
    </div>
  </div>
</template>
