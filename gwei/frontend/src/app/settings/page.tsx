'use client'

import { useEffect, useState } from 'react'
import ConfigForm from '@/components/ConfigForm'

interface Config {
  mode: string
  ai_provider: string
  ai_model: string
  min_approvals: number
  owner_can_override: boolean
}

export default function Settings() {
  const [config, setConfig] = useState<Config | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => {
        setConfig(data)
        setLoading(false)
      })
  }, [])

  const handleSave = async (newConfig: Config) => {
    setSaving(true)
    await fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newConfig),
    })
    setConfig(newConfig)
    setSaving(false)
  }

  if (loading) {
    return <div className="p-8">加载中...</div>
  }

  return (
    <div className="p-8">
      <h1 className="text-3xl font-bold mb-8">项目配置</h1>
      <ConfigForm config={config!} onSave={handleSave} saving={saving} />
    </div>
  )
}
