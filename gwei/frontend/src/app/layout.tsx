import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: '既未 · Gwei',
  description: 'AI 驱动的 GitHub Issue 修复平台',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh">
      <body>{children}</body>
    </html>
  )
}
