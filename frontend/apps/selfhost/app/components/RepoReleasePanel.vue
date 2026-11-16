<script setup lang="ts">
// 一个仓库的发布管道:现在实际会怎样、这一仓覆盖了什么、哪些还继承上层。
//
// 它属于仓库,不属于工作区。设置页那份是"租户默认 + 所有仓库行"的总表,管的
// 是给整个工作区定调子;这里管的是一份代码自己怎么发。两处读写的是同一份数据,
// 所以保存完就在原地重取,不留第二份状态。
import { ReleaseSettingsApi } from '@gwei/core/api/client'

interface ReleaseRepoRow {
  set: boolean
  values: Record<string, string>
  effective: Record<string, string>
}
interface ReleaseConfig {
  fields: Record<string, string>
  modes: string[]
  compose_required: string[]
  effective: Record<string, string>
  tenant_default: { set: boolean; values: Record<string, string> }
  repos: Record<string, ReleaseRepoRow>
}

const props = defineProps<{ repo: string; canWrite: boolean }>()

const config = ref<ReleaseConfig | null>(null)
const draft = ref<Record<string, string>>({})
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const saved = ref(false)

const row = computed<ReleaseRepoRow | null>(() => config.value?.repos?.[props.repo] ?? null)
const effective = computed(
  () => row.value?.effective ?? config.value?.effective ?? {},
)

/** 这一仓没有行时,生效值就是继承来的:写进草稿的默认值也应该是那个。 */
function placeholder(field: string) {
  return row.value?.values[field] || effective.value[field] || ''
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    config.value = (await ReleaseSettingsApi.get()) as unknown as ReleaseConfig
    draft.value = {}
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function save() {
  const values = Object.fromEntries(Object.entries(draft.value).filter(([, v]) => v !== ''))
  if (!Object.keys(values).length) return
  saving.value = true
  error.value = ''
  try {
    await ReleaseSettingsApi.putRepo(props.repo, values)
    await load()
    saved.value = true
    setTimeout(() => (saved.value = false), 2000)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

async function clearRow() {
  saving.value = true
  error.value = ''
  try {
    await ReleaseSettingsApi.deleteRepo(props.repo)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

onMounted(load)
watch(() => props.repo, load)
</script>

<template>
  <section class="panel overflow-hidden">
    <div class="flex items-center gap-2 border-b border-line px-5 py-3.5">
      <AppIcon name="changes" :size="14" class="text-ink-faint" />
      <h2 class="text-[13px] font-semibold">发布管道</h2>
      <span v-if="config" class="chip">{{ effective.mode || '—' }}</span>
      <span
        v-if="row"
        class="chip"
        :class="row.set ? '' : 'text-ink-faint/70'"
      >
        {{ row.set ? '这一仓有覆盖' : '全继承上层' }}
      </span>
      <button class="btn-ghost btn-sm ml-auto" :disabled="loading" @click="load">
        <AppIcon name="refresh" :size="13" :class="loading ? 'animate-spin' : ''" />
      </button>
    </div>

    <div v-if="error" class="border-b border-coral/30 bg-coral/5 px-5 py-3 text-[12px] text-coral">
      {{ error }}
    </div>

    <div v-if="config" class="px-5 py-4">
      <!-- 生效值:先说"现在会怎样",再说"哪一层说了算" -->
      <div class="grid gap-x-6 gap-y-1 sm:grid-cols-2">
        <div
          v-for="(desc, field) in config.fields"
          :key="field"
          class="flex items-baseline justify-between gap-3"
        >
          <span class="text-[11.5px] text-ink-faint">{{ desc }}</span>
          <span class="truncate font-mono text-[11.5px]">
            {{ effective[field] || '—' }}
            <span v-if="row?.values[field]" class="ml-1 text-[10.5px] text-ink-faint">本仓</span>
          </span>
        </div>
      </div>
      <p
        v-if="effective.mode === 'compose' && config.compose_required.some((k) => !effective[k])"
        class="mt-2 text-[11.5px] text-coral"
      >
        compose 必填项缺失,这个仓库现在发不出去。
      </p>

      <div class="mt-4 grid gap-2 border-t border-line/60 pt-3.5 sm:grid-cols-2">
        <label v-for="(desc, field) in config.fields" :key="field" class="block">
          <span class="mb-1 block text-[11.5px] text-ink-soft">{{ desc }}</span>
          <input
            :value="draft[field] ?? ''"
            :placeholder="placeholder(field)"
            class="w-full rounded-card border border-line bg-well px-3 py-2 font-mono text-[11.5px] outline-none focus:border-line-strong"
            autocomplete="off"
            spellcheck="false"
            :disabled="!canWrite"
            @input="draft[field] = ($event.target as HTMLInputElement).value"
          >
        </label>
      </div>

      <div class="mt-3 flex items-center gap-2">
        <button class="btn-solid btn-sm" :disabled="!canWrite || saving" @click="save">
          保存这一仓
        </button>
        <button
          v-if="row?.set"
          class="btn-ghost btn-sm text-coral"
          :disabled="!canWrite || saving"
          @click="clearRow"
        >
          删掉覆盖
        </button>
        <span v-if="saved" class="text-[11.5px] text-ink-faint">已保存</span>
        <span class="ml-auto text-[11.5px] text-ink-faint">
          没填的字段继承工作区默认
        </span>
      </div>
    </div>

    <div v-else class="px-5 py-4 text-[12px] text-ink-faint">
      {{ loading ? '正在读这一仓的发布配置…' : '读不到发布配置。' }}
    </div>
  </section>
</template>
