<script setup lang="ts">
// 登录 / 首启初始化。两种部署档位都走这一页。
// 库里没有用户时显示「创建管理员」,有用户之后显示登录。
definePageMeta({ layout: false })

const mode = ref<'loading' | 'setup' | 'login'>('loading')
const email = ref('')
const password = ref('')
const displayName = ref('')
const error = ref('')
const busy = ref(false)

async function loadStatus() {
  try {
    const s = await $fetch<{ needs_setup: boolean; authenticated: boolean }>('/api/auth/status')
    if (s.authenticated) {
      await navigateTo('/dashboard', { replace: true })
      return
    }
    mode.value = s.needs_setup ? 'setup' : 'login'
  } catch {
    mode.value = 'login'
  }
}

async function submit() {
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
    await navigateTo('/dashboard', { replace: true })
  } catch (err) {
    // 引擎的 detail 就是给人看的那句话,原样显示
    const e = err as { data?: { detail?: string; message?: string }; message?: string }
    error.value = e.data?.detail || e.data?.message || e.message || '出错了,再试一次'
  } finally {
    busy.value = false
  }
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
          <h1 class="text-[17px] font-semibold tracking-tightest">
            {{ mode === 'setup' ? '创建管理员' : '登录既未' }}
          </h1>
          <p class="mt-1 text-[12.5px] text-ink-soft">
            {{ mode === 'setup' ? '这台实例还没有用户,先建一个所有者。' : '夜里发生的事,早上只做判断。' }}
          </p>
        </div>
      </div>

      <form
        v-if="mode !== 'loading'"
        class="glass rounded-panel border border-line/70 p-6 shadow-xl shadow-ink/5"
        @submit.prevent="submit"
      >
        <label v-if="mode === 'setup'" class="mb-3 block">
          <span class="mb-1 block text-[11.5px] text-ink-soft">名字</span>
          <input
            v-model="displayName"
            type="text"
            autocomplete="name"
            placeholder="怎么称呼你"
            class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
          >
        </label>

        <label class="mb-3 block">
          <span class="mb-1 block text-[11.5px] text-ink-soft">邮箱</span>
          <input
            v-model="email"
            type="email"
            required
            autocomplete="username"
            placeholder="you@example.com"
            class="w-full rounded-card border border-line bg-well px-3 py-2 text-[12.5px] outline-none focus:border-line-strong"
          >
        </label>

        <label class="mb-4 block">
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

        <p v-if="error" class="mb-3 rounded-card border border-coral/40 bg-coral/5 px-3 py-2 text-[11.5px] text-coral">
          {{ error }}
        </p>

        <button type="submit" class="btn-solid h-10 w-full text-[13px]" :disabled="busy">
          <span v-if="busy">{{ mode === 'setup' ? '创建中…' : '登录中…' }}</span>
          <span v-else>{{ mode === 'setup' ? '创建管理员并进入' : '登录' }}</span>
        </button>
      </form>

      <p v-else class="text-center text-[12px] text-ink-faint">正在确认这台实例的状态…</p>

      <p class="mt-5 text-center text-[12px] leading-relaxed text-ink-faint">
        {{ mode === 'setup'
          ? '这个入口只在没有任何用户时出现,创建完成后自动关闭。'
          : '会话存在 HttpOnly cookie 里,退出即失效。' }}
      </p>
    </div>
  </div>
</template>
