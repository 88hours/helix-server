/**
 * Live agent activity stream panel.
 *
 * Renders an auto-scrolling log of UI progress events received via SSE.
 * Each event shows a timestamp, agent name, and message.
 */

import { useEffect, useRef } from 'react'
import { UIProgressEvent } from '../api'

const AGENT_COLOURS: Record<string, string> = {
  crash_handler: 'text-blue-600',
  qa: 'text-purple-600',
  dev: 'text-green-600',
  notifier: 'text-orange-600',
}

const EVENT_ICONS: Record<string, string> = {
  agent_start: '▶',
  agent_step: '·',
  agent_done: '✓',
  status_changed: '◆',
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

interface StreamPanelProps {
  events: UIProgressEvent[]
  isConnected: boolean
}

export function StreamPanel({ events, isConnected }: StreamPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom whenever new events arrive.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events.length])

  return (
    <div className="bg-gray-900 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <span className="text-sm font-medium text-gray-300 font-mono">Agent Activity</span>
        <span className="flex items-center gap-1.5 text-xs text-gray-500">
          <span
            className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-400 animate-pulse' : 'bg-gray-600'}`}
          />
          {isConnected ? 'Live' : 'Disconnected'}
        </span>
      </div>

      {/* Log */}
      <div className="px-4 py-3 h-72 overflow-y-auto space-y-1 font-mono text-sm">
        {events.length === 0 ? (
          <p className="text-gray-600 italic">Waiting for agent activity…</p>
        ) : (
          events.map((ev, i) => (
            <div key={i} className="flex items-start gap-3">
              <span className="text-gray-600 text-xs flex-shrink-0 mt-0.5 w-20 tabular-nums">
                {formatTime(ev.timestamp)}
              </span>
              <span
                className={`text-xs flex-shrink-0 mt-0.5 w-4 text-center ${AGENT_COLOURS[ev.agent] ?? 'text-gray-400'}`}
              >
                {EVENT_ICONS[ev.type] ?? '·'}
              </span>
              <span className={`text-xs font-semibold flex-shrink-0 w-16 ${AGENT_COLOURS[ev.agent] ?? 'text-gray-400'}`}>
                {ev.agent}
              </span>
              <span className="text-gray-300 text-xs leading-relaxed">{ev.message}</span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
