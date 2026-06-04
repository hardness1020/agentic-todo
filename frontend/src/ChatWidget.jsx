// Floating, collapsible assistant. Collapsed = a FAB; expanded = a docked panel
// with the transcript, visible tool-call activity, suggestions, thinking dots,
// and a pill composer. Purely presentational — the Dashboard owns chat state.
import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'

const TOOL_ICON = {
  create_todo: 'plus',
  complete_todo: 'check',
  delete_todo: 'trash',
  update_todo: 'pencil',
  schedule_cron: 'calendar-clock',
  cancel_cron: 'x',
  remember: 'bookmark',
  recall: 'brain',
  list_todos: 'list',
  get_todo_stats: 'bar-chart',
  notify_user: 'bell',
}

const PENDING_TEXT = {
  create_todo: 'Creating todo…',
  complete_todo: 'Completing…',
  delete_todo: 'Deleting…',
  update_todo: 'Updating…',
  schedule_cron: 'Scheduling reminder…',
  cancel_cron: 'Cancelling…',
  remember: 'Saving to memory…',
  recall: 'Recalling…',
  list_todos: 'Reading list…',
  get_todo_stats: 'Checking stats…',
  notify_user: 'Notifying…',
}

const SUGGESTIONS = [
  'Add buy milk, then mark my oldest done',
  'Remind me to stretch every hour',
  'Remember I prefer short titles',
  "What's on my list today?",
]

function ActivityRow({ step }) {
  const pending = step.status === 'pending'
  return (
    <div className={'act' + (pending ? ' pending' : '')}>
      <span className="ai">
        {pending ? (
          <span className="spin" />
        ) : (
          <Icon name={TOOL_ICON[step.tool] || 'circle'} size={14} />
        )}
      </span>
      <span className="atx">
        {pending ? PENDING_TEXT[step.tool] || 'Working…' : step.label || step.tool}
        <span className="tool">{step.tool}</span>
      </span>
      {!pending && (
        <span className="chk">
          <Icon name="check" size={16} stroke={2.5} />
        </span>
      )}
    </div>
  )
}

function Message({ m }) {
  if (m.role === 'user') {
    return (
      <div className="msg user">
        <div className="bub">{m.text}</div>
      </div>
    )
  }
  const hasSteps = m.steps && m.steps.length > 0
  return (
    <div className="msg asst">
      <span className="av">
        <Icon name="sparkles" size={17} />
      </span>
      <div className="stack">
        {m.text && <div className={'bub' + (m.error ? ' err' : '')}>{m.text}</div>}
        {hasSteps && (
          <div className="acts">
            {m.steps.map((s, i) => (
              <ActivityRow step={s} key={i} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function ChatWidget({
  open,
  messages,
  thinking,
  unread,
  busy,
  fresh,
  onOpen,
  onClose,
  onSend,
  onReset,
}) {
  const [text, setText] = useState('')
  const [closing, setClosing] = useState(false)
  const scroll = useRef(null)

  useEffect(() => {
    if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight
  }, [messages, thinking, open])

  const send = (val) => {
    const v = (val ?? text).trim()
    if (!v || thinking) return
    onSend(v)
    setText('')
  }

  const handleClose = () => {
    setClosing(true)
    setTimeout(() => {
      setClosing(false)
      onClose()
    }, 160)
  }

  if (!open) {
    return (
      <button
        className={'fab' + (busy ? ' busy' : '')}
        onClick={onOpen}
        aria-label="Open assistant"
      >
        <span className="ring" />
        <Icon name="sparkles" size={26} />
        {unread > 0 && <span className="dot">{unread}</span>}
      </button>
    )
  }

  return (
    <div
      className={'chatw' + (closing ? ' closing' : '')}
      role="dialog"
      aria-label="ToDo assistant"
    >
      <div className="cw-h">
        <span className="av">
          <Icon name="sparkles" size={20} />
        </span>
        <div className="who">
          <div className="nm">ToDo assistant</div>
          <div className="st">Online</div>
        </div>
        <div className="cw-actions">
          <button
            className="min reset"
            onClick={() => onReset && onReset()}
            disabled={thinking || fresh}
            aria-label="Reset conversation"
            title="Reset conversation"
          >
            <Icon name="refresh-cw" size={17} />
          </button>
          <button
            className="min"
            onClick={handleClose}
            aria-label="Minimize"
            title="Conceal"
          >
            <Icon name="chevron-down" size={19} />
          </button>
        </div>
      </div>

      <div className="chat-scroll" ref={scroll}>
        {messages.map((m, i) => (
          <Message m={m} key={i} />
        ))}
        {thinking && (
          <div className="msg asst">
            <span className="av">
              <Icon name="sparkles" size={17} />
            </span>
            <div className="stack">
              <div className="bub">
                <div className="thinking">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {fresh && !thinking && (
        <div className="suggest">
          {SUGGESTIONS.map((s, i) => (
            <button className="chip" key={i} onClick={() => send(s)}>
              {s}
            </button>
          ))}
        </div>
      )}

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ask ToDo to add, schedule, or remember…"
        />
        <button
          className="send"
          type="submit"
          disabled={thinking || !text.trim()}
          aria-label="Send"
        >
          <Icon name="send" size={19} />
        </button>
      </form>
    </div>
  )
}
