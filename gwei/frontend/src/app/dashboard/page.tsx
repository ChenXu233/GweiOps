'use client'

import { useEffect, useState } from 'react'
import IssueCard from '@/components/IssueCard'
import SessionStatus from '@/components/SessionStatus'

interface Issue {
  id: string
  number: number
  title: string
  status: string
  created_at: string
}

interface Session {
  id: string
  issue_id: string
  status: string
  started_at: string
}

export default function Dashboard() {
  const [issues, setIssues] = useState<Issue[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      fetch('/api/issues').then(r => r.json()),
      fetch('/api/sessions').then(r => r.json()),
    ]).then(([issuesData, sessionsData]) => {
      setIssues(issuesData)
      setSessions(sessionsData)
      setLoading(false)
    })
  }, [])

  if (loading) {
    return <div className="p-8">加载中...</div>
  }

  return (
    <div className="p-8">
      <h1 className="text-3xl font-bold mb-8">监控面板</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <div>
          <h2 className="text-2xl font-semibold mb-4">Issues</h2>
          <div className="space-y-4">
            {issues.map(issue => (
              <IssueCard key={issue.id} issue={issue} />
            ))}
            {issues.length === 0 && (
              <p className="text-gray-500">暂无 Issue</p>
            )}
          </div>
        </div>

        <div>
          <h2 className="text-2xl font-semibold mb-4">Agent 会话</h2>
          <div className="space-y-4">
            {sessions.map(session => (
              <SessionStatus key={session.id} session={session} />
            ))}
            {sessions.length === 0 && (
              <p className="text-gray-500">暂无活跃会话</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
