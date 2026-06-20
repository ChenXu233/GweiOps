import { NextResponse } from 'next/server'

// 简化版：使用内存存储
// 生产环境会使用数据库
let config = {
  mode: 'saas',
  ai_provider: 'openai',
  ai_model: 'gpt-4o',
  min_approvals: 2,
  owner_can_override: true,
}

export async function GET() {
  return NextResponse.json(config)
}

export async function PUT(request: Request) {
  const newConfig = await request.json()
  config = { ...config, ...newConfig }
  return NextResponse.json(config)
}
