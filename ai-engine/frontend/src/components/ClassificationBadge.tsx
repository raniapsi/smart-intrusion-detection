import type { Classification } from '../api/types'
import { classificationColors } from '../lib/format'

type Props = {
  classification: Classification
  score?: number
  size?: 'sm' | 'md'
}

export function ClassificationBadge({ classification, score, size = 'md' }: Props) {
  const { bg, text, border } = classificationColors(classification)
  const sizeClasses =
    size === 'sm' ? 'text-[10px] px-1.5 py-0.5' : 'text-xs px-2 py-0.5'
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-mono font-medium uppercase tracking-wide ${bg} ${text} ${border} ${sizeClasses}`}
    >
      {classification}
      {score !== undefined && (
        <span className="text-gray-300/80">{score.toFixed(2)}</span>
      )}
    </span>
  )
}