interface Issue {
  id: string
  number: number
  title: string
  status: string
  created_at: string
}

const statusColors: Record<string, string> = {
  OPEN: 'bg-green-100 text-green-800',
  ANALYZING: 'bg-yellow-100 text-yellow-800',
  HAS_PATCH: 'bg-blue-100 text-blue-800',
  PR_CREATED: 'bg-purple-100 text-purple-800',
  FIXED: 'bg-gray-100 text-gray-800',
  CLOSED: 'bg-gray-100 text-gray-800',
}

export default function IssueCard({ issue }: { issue: Issue }) {
  return (
    <div className="border rounded-lg p-4 hover:shadow-md transition-shadow">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-gray-500">#{issue.number}</span>
        <span className={`px-2 py-1 rounded-full text-xs ${statusColors[issue.status] || 'bg-gray-100'}`}>
          {issue.status}
        </span>
      </div>
      <h3 className="font-medium">{issue.title}</h3>
      <p className="text-sm text-gray-500 mt-2">
        {new Date(issue.created_at).toLocaleDateString('zh-CN')}
      </p>
    </div>
  )
}
