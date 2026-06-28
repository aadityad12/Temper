import { useEffect, useReducer, useCallback } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { fetchRoomState } from '../api'
import { useSSE } from '../hooks/useSSE'
import QuestionTable from './QuestionTable'
import BaselinePanel from './BaselinePanel'
import FinalReport from './FinalReport'

const s = {
  page: {
    minHeight: '100vh',
    display: 'grid',
    gridTemplateColumns: '1fr 280px',
    gridTemplateRows: 'auto 1fr',
    gap: '0',
  },
  header: {
    gridColumn: '1 / -1',
    display: 'flex',
    alignItems: 'center',
    gap: '1rem',
    padding: '1rem 1.5rem',
    borderBottom: '1px solid var(--border)',
    background: 'var(--surface)',
  },
  wordmark: {
    fontSize: '1.1rem',
    fontWeight: 700,
    letterSpacing: '0.12em',
    color: 'var(--accent)',
  },
  roomId: {
    fontFamily: 'var(--mono)',
    fontSize: '0.75rem',
    color: 'var(--muted)',
  },
  statusDot: (connected) => ({
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: connected ? 'var(--green)' : 'var(--muted)',
    marginLeft: 'auto',
    flexShrink: 0,
  }),
  statusLabel: {
    fontSize: '0.8rem',
    color: 'var(--muted)',
  },
  main: {
    padding: '1.5rem',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '1.5rem',
  },
  sidebar: {
    borderLeft: '1px solid var(--border)',
    padding: '1.5rem',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '1.5rem',
  },
}

function reducer(state, action) {
  switch (action.type) {
    case 'INIT':
      return { ...state, ...action.payload, loaded: true }

    case 'pi_connected':
      return { ...state, pi_connected: true }

    case 'questions_ready': {
      const rows = action.questions.map(q => ({ ...q, status: 'pending' }))
      return { ...state, questions: rows, questionCount: rows.length }
    }

    case 'pi_submitted': {
      const questions = state.questions.map(q =>
        q.question_id === action.question_id
          ? { ...q, pi_latency_ms: action.latency_ms, pi_input_tokens: action.input_tokens, pi_output_tokens: action.output_tokens, status: 'submitted' }
          : q
      )
      // Add placeholder if question not yet in list
      const exists = questions.some(q => q.question_id === action.question_id)
      if (!exists) {
        questions.push({
          question_id: action.question_id,
          dimension: action.dimension,
          pi_latency_ms: action.latency_ms,
          pi_input_tokens: action.input_tokens,
          pi_output_tokens: action.output_tokens,
          status: 'submitted',
        })
      }
      const piTokens = {
        input: (state.piTokens.input || 0) + (action.input_tokens || 0),
        output: (state.piTokens.output || 0) + (action.output_tokens || 0),
      }
      return { ...state, questions, piTokens }
    }

    case 'question_judged': {
      const questions = state.questions.map(q =>
        q.question_id === action.question_id
          ? {
              ...q,
              baseline_score: action.baseline_score,
              harness_score: action.harness_score,
              delta: action.delta,
              verdict: action.verdict,
              baseline_latency_ms: action.baseline_latency_ms,
              status: 'judged',
            }
          : q
      )
      const baselineTokens = {
        input: (state.baselineTokens.input || 0) + 500,  // estimated
        output: (state.baselineTokens.output || 0) + 120,
      }
      return { ...state, questions, baselineTokens }
    }

    case 'session_complete':
      return { ...state, report: action.report, patches: action.patches, complete: true }

    default:
      return state
  }
}

const initialState = {
  loaded: false,
  pi_connected: false,
  questionCount: null,
  questions: [],
  piTokens: { input: 0, output: 0 },
  baselineTokens: { input: 0, output: 0 },
  report: null,
  patches: [],
  complete: false,
  baseline_model: 'DeepSeek V3 Flash',
  judge_model: 'Gemini 2.5 Flash',
}

export default function Dashboard() {
  const { roomId } = useParams()
  const [searchParams] = useSearchParams()
  const key = searchParams.get('key') || ''
  const [state, dispatch] = useReducer(reducer, initialState)

  useEffect(() => {
    fetchRoomState(roomId, key)
      .then(data => {
        const questions = (data.questions || []).map(q => ({
          ...q,
          status: q.judge_result ? 'judged' : q.pi_latency_ms ? 'submitted' : 'pending',
          baseline_score: q.judge_result?.baseline_score,
          harness_score: q.judge_result?.harness_score,
          delta: q.judge_result ? q.judge_result.harness_score - q.judge_result.baseline_score : undefined,
          verdict: q.judge_result?.verdict,
        }))
        const piTokens = questions.reduce(
          (acc, q) => ({ input: acc.input + (q.pi_input_tokens || 0), output: acc.output + (q.pi_output_tokens || 0) }),
          { input: 0, output: 0 }
        )
        const judgedCount = questions.filter(q => q.status === 'judged').length
        const baselineTokens = { input: judgedCount * 500, output: judgedCount * 120 }
        dispatch({
          type: 'INIT',
          payload: {
            pi_connected: data.pi_connected,
            questions,
            piTokens,
            baselineTokens,
            report: data.report,
            patches: data.patches || [],
            complete: data.status === 'ready',
            baseline_model: data.baseline_model || 'DeepSeek V3 Flash',
            judge_model: data.judge_model || 'Gemini 2.5 Flash',
          },
        })
      })
      .catch(console.error)
  }, [roomId, key])

  const handleSSE = useCallback((event) => {
    dispatch({ ...event, type: event.type })
  }, [])

  useSSE(roomId, key, handleSSE)

  const piLatencies = state.questions.filter(q => q.pi_latency_ms).map(q => q.pi_latency_ms)
  const baselineLatencies = state.questions.filter(q => q.baseline_latency_ms).map(q => q.baseline_latency_ms)
  const avgPiLatency = piLatencies.length ? Math.round(piLatencies.reduce((a, b) => a + b, 0) / piLatencies.length) : null
  const avgBaselineLatency = baselineLatencies.length ? Math.round(baselineLatencies.reduce((a, b) => a + b, 0) / baselineLatencies.length) : null

  const statusLabel = !state.loaded ? 'Loading…'
    : state.complete ? 'Complete'
    : !state.pi_connected ? 'Waiting for Pi…'
    : `${state.questions.filter(q => q.status === 'judged').length} / ${state.questions.length || '?'} judged`

  return (
    <div style={s.page}>
      <header style={s.header}>
        <span style={s.wordmark}>TEMPER</span>
        <span style={s.roomId}>room/{roomId}</span>
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={s.statusLabel}>{statusLabel}</span>
          <span style={s.statusDot(state.pi_connected)} />
        </span>
      </header>

      <main style={s.main}>
        <QuestionTable questions={state.questions} />
        {state.complete && (
          <FinalReport report={state.report} patches={state.patches} />
        )}
      </main>

      <aside style={s.sidebar}>
        <BaselinePanel
          baselineModel={state.baseline_model}
          judgeModel={state.judge_model}
          piTokens={state.piTokens}
          baselineTokens={state.baselineTokens}
          avgPiLatency={avgPiLatency}
          avgBaselineLatency={avgBaselineLatency}
        />
      </aside>
    </div>
  )
}
