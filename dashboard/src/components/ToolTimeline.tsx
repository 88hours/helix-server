/**
 * Tool call timeline component.
 *
 * Extracts tool_call events from the UIProgressEvent stream and renders a
 * structured list showing which external tools each agent called, the action
 * taken, the result (success / failed), and any result detail.
 *
 * Displayed only when at least one tool_call event has been received.
 */

import { ToolCallEvent, UIProgressEvent } from '../api'

// ─── Labels ──────────────────────────────────────────────────────────────────

const TOOL_LABELS: Record<string, string> = {
  llm: 'LLM',
  github: 'GitHub',
  git: 'Git',
  claude_code: 'Claude Code',
}

const ACTION_LABELS: Record<string, string> = {
  complete: 'Generate',
  create_issue: 'Create issue',
  find_issue: 'Search issues',
  add_comment: 'Add comment',
  clone: 'Clone repo',
  fetch_files: 'Fetch files',
  tdd_iterate: 'TDD iterate',
  commit_push: 'Commit & push',
  create_pr: 'Create PR',
}

const AGENT_CHIP: Record<string, string> = {
  crash_handler: 'bg-blue-100 text-blue-700',
  qa: 'bg-purple-100 text-purple-700',
  dev: 'bg-green-100 text-green-700',
  notifier: 'bg-orange-100 text-orange-700',
}

// ─── Tool icon ────────────────────────────────────────────────────────────────

function ToolIcon({ tool }: { tool: string }) {
  const base = 'w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0'

  if (tool === 'llm') {
    return (
      <div className={`${base} bg-violet-100`}>
        <svg className="w-4 h-4 text-violet-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z" />
        </svg>
      </div>
    )
  }

  if (tool === 'github') {
    return (
      <div className={`${base} bg-gray-100`}>
        <svg className="w-4 h-4 text-gray-700" fill="currentColor" viewBox="0 0 24 24">
          <path d="M12 2C6.477 2 2 6.477 2 12c0 4.418 2.865 8.166 6.839 9.489.5.092.682-.217.682-.482 0-.237-.009-.868-.013-1.703-2.782.603-3.369-1.342-3.369-1.342-.454-1.154-1.11-1.461-1.11-1.461-.908-.62.069-.608.069-.608 1.003.07 1.531 1.03 1.531 1.03.892 1.529 2.341 1.087 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.11-4.555-4.943 0-1.091.39-1.984 1.029-2.683-.103-.253-.446-1.27.098-2.647 0 0 .84-.269 2.75 1.025A9.578 9.578 0 0 1 12 6.836a9.59 9.59 0 0 1 2.504.337c1.909-1.294 2.747-1.025 2.747-1.025.546 1.377.202 2.394.1 2.647.64.699 1.028 1.592 1.028 2.683 0 3.842-2.339 4.687-4.566 4.935.359.309.678.919.678 1.852 0 1.336-.012 2.415-.012 2.743 0 .267.18.578.688.48C19.138 20.163 22 16.418 22 12c0-5.523-4.477-10-10-10Z" />
        </svg>
      </div>
    )
  }

  if (tool === 'git') {
    return (
      <div className={`${base} bg-orange-100`}>
        <svg className="w-4 h-4 text-orange-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M14.25 9.75 16.5 12l-2.25 2.25m-4.5 0L7.5 12l2.25-2.25M6 20.25h12A2.25 2.25 0 0 0 20.25 18V6A2.25 2.25 0 0 0 18 3.75H6A2.25 2.25 0 0 0 3.75 6v12A2.25 2.25 0 0 0 6 20.25Z" />
        </svg>
      </div>
    )
  }

  // claude_code
  return (
    <div className={`${base} bg-emerald-100`}>
      <svg className="w-4 h-4 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="m3.75 13.5 10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75Z" />
      </svg>
    </div>
  )
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

// ─── Component ────────────────────────────────────────────────────────────────

interface ToolTimelineProps {
  events: UIProgressEvent[]
}

export function ToolTimeline({ events }: ToolTimelineProps) {
  const calls = events.filter((e): e is ToolCallEvent => e.type === 'tool_call')

  if (calls.length === 0) return null

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-100 bg-gray-50">
        <h3 className="text-sm font-semibold text-gray-700">Tool Calls</h3>
      </div>
      <div className="divide-y divide-gray-50">
        {calls.map((call, i) => {
          const chipClass = AGENT_CHIP[call.agent] ?? 'bg-gray-100 text-gray-700'
          const toolLabel = TOOL_LABELS[call.tool] ?? call.tool
          const actionLabel = ACTION_LABELS[call.action] ?? call.action

          return (
            <div key={i} className="flex items-center gap-3 px-5 py-3">
              <ToolIcon tool={call.tool} />

              <div className="flex-1 min-w-0 flex items-center gap-2 flex-wrap">
                <span className={`text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${chipClass}`}>
                  {call.agent}
                </span>
                <span className="text-sm text-gray-800">
                  {toolLabel} — {actionLabel}
                </span>
                {call.detail && (
                  <span className="text-xs text-gray-400 font-mono">{call.detail}</span>
                )}
              </div>

              <div className="flex items-center gap-2 flex-shrink-0">
                {call.status === 'success' ? (
                  <svg className="w-4 h-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                  </svg>
                )}
                <span className="text-xs text-gray-400 tabular-nums">{formatTime(call.timestamp)}</span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
