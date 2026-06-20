import { cn } from '@/lib/utils'

type Status = 'healthy' | 'warning' | 'critical'

interface StatusDotProps {
  status: Status
  size?: 'sm' | 'md'
  className?: string
}

const statusColors = {
  healthy: 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]',
  warning: 'bg-yellow-500',
  critical: 'bg-red-500',
}

export function StatusDot({ status, size = 'sm', className }: StatusDotProps) {
  return (
    <span className={cn('inline-block rounded-full', size === 'sm' ? 'h-1.5 w-1.5' : 'h-2 w-2', statusColors[status], className)} />
  )
}
