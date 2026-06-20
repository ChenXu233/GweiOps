import { NextResponse } from 'next/server'

export async function GET() {
  // 简化版：返回模拟数据
  // 生产环境会调用后端 API
  const issues = [
    {
      id: '1',
      number: 1,
      title: 'Parser crash on null input',
      status: 'HAS_PATCH',
      created_at: new Date().toISOString(),
    },
    {
      id: '2',
      number: 2,
      title: 'Add JSON output support',
      status: 'ANALYZING',
      created_at: new Date().toISOString(),
    },
  ]

  return NextResponse.json(issues)
}
