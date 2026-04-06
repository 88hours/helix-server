/**
 * Horizontal pipeline step tracker.
 *
 * Shows the 4 pipeline stages and highlights which has been reached based
 * on the current incident status string.
 */

const STAGES = [
  { key: 'crash_analysed', label: 'Crash Analysed', agent: 'Crash Handler' },
  { key: 'test_case_generated', label: 'Test Generated', agent: 'QA Agent' },
  { key: 'pr_created', label: 'PR Created', agent: 'Dev Agent' },
  { key: 'pr_merged', label: 'Merged', agent: 'Human Approval' },
]

// Ordered list of statuses — a higher index means further along the pipeline.
const STATUS_ORDER = [
  'crash_analysed',
  'test_case_generated',
  'fix_suggested',
  'pr_created',
  'quality_approved',
  'pr_merged',
]

function stageReached(stageKey: string, currentStatus: string): boolean {
  const stageIndex = STATUS_ORDER.indexOf(stageKey)
  const currentIndex = STATUS_ORDER.indexOf(currentStatus)
  if (stageIndex === -1 || currentIndex === -1) return false
  return currentIndex >= stageIndex
}

interface PipelineProgressProps {
  status: string
}

export function PipelineProgress({ status }: PipelineProgressProps) {
  const failed = status === 'fix_failed' || status === 'approval_rejected'

  return (
    <div className="flex items-start gap-0">
      {STAGES.map((stage, i) => {
        const reached = stageReached(stage.key, status)
        const isLast = i === STAGES.length - 1

        return (
          <div key={stage.key} className="flex items-center flex-1 min-w-0">
            <div className="flex flex-col items-center flex-1 min-w-0">
              {/* Circle */}
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold flex-shrink-0 ${
                  reached && !failed
                    ? 'bg-green-500 text-white'
                    : reached && failed
                    ? 'bg-red-400 text-white'
                    : 'bg-gray-200 text-gray-400'
                }`}
              >
                {reached && !failed ? (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  <span>{i + 1}</span>
                )}
              </div>
              {/* Label */}
              <p className="mt-1.5 text-xs font-medium text-center text-gray-600 leading-tight">{stage.label}</p>
              <p className="text-xs text-center text-gray-400 leading-tight">{stage.agent}</p>
            </div>
            {/* Connector line */}
            {!isLast && (
              <div
                className={`h-0.5 flex-1 mx-1 mt-0 mb-8 ${
                  stageReached(STAGES[i + 1].key, status) && !failed ? 'bg-green-500' : 'bg-gray-200'
                }`}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}
