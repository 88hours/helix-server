/**
 * Pill badge for incident pipeline status.
 */

const STATUS_STYLES: Record<string, string> = {
  crash_analysed: 'bg-blue-100 text-blue-700',
  test_case_generated: 'bg-purple-100 text-purple-700',
  fix_suggested: 'bg-yellow-100 text-yellow-700',
  pr_created: 'bg-orange-100 text-orange-700',
  quality_approved: 'bg-teal-100 text-teal-700',
  pr_merged: 'bg-green-100 text-green-700',
  approval_rejected: 'bg-red-100 text-red-700',
  fix_failed: 'bg-red-100 text-red-700',
  duplicate_detected: 'bg-gray-100 text-gray-600',
  unknown: 'bg-gray-100 text-gray-500',
}

const STATUS_LABELS: Record<string, string> = {
  crash_analysed: 'Crash Analysed',
  test_case_generated: 'Test Generated',
  fix_suggested: 'Fix Suggested',
  pr_created: 'PR Created',
  quality_approved: 'Quality Approved',
  pr_merged: 'Merged',
  approval_rejected: 'Rejected',
  fix_failed: 'Fix Failed',
  duplicate_detected: 'Duplicate',
  unknown: 'Unknown',
}

interface StatusBadgeProps {
  status: string
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.unknown
  const label = STATUS_LABELS[status] ?? status
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${style}`}>
      {label}
    </span>
  )
}
