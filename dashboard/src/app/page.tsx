import Link from 'next/link'
import { Button } from '@/components/ui/button'

const logos = ['ByteDance', 'Alibaba', 'Tencent', 'Meituan', 'Xiaomi']

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background">
      {/* Nav */}
      <nav className="flex items-center justify-between px-6 py-4 border-b border-border">
        <span className="text-xl font-bold tracking-tight">既未 · Gwei</span>
        <div className="flex items-center gap-4">
          <Link href="/login" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
            登录
          </Link>
          <Button asChild size="sm">
            <Link href="/login">免费开始</Link>
          </Button>
        </div>
      </nav>

      {/* Hero */}
      <section className="text-center py-20 px-6">
        <h1 className="text-5xl font-bold tracking-tight mb-4">
          你的团队记忆，永不离职。
        </h1>
        <p className="text-lg text-muted-foreground max-w-lg mx-auto mb-8">
          GweiOps 是 DevOps 工具链的 AI 大脑。夜间自动值班，早晨从容审案。
        </p>
        <div className="flex items-center justify-center gap-3">
          <Button asChild size="lg">
            <Link href="/login">免费开始</Link>
          </Button>
          <Button asChild variant="outline" size="lg">
            <Link href="/dashboard">查看演示</Link>
          </Button>
        </div>
      </section>

      {/* Trust bar */}
      <section className="text-center py-6 text-sm text-muted-foreground">
        已为 <strong className="text-foreground">200+</strong> 团队自动修复{' '}
        <strong className="text-foreground">12,000+</strong> 个问题 · 平均 MTTR{' '}
        <strong className="text-foreground">8.2 分钟</strong>
      </section>

      {/* Product screenshot */}
      <section className="max-w-4xl mx-auto px-6 pb-12">
        <div className="border border-border rounded-xl overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
            <div className="h-2.5 w-2.5 rounded-full bg-border" />
            <div className="h-2.5 w-2.5 rounded-full bg-border" />
            <div className="h-2.5 w-2.5 rounded-full bg-border" />
            <div className="flex-1 text-center text-[11px] text-muted-foreground font-mono">
              app.gweiops.com/dashboard
            </div>
          </div>
          <div className="bg-background p-4">
            <div className="grid grid-cols-4 gap-px bg-border rounded-lg overflow-hidden">
              <div className="col-span-2 bg-card p-4">
                <div className="text-[9px] uppercase tracking-wider text-muted-foreground mb-2">整体态势</div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
                  系统正常运行 · 连续 14 天无故障
                </div>
              </div>
              <div className="bg-card p-4">
                <div className="text-[9px] uppercase tracking-wider text-muted-foreground mb-2">待审</div>
                <div className="text-xl font-bold text-yellow-500">3</div>
              </div>
              <div className="bg-card p-4">
                <div className="text-[9px] uppercase tracking-wider text-muted-foreground mb-2">昨夜修复</div>
                <div className="text-xl font-bold text-green-500">7</div>
              </div>
              <div className="col-span-3 bg-card p-4">
                <div className="text-[9px] uppercase tracking-wider text-muted-foreground mb-2">待审案件</div>
                <div className="text-[11px] text-muted-foreground space-y-1">
                  <div className="py-1 border-b border-border">#42 内存泄漏 — <span className="text-green-500">3 方案就绪</span></div>
                  <div className="py-1 border-b border-border">CVE-2026-1234 — <span className="text-green-500">应急补丁完成</span></div>
                  <div className="py-1">#89 文档缺失 — <span className="text-green-500">1 方案就绪</span></div>
                </div>
              </div>
              <div className="bg-card p-4">
                <div className="text-[9px] uppercase tracking-wider text-muted-foreground mb-2">MTTR</div>
                <div className="text-xl font-bold">8.2<span className="text-xs text-muted-foreground">min</span></div>
              </div>
              <div className="col-span-4 bg-card p-4">
                <div className="text-[9px] uppercase tracking-wider text-muted-foreground mb-2">昨夜回顾</div>
                <div className="text-[11px] text-muted-foreground flex gap-6">
                  <span>03:17 内存泄漏 → ✅</span>
                  <span>04:30 CVE 补丁 → ✅</span>
                  <span>05:12 流量扩容 → ✅</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Logos */}
      <section className="flex items-center justify-center gap-8 py-12 opacity-30">
        {logos.map((logo) => (
          <span key={logo} className="text-sm font-bold tracking-wider uppercase">{logo}</span>
        ))}
      </section>

      {/* Footer */}
      <footer className="text-center py-8 text-xs text-muted-foreground border-t border-border">
        GweiOps — 摆渡未济，恒守既济。
      </footer>
    </div>
  )
}
