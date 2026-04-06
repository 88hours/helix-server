/**
 * Pill badge for crash severity.
 */

const SEVERITY_STYLES: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  high: 'bg-orange-100 text-orange-700',
  medium: 'bg-yellow-100 text-yellow-700',
}

interface SeverityBadgeProps {
  severity: string | null
}

export function SeverityBadge({ severity }: SeverityBadgeProps) {
  if (!severity) return null
  const style = SEVERITY_STYLES[severity] ?? 'bg-gray-100 text-gray-600'
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${style}`}>
      {severity}
    </span>
  )
}
