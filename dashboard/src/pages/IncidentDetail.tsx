/**
 * Incident detail page.
 *
 * Opens an SSE connection on mount to receive live agent progress events.
 * Shows:
 *   - Pipeline progress tracker
 *   - Crash report details
 *   - QA result (test case) when available
 *   - PR result when available
 *   - Live agent activity stream
 */

import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  IncidentDetail as IncidentDetailType,
  UIProgressEvent,
  subscribeToIncident,
} from '../api'
import { StatusBadge } from '../components/StatusBadge'
import { SeverityBadge } from '../components/SeverityBadge'
import { PipelineProgress } from '../components/PipelineProgress'
import { StreamPanel } from '../components/StreamPanel'
import { ToolTimeline } from '../components/ToolTimeline'

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString([], {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return iso
  }
}

interface SectionProps {
  title: string
  children: React.ReactNode
}

function Section({ title, children }: SectionProps) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-100 bg-gray-50">
        <h3 className="text-sm font-semibold text-gray-700">{title}</h3>
      </div>
      <div className="px-5 py-4">{children}</div>
    </div>
  )
}

interface FieldProps {
  label: string
  value: React.ReactNode
  mono?: boolean
}

function Field({ label, value, mono }: FieldProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs font-medium text-gray-400 uppercase tracking-wide">{label}</dt>
      <dd className={`text-sm text-gray-800 ${mono ? 'font-mono' : ''}`}>{value ?? '—'}</dd>
    </div>
  )
}

export function IncidentDetail() {
  const { incidentId } = useParams<{ incidentId: string }>()
  const [detail, setDetail] = useState<IncidentDetailType | null>(null)
  const [events, setEvents] = useState<UIProgressEvent[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!incidentId) return

    setError(null)
    setIsConnected(false)

    let cleanupFn: (() => void) | null = null

    subscribeToIncident(
      incidentId,
      (snapshot) => {
        if (!snapshot.status) {
          setError(`Incident '${incidentId}' not found`)
          return
        }
        setDetail(snapshot)
        setIsConnected(true)
      },
      (event) => {
        setEvents((prev) => [...prev, event])
        // When a status_changed event arrives, refresh the snapshot fields.
        if (event.type === 'status_changed') {
          setDetail((prev) => prev ? { ...prev, status: event.message } : prev)
        }
      },
    ).then((cleanup) => {
      cleanupFn = cleanup
    })

    return () => {
      cleanupFn?.()
    }
  }, [incidentId])

  if (error) {
    return (
      <div className="text-center py-16">
        <p className="text-red-500 text-sm">{error}</p>
        <Link to="/" className="mt-4 inline-block text-sm text-blue-600 hover:underline">
          ← Back to incidents
        </Link>
      </div>
    )
  }

  if (!detail) {
    return <div className="text-center py-16 text-gray-400 text-sm">Connecting…</div>
  }

  const { crash_report: report, qa_result, pr_result } = detail

  return (
    <div className="space-y-6">
      {/* Back link + header */}
      <div>
        <Link to="/" className="text-sm text-gray-400 hover:text-gray-600 flex items-center gap-1 mb-4">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18" />
          </svg>
          All incidents
        </Link>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-gray-900 font-mono break-all">
              {incidentId}
            </h1>
            {report && (
              <p className="mt-1 text-sm text-gray-600">
                {report.error_type}: {report.error_message}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {report && <SeverityBadge severity={report.severity} />}
            <StatusBadge status={detail.status} />
          </div>
        </div>
      </div>

      {/* Pipeline progress */}
      <Section title="Pipeline">
        <PipelineProgress status={detail.status} />
      </Section>

      {/* Tool call timeline */}
      <ToolTimeline events={events} />

      {/* Live stream */}
      <StreamPanel events={events} isConnected={isConnected} />

      {/* Crash report */}
      {report && (
        <Section title="Crash Report">
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <Field label="Error type" value={report.error_type} mono />
            <Field label="Component" value={report.affected_component} />
            <Field label="Endpoint" value={report.affected_endpoint} />
            <Field label="Language" value={report.language} />
            <Field label="Source" value={report.source} />
            <Field label="Detected" value={formatTimestamp(report.timestamp)} />
          </dl>
          <div className="mt-4">
            <dt className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">Summary</dt>
            <p className="text-sm text-gray-700 leading-relaxed">{report.summary}</p>
          </div>
          {report.stack_trace && (
            <details className="mt-4">
              <summary className="text-xs font-medium text-gray-400 uppercase tracking-wide cursor-pointer hover:text-gray-600">
                Stack trace
              </summary>
              <pre className="mt-2 text-xs text-gray-600 bg-gray-50 rounded-lg p-3 overflow-x-auto leading-relaxed font-mono whitespace-pre-wrap">
                {report.stack_trace}
              </pre>
            </details>
          )}
        </Section>
      )}

      {/* QA result */}
      {qa_result && qa_result.test_case.content && (
        <Section title="QA — Test Case">
          <dl className="grid grid-cols-2 gap-4 mb-4">
            <Field
              label="Issue"
              value={
                <a
                  href={qa_result.ticket_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline"
                >
                  #{qa_result.ticket_id}
                </a>
              }
            />
            <Field label="Test file" value={qa_result.test_case.file_path} mono />
            <Field label="Test name" value={qa_result.test_case.test_name} mono />
            <Field label="Format" value={qa_result.test_case.format} />
          </dl>
          <details open>
            <summary className="text-xs font-medium text-gray-400 uppercase tracking-wide cursor-pointer hover:text-gray-600">
              Test content
            </summary>
            <pre className="mt-2 text-xs text-gray-700 bg-gray-50 rounded-lg p-3 overflow-x-auto leading-relaxed font-mono whitespace-pre-wrap">
              {qa_result.test_case.content}
            </pre>
          </details>
        </Section>
      )}

      {/* PR result */}
      {pr_result && (
        <Section title="Dev Agent — Pull Request">
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <Field
              label="Pull request"
              value={
                <a
                  href={pr_result.pr_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline"
                >
                  #{pr_result.pr_number}
                </a>
              }
            />
            <Field label="Branch" value={pr_result.branch_name} mono />
            <Field label="Iterations" value={String(pr_result.iterations_taken)} />
          </dl>
          {pr_result.fix_summary && (
            <div className="mt-4">
              <dt className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">Fix summary</dt>
              <p className="text-sm text-gray-700 leading-relaxed">{pr_result.fix_summary}</p>
            </div>
          )}
          {pr_result.files_changed.length > 0 && (
            <div className="mt-4">
              <dt className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">Files changed</dt>
              <ul className="space-y-0.5">
                {pr_result.files_changed.map((f) => (
                  <li key={f} className="text-xs font-mono text-gray-600">
                    {f}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Section>
      )}
    </div>
  )
}
