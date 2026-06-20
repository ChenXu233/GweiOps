import { NextResponse } from 'next/server'

export async function GET() {
  // 简化版：返回模拟数据
  const sessions = [
    {
      id: '1',
      issue_id: '1',
      status: 'WAITING',
      started_at: new Date().toISOString(),
    },
  ]

  return NextResponse.json(sessions)
}
