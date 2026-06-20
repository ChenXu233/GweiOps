import { cn } from '@/lib/utils'

interface CanaryProgressProps {
  steps: string[]
  completedSteps: string[]
  currentStep: string
  metrics: {
    passRate: number
    errorRate: number
    p99Latency: string
    memoryPeak: string
  }
  className?: string
}

export function CanaryProgress({ steps, completedSteps, currentStep, metrics, className }: CanaryProgressProps) {
  return (
    <div className={cn('space-y-3', className)}>
      <div className="flex gap-1">
        {steps.map((step) => (
          <div key={step} className={cn(
            'h-1.5 flex-1 rounded-full',
            completedSteps.includes(step) && 'bg-green-500',
            step === currentStep && 'bg-yellow-500 animate-pulse',
            !completedSteps.includes(step) && step !== currentStep && 'bg-border'
          )} />
        ))}
      </div>
      <div className="flex justify-between text-[10px] text-muted-foreground">
        {steps.map((step) => (
          <span key={step} className={cn(step === currentStep && 'text-yellow-500 font-semibold')}>
            {step}{completedSteps.includes(step) ? ' ✅' : ''}
          </span>
        ))}
      </div>
      <div className="grid grid-cols-4 gap-3 text-center">
        <div>
          <div className="text-lg font-bold text-green-500">{metrics.passRate}%</div>
          <div className="text-[10px] text-muted-foreground">通过率</div>
        </div>
        <div>
          <div className="text-lg font-bold text-green-500">{metrics.errorRate}%</div>
          <div className="text-[10px] text-muted-foreground">错误率</div>
        </div>
        <div>
          <div className="text-lg font-bold">{metrics.p99Latency}</div>
          <div className="text-[10px] text-muted-foreground">P99 延迟</div>
        </div>
        <div>
          <div className="text-lg font-bold text-yellow-500">{metrics.memoryPeak}</div>
          <div className="text-[10px] text-muted-foreground">内存峰值</div>
        </div>
      </div>
    </div>
  )
}
