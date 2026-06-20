interface Session {
  id: string
  issue_id: string
  status: string
  started_at: string
}

const statusIcons: Record<string, string> = {
  INIT: '⏳',
  ANALYZING: '🔍',
  REPRODUCING: '🔄',
  GENERATING: '🛠️',
  WAITING: '⏸️',
  CREATING_PR: '📝',
  DONE: '✅',
  FAILED: '❌',
}

export default function SessionStatus({ session }: { session: Session }) {
  return (
    <div className="border rounded-lg p-4">
      <div className="flex items-center gap-2">
        <span className="text-2xl">{statusIcons[session.status] || '❓'}</span>
        <div>
          <p className="font-medium">{session.status}</p>
          <p className="text-sm text-gray-500">
            Issue #{session.issue_id.slice(0, 8)}
          </p>
        </div>
      </div>
      <p className="text-xs text-gray-400 mt-2">
        开始于 {new Date(session.started_at).toLocaleString('zh-CN')}
      </p>
    </div>
  )
}
