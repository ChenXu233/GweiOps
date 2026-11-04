<script setup lang="ts">
// 插件沙箱页面:资产由 engine 提供,iframe opaque origin 隔离。
// 沙箱内直接 fetch engine API 属跨域,所以走下面这条只读 postMessage 桥。
const route = useRoute()
const name = computed(() => String(route.params.name || ''))

interface PluginManifestPage {
  title: string
  entry: string
}
interface PluginManifest {
  name: string
  description: string
  pages: PluginManifestPage[]
}

const manifest = ref<PluginManifest | null>(null)
const notFound = ref(false)

onMounted(async () => {
  try {
    const plugins: PluginManifest[] = await $fetch('/api/plugins')
    manifest.value = plugins.find(p => p.name === name.value) || null
    if (!manifest.value?.pages?.length) notFound.value = true
  } catch {
    notFound.value = true
  }
})

const page = computed(() => manifest.value?.pages?.[0] || null)
const assetUrl = computed(() =>
  manifest.value && page.value ? '/api/plugins/' + manifest.value.name + '/ui/' + page.value.entry : '',
)

// ---------------------------------------------------------------------------
// 只读 postMessage 桥:白名单外的路径一律拒绝。
// ---------------------------------------------------------------------------
const BRIDGE_REPLY = 'gwei:bridge:response'
const ALLOWED_PREFIXES = ['/api/plugins', '/api/metrics', '/api/health']
const iframeRef = ref<HTMLIFrameElement | null>(null)

function bridgeAllowed(path: string): boolean {
  const [pathname] = path.split('?')
  return ALLOWED_PREFIXES.some(prefix => pathname.startsWith(prefix))
}

async function onBridgeMessage(ev: MessageEvent) {
  if (ev.source !== iframeRef.value?.contentWindow) return
  const msg = ev.data as { type: 'gwei:bridge:fetch'; id: number; path: string } | undefined
  if (!msg || msg.type !== 'gwei:bridge:fetch') return

  let payload: unknown
  if (typeof msg.path !== 'string' || !bridgeAllowed(msg.path)) {
    payload = { id: msg.id, ok: false, status: 403, body: { error: 'forbidden' } }
  } else {
    try {
      const body = await $fetch(msg.path)
      payload = { id: msg.id, ok: true, status: 200, body }
    } catch (e: any) {
      payload = { id: msg.id, ok: false, status: e?.statusCode || 502, body: null }
    }
  }
  iframeRef.value?.contentWindow?.postMessage(
    { type: BRIDGE_REPLY, ...payload },
    window.location.origin,
  )
}

onMounted(() => window.addEventListener('message', onBridgeMessage))
onUnmounted(() => window.removeEventListener('message', onBridgeMessage))
</script>

<template>
  <div class="space-y-4">
    <NuxtLink
      to="/marketplace"
      class="inline-flex items-center gap-1.5 text-[12px] font-medium text-ink-faint transition-colors hover:text-ink"
    >
      <AppIcon name="arrow-right" :size="13" class="rotate-180" />
      回到插件
    </NuxtLink>

    <div v-if="notFound" class="card">
      <EmptyState icon="plugins" title="这个插件没有页面" hint="它可能只提供了能力,没有声明 UI。" />
    </div>

    <template v-else-if="manifest && page">
      <header class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div class="mono-label">{{ manifest.name }}</div>
          <h1 class="mt-1.5 text-[24px] font-semibold leading-none tracking-tightest">{{ page.title }}</h1>
        </div>
        <span class="flex items-center gap-1.5 rounded-full border border-line bg-well px-2.5 py-1 font-mono text-[10.5px] text-ink-soft">
          <AppIcon name="shield-check" :size="12" />
          沙箱运行
        </span>
      </header>

      <div class="overflow-hidden rounded-panel border border-line bg-panel">
        <iframe
          ref="iframeRef"
          :src="assetUrl"
          class="block h-[calc(100vh-220px)] w-full"
          sandbox="allow-scripts"
          referrerpolicy="no-referrer"
          :title="page.title"
        />
      </div>
    </template>

    <div v-else class="space-y-3">
      <div class="h-6 w-40 animate-pulse rounded bg-well" />
      <div class="h-[420px] animate-pulse rounded-panel bg-well/60" />
    </div>
  </div>
</template>
