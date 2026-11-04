// 语气只决定状态点的颜色;胶囊和描边颜色各页面自己拼,避免过度抽象。
export type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'idle'

export const toneDot: Record<Tone, string> = {
  ok: 'bg-ok',
  warn: 'bg-amber',
  bad: 'bg-coral',
  info: 'bg-brand',
  idle: 'bg-ink-faint',
}
