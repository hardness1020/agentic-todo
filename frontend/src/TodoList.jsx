// Todo card: add bar + rows with reactive highlight (flash / enter / remove),
// complete toggle, hover-reveal edit + delete. The flash/enter/removing ids are
// owned by the Dashboard so agent-driven and manual changes animate identically.
import { useState } from 'react'
import Icon from './Icon.jsx'

export default function TodoList({
  todos,
  flashId,
  enteringId,
  removingId,
  onAdd,
  onToggle,
  onDelete,
  onEdit,
}) {
  const [text, setText] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editText, setEditText] = useState('')

  const submit = (e) => {
    e.preventDefault()
    const v = text.trim()
    if (!v) return
    onAdd(v)
    setText('')
  }

  const startEdit = (todo) => {
    setEditingId(todo.id)
    setEditText(todo.title)
  }
  const commitEdit = (id) => {
    const v = editText.trim()
    setEditingId(null)
    if (v && v !== todos.find((t) => t.id === id)?.title) onEdit(id, v)
  }

  const open = todos.filter((t) => !t.completed).length

  return (
    <div className="card">
      <div className="card-h">
        <span
          className="ch-ic"
          style={{ background: 'var(--rausch-tint)', color: 'var(--rausch)' }}
        >
          <Icon name="list" size={17} />
        </span>
        <h2>Your todos</h2>
        <span className="muted">{open} open</span>
      </div>
      <form className="addbar" onSubmit={submit}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Add a todo…"
        />
        <button className="btn-primary" type="submit">
          <Icon name="plus" size={18} /> Add
        </button>
      </form>
      <div className="todos">
        {todos.length === 0 && (
          <div className="empty">Nothing here yet — ask ToDo to add something.</div>
        )}
        {todos.map((t) => (
          <div
            key={t.id}
            className={
              'todo' +
              (t.completed ? ' done' : '') +
              (t.id === flashId ? ' flash' : '') +
              (t.id === enteringId ? ' entering' : '') +
              (t.id === removingId ? ' removing' : '')
            }
          >
            <button
              className={'ck' + (t.completed ? ' done' : '')}
              onClick={() => onToggle(t)}
              aria-label={t.completed ? 'Mark not done' : 'Mark done'}
            >
              {t.completed && <Icon name="check" size={15} stroke={3} />}
            </button>
            {editingId === t.id ? (
              <input
                className="title-edit"
                autoFocus
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                onBlur={() => commitEdit(t.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitEdit(t.id)
                  if (e.key === 'Escape') setEditingId(null)
                }}
              />
            ) : (
              <span className="title">{t.title}</span>
            )}
            <button className="edit" onClick={() => startEdit(t)} aria-label="Edit">
              <Icon name="pencil" size={16} />
            </button>
            <button className="del" onClick={() => onDelete(t)} aria-label="Delete">
              <Icon name="trash" size={16} />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
