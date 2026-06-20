import { cn } from '@/lib/utils'

interface BentoGridProps {
  children: React.ReactNode
  className?: string
}

export function BentoGrid({ children, className }: BentoGridProps) {
  return (
    <div className={cn('grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-px bg-border rounded-xl overflow-hidden', className)}>
      {children}
    </div>
  )
}

interface BentoCellProps {
  children: React.ReactNode
  span?: 1 | 2 | 3 | 4
  rowSpan?: 1 | 2
  className?: string
}

export function BentoCell({ children, span = 1, rowSpan = 1, className }: BentoCellProps) {
  return (
    <div className={cn(
      'bg-card p-5 flex flex-col',
      span === 2 && 'md:col-span-2',
      span === 3 && 'md:col-span-2 xl:col-span-3',
      span === 4 && 'md:col-span-2 xl:col-span-4',
      rowSpan === 2 && 'row-span-2',
      className
    )}>
      {children}
    </div>
  )
}
