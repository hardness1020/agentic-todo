// SidePanels.jsx — the two side cards surfaced from agent features:
//   • Reminders — scheduled cron jobs the agent created (schedule_cron).
//   • Memory    — durable per-user facts the agent remembered (remember).

function Reminders({ items, flashId, enteringId, onCancel }) {
  return (
    <div className="card">
      <div className="card-h">
        <span className="ch-ic" style={{ background: "var(--rausch-tint)", color: "var(--rausch)" }}>
          <Icon name="calendar-clock" size={17} />
        </span>
        <h2>Reminders</h2>
        <span className="muted">{items.length}</span>
      </div>
      <div className="mini">
        {items.length === 0 && (
          <div className="mini-empty">No reminders yet.<br />Try “remind me to stretch every hour.”</div>
        )}
        {items.map((r) => (
          <div
            key={r.id}
            className={"mini-row rem" + (r.id === flashId ? " flash" : "") + (r.id === enteringId ? " entering" : "")}
          >
            <span className="ic"><Icon name="clock" size={16} /></span>
            <div className="info">
              <div className="lab">{r.label}</div>
              <div className="sub">{r.schedule} · {r.next}</div>
            </div>
            <button className="x" onClick={() => onCancel(r.id)} aria-label="Cancel reminder">
              <Icon name="x" size={15} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
window.Reminders = Reminders;

function Memory({ items, flashId, enteringId, onForget }) {
  return (
    <div className="card">
      <div className="card-h">
        <span className="ch-ic" style={{ background: "var(--rausch-tint)", color: "var(--luxe)" }}>
          <Icon name="brain" size={17} />
        </span>
        <h2>Memory</h2>
        <span className="muted">{items.length}</span>
      </div>
      <div className="mini">
        {items.length === 0 && (
          <div className="mini-empty">Nothing remembered yet.<br />Try “remember I prefer short titles.”</div>
        )}
        {items.map((m) => (
          <div
            key={m.id}
            className={"mini-row mem" + (m.id === flashId ? " flash" : "") + (m.id === enteringId ? " entering" : "")}
          >
            <span className="ic"><Icon name="bookmark" size={16} /></span>
            <div className="info">
              <div className="lab">{m.value}</div>
            </div>
            <button className="x" onClick={() => onForget(m.id)} aria-label="Forget">
              <Icon name="x" size={15} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
window.Memory = Memory;
