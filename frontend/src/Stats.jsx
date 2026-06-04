// Three stat cards (open / done / total) + a gradient momentum bar.
// Driven by the server-computed stats so it stays consistent with the agent's
// own get_todo_stats tool.
export default function Stats({ stats }) {
  const { open = 0, done = 0, total = 0 } = stats || {}
  const pct = total ? Math.round((done / total) * 100) : 0
  return (
    <>
      <div className="stats">
        <div className="stat accent">
          <div className="num">{open}</div>
          <div className="lab">open</div>
        </div>
        <div className="stat good">
          <div className="num">{done}</div>
          <div className="lab">done</div>
        </div>
        <div className="stat">
          <div className="num">{total}</div>
          <div className="lab">total</div>
        </div>
      </div>
      <div className="momentum">
        <div className="track">
          <div className="fill" style={{ width: pct + '%' }} />
        </div>
        <span className="pct">{pct}% done today</span>
      </div>
    </>
  )
}
