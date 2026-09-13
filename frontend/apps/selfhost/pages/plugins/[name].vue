<script setup lang="ts">
// 插件沙箱页面:资产由 engine 提供,iframe opaque origin 隔离。
// 已知边界:沙箱内直接 fetch engine API 属跨域,postMessage 桥随认证阶段提供。
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
  manifest.value && page.value ? `/api/plugins/${manifest.value.name}/ui/${page.value.entry}` : ''
)

// ---------------------------------------------------------------------------
// 只读 postMessage 桥:沙箱页面(opaque origin)无法直接 fetch engine API,
// 通过 parent 代理只读 GET。白名单外的路径一律拒绝。
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
  const msg = ev.data as
    | { type: 'gwei:bridge:fetch'; id: number; path: string }
    | undefined
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
    window.location.origin
  )
}

onMounted(() => window.addEventListener('message', onBridgeMessage))
onUnmounted(() => window.removeEventListener('message', onBridgeMessage))
</script>

<template>
  <div class="space-y-4">
    <div v-if="notFound" class="text-sm text-muted-foreground py-16 text-center">
      插件页面不存在。
    </div>

    <template v-else-if="manifest && page">
      <div class="flex items-baseline justify-between">
        <h1 class="text-2xl font-bold tracking-tight">{{ page.title }}</h1>
        <span class="text-xs text-muted-foreground">插件 {{ manifest.name }} · 沙箱运行</span>
      </div>
      <div class="border border-border rounded-lg overflow-hidden bg-card">
        <iframe
          ref="iframeRef"
          :src="assetUrl"
          class="w-full h-[calc(100vh-190px)] block"
          sandbox="allow-scripts"
          referrerpolicy="no-referrer"
          :title="page.title"
        />
      </div>
    </template>

    <div v-else class="text-sm text-muted-foreground py-16 text-center">加载中…</div>
  </div>
</template>
