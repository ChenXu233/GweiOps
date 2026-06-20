import { cn } from '@/lib/utils'

interface MetricCardProps {
  label: string
  value: string | number
  suffix?: string
  sub?: string
  variant?: 'default' | 'green' | 'yellow' | 'red'
  className?: string
}

const variantColors = {
  default: 'text-foreground',
  green: 'text-green-500',
  yellow: 'text-yellow-500',
  red: 'text-red-500',
}

export function MetricCard({ label, value, suffix, sub, variant = 'default', className }: MetricCardProps) {
  return (
    <div className={cn('space-y-1', className)}>
      {label && <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</div>}
      <div className={cn('text-3xl font-bold tracking-tight', variantColors[variant])}>
        {value}
        {suffix && <span className="text-base text-muted-foreground ml-0.5">{suffix}</span>}
      </div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
    </div>
  )
}
