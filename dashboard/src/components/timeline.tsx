import { cn } from '@/lib/utils'

interface TimelineStep {
  id: string
  label: string
  status: 'done' | 'active' | 'pending'
}

interface TimelineProps {
  steps: TimelineStep[]
  className?: string
}

export function Timeline({ steps, className }: TimelineProps) {
  return (
    <div className={cn('flex items-center gap-0 overflow-x-auto', className)}>
      {steps.map((step, i) => (
        <div key={step.id} className="flex items-center">
          <div className="flex items-center gap-2 whitespace-nowrap">
            <div className={cn(
              'h-2 w-2 rounded-full flex-shrink-0',
              step.status === 'done' && 'bg-green-500',
              step.status === 'active' && 'bg-yellow-500 animate-pulse',
              step.status === 'pending' && 'bg-border'
            )} />
            <span className={cn(
              'text-xs',
              step.status === 'done' && 'text-muted-foreground',
              step.status === 'active' && 'text-yellow-500 font-semibold',
              step.status === 'pending' && 'text-muted-foreground'
            )}>
              {step.label}
            </span>
          </div>
          {i < steps.length - 1 && <div className="w-6 h-px bg-border mx-1 flex-shrink-0" />}
        </div>
      ))}
    </div>
  )
}
