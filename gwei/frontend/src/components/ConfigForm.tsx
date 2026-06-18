'use client'

import { useState } from 'react'

interface Config {
  mode: string
  ai_provider: string
  ai_model: string
  min_approvals: number
  owner_can_override: boolean
}

interface ConfigFormProps {
  config: Config
  onSave: (config: Config) => void
  saving: boolean
}

export default function ConfigForm({ config, onSave, saving }: ConfigFormProps) {
  const [formData, setFormData] = useState(config)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSave(formData)
  }

  return (
    <form onSubmit={handleSubmit} className="max-w-2xl space-y-6">
      <div>
        <label className="block text-sm font-medium mb-2">托管模式</label>
        <select
          value={formData.mode}
          onChange={e => setFormData({ ...formData, mode: e.target.value })}
          className="w-full border rounded-lg p-2"
        >
          <option value="saas">SaaS 模式</option>
          <option value="self-hosted">自托管模式</option>
        </select>
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">AI 提供商</label>
        <select
          value={formData.ai_provider}
          onChange={e => setFormData({ ...formData, ai_provider: e.target.value })}
          className="w-full border rounded-lg p-2"
        >
          <option value="openai">OpenAI</option>
          <option value="anthropic">Anthropic</option>
          <option value="local">本地模型</option>
        </select>
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">AI 模型</label>
        <input
          type="text"
          value={formData.ai_model}
          onChange={e => setFormData({ ...formData, ai_model: e.target.value })}
          className="w-full border rounded-lg p-2"
          placeholder="gpt-4o"
        />
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">最少审批人数</label>
        <input
          type="number"
          value={formData.min_approvals}
          onChange={e => setFormData({ ...formData, min_approvals: parseInt(e.target.value) })}
          className="w-full border rounded-lg p-2"
          min="1"
          max="5"
        />
      </div>

      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={formData.owner_can_override}
          onChange={e => setFormData({ ...formData, owner_can_override: e.target.checked })}
          className="rounded"
        />
        <label className="text-sm font-medium">Owner 可单人决定</label>
      </div>

      <button
        type="submit"
        disabled={saving}
        className="bg-blue-500 text-white px-4 py-2 rounded-lg hover:bg-blue-600 disabled:opacity-50"
      >
        {saving ? '保存中...' : '保存配置'}
      </button>
    </form>
  )
}
