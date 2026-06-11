// The two right-sidebar cards surfaced from agent features:
//   • Reminders — scheduled cron jobs (schedule_cron / cancel_cron).
//   • Memory    — durable per-user facts (remember / forget).
// Both share the flash + slide-in + fade-out reactive animations.
import Icon from './Icon.jsx'

export function Reminders({ items, flashId, enteringId, removingId, onCancel }) {
  return (
    <div className="card">
      <div className="card-h">
        <span
          className="ch-ic"
          style={{ background: 'var(--rausch-tint)', color: 'var(--rausch)' }}
        >
          <Icon name="calendar-clock" size={17} />
        </span>
        <h2>Reminders</h2>
        <span className="muted">{items.length}</span>
      </div>
      <div className="mini">
        {items.length === 0 && (
          <div className="mini-empty">
            No reminders yet.
            <br />
            Try “remind me to stretch every hour.”
          </div>
        )}
        {items.map((r) => (
          <div
            key={r.id}
            className={
              'mini-row rem' +
              (r.id === flashId ? ' flash' : '') +
              (r.id === enteringId ? ' entering' : '') +
              (r.id === removingId ? ' removing' : '')
            }
          >
            <span className="ic">
              <Icon name="clock" size={16} />
            </span>
            <div className="info">
              <div className="lab">{r.label}</div>
              <div className="sub">
                {r.schedule_human} · {r.next_fire}
              </div>
            </div>
            <button
              className="x"
              onClick={() => onCancel(r)}
              aria-label="Cancel reminder"
            >
              <Icon name="x" size={15} />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

export function Memory({ items, flashId, enteringId, removingId, onForget }) {
  return (
    <div className="card">
      <div className="card-h">
        <span
          className="ch-ic"
          style={{ background: 'var(--rausch-tint)', color: 'var(--luxe)' }}
        >
          <Icon name="brain" size={17} />
        </span>
        <h2>Memory</h2>
        <span className="muted">{items.length}</span>
      </div>
      <div className="mini">
        {items.length === 0 && (
          <div className="mini-empty">
            Nothing remembered yet.
            <br />
            Try “remember I prefer short titles.”
          </div>
        )}
        {items.map((m) => (
          <div
            key={m.id}
            className={
              'mini-row mem' +
              (m.id === flashId ? ' flash' : '') +
              (m.id === enteringId ? ' entering' : '') +
              (m.id === removingId ? ' removing' : '')
            }
          >
            <span className="ic">
              <Icon name="bookmark" size={16} />
            </span>
            <div className="info">
              <div className="lab">{m.value}</div>
            </div>
            <button className="x" onClick={() => onForget(m)} aria-label="Forget">
              <Icon name="x" size={15} />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
