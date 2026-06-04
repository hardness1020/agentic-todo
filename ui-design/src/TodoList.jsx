// TodoList.jsx — todo card: add bar + rows with reactive highlight,
// complete, delete, entering animation, and a small due/meta affordance.
function TodoList({ todos, flashId, removingId, enteringId, onAdd, onToggle, onDelete }) {
  const [text, setText] = React.useState("");
  const submit = (e) => {
    e.preventDefault();
    const v = text.trim();
    if (!v) return;
    onAdd(v);
    setText("");
  };
  const open = todos.filter((t) => !t.done).length;
  return (
    <div className="card">
      <div className="card-h">
        <span className="ch-ic" style={{ background: "var(--rausch-tint)", color: "var(--rausch)" }}>
          <Icon name="list" size={17} />
        </span>
        <h2>Your todos</h2>
        <span className="muted">{open} open</span>
      </div>
      <form className="addbar" onSubmit={submit}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Add a todo…" />
        <button className="btn-primary" type="submit"><Icon name="plus" size={18} /> Add</button>
      </form>
      <div className="todos">
        {todos.length === 0 && (
          <div className="empty">Nothing here yet — ask ToDo to add something.</div>
        )}
        {todos.map((t) => (
          <div
            key={t.id}
            className={
              "todo" +
              (t.done ? " done" : "") +
              (t.id === flashId ? " flash" : "") +
              (t.id === enteringId ? " entering" : "") +
              (t.id === removingId ? " removing" : "")
            }
          >
            <button
              className={"ck" + (t.done ? " done" : "")}
              onClick={() => onToggle(t.id)}
              aria-label={t.done ? "Mark not done" : "Mark done"}
            >
              {t.done && <Icon name="check" size={15} stroke={3} />}
            </button>
            <span className="title">{t.title}</span>
            <button className="del" onClick={() => onDelete(t.id)} aria-label="Delete">
              <Icon name="trash" size={16} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
window.TodoList = TodoList;
