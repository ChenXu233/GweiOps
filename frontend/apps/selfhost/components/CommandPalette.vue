<script setup lang="ts">
interface PaletteItem {
  to: string
  label: string
  icon: string
  hint?: string
}

interface PaletteGroup {
  title: string
  items: PaletteItem[]
}

const props = defineProps<{ items?: PaletteItem[]; groups?: PaletteGroup[] }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const q = ref('')
const inputEl = ref<HTMLInputElement | null>(null)
const active = ref(0)

interface Row {
  item: PaletteItem
  group: string
}

const rows = computed<Row[]>(() => {
  const needle = q.value.trim().toLowerCase()
  const all: Row[] = props.groups
    ? props.groups.flatMap((g) => g.items.map((item) => ({ item, group: g.title })))
    : (props.items ?? []).map((item) => ({ item, group: '' }))
  if (!needle) return all
  return all.filter(
    (r) =>
      (r.item.label + ' ' + r.item.to + ' ' + (r.item.hint || '')).toLowerCase().includes(needle),
  )
})

watch(rows, () => {
  active.value = 0
})

onMounted(() => {
  nextTick(() => inputEl.value?.focus())
})

function go(item?: PaletteItem) {
  if (!item) return
  emit('close')
  navigateTo(item.to)
}

function onKey(e: KeyboardEvent) {
  const total = rows.value.length
  if (e.key === 'Escape') {
    emit('close')
    return
  }
  if (e.key === 'ArrowDown' && total) {
    e.preventDefault()
    active.value = (active.value + 1) % total
  }
  if (e.key === 'ArrowUp' && total) {
    e.preventDefault()
    active.value = (active.value - 1 + total) % total
  }
  if (e.key === 'Enter') {
    e.preventDefault()
    go(rows.value[active.value]?.item)
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[60] flex items-start justify-center px-4 pt-[12vh]">
      <div class="absolute inset-0 animate-fade bg-ink/25 backdrop-blur-md" @click="emit('close')" />

      <div
        class="glass relative w-full max-w-[540px] animate-rise overflow-hidden rounded-2xl border border-line/70 shadow-pop"
        role="dialog"
        aria-modal="true"
      >
        <div class="flex items-center gap-2.5 border-b border-line/70 px-4 py-3">
          <AppIcon name="search" :size="16" class="text-ink-faint" />
          <input
            ref="inputEl"
            v-model="q"
            type="text"
            placeholder="跳转到..."
            class="w-full bg-transparent text-[14px] text-ink outline-none placeholder:text-ink-faint"
            @keydown="onKey"
          >
          <button class="kbd" @click="emit('close')">Esc</button>
        </div>

        <ul class="max-h-[52vh] overflow-auto p-1.5">
          <template v-for="(row, i) in rows" :key="row.item.to">
            <li
              v-if="i === 0 || rows[i - 1].group !== row.group"
              class="px-3 pb-1 pt-2.5 font-mono text-[9.5px] uppercase tracking-[0.2em] text-ink-faint"
            >
              {{ row.group }}
            </li>
            <li>
              <button
                class="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left transition-colors duration-150"
                :class="i === active ? 'bg-well text-ink' : 'text-ink-soft hover:bg-well/70'"
                @mouseenter="active = i"
                @click="go(row.item)"
              >
                <AppIcon :name="row.item.icon" :size="15" />
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-[13px] font-medium">{{ row.item.label }}</span>
                  <span v-if="row.item.hint" class="block truncate text-[11px] text-ink-faint">
                    {{ row.item.hint }}
                  </span>
                </span>
                <span class="font-mono text-[11px] text-ink-faint">{{ row.item.to }}</span>
                <AppIcon v-if="i === active" name="arrow-right" :size="13" class="text-ink-faint" />
              </button>
            </li>
          </template>

          <li v-if="!rows.length" class="px-3 py-8 text-center text-[12px] text-ink-faint">
            没有匹配的页面
          </li>
        </ul>
      </div>
    </div>
  </Teleport>
</template>
