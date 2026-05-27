import { useEffect, useState } from 'react'
import { api, UnauthorizedError } from './api.js'

export default function TodoList({ onUnauthorized }) {
  const [todos, setTodos] = useState([])
  const [title, setTitle] = useState('')
  const [error, setError] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editTitle, setEditTitle] = useState('')

  // Centralized error handling: 401 logs the user out.
  function handleError(err) {
    if (err instanceof UnauthorizedError) onUnauthorized()
    else setError('Could not reach the server. Try again.')
  }

  async function load() {
    try {
      const data = await api.listTodos()
      setTodos(data.results)
      setError('')
    } catch (err) {
      handleError(err)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function addTodo(e) {
    e.preventDefault()
    if (!title.trim()) return
    try {
      await api.createTodo(title.trim())
      setTitle('')
      load()
    } catch (err) {
      handleError(err)
    }
  }

  async function toggle(todo) {
    try {
      await api.updateTodo(todo.id, { completed: !todo.completed })
      load()
    } catch (err) {
      handleError(err)
    }
  }

  async function saveEdit(id) {
    if (!editTitle.trim()) return
    try {
      await api.updateTodo(id, { title: editTitle.trim() })
      setEditingId(null)
      load()
    } catch (err) {
      handleError(err)
    }
  }

  async function remove(id) {
    if (!window.confirm('Delete this todo?')) return
    try {
      await api.deleteTodo(id)
      load()
    } catch (err) {
      handleError(err)
    }
  }

  return (
    <div>
      {error && <p className="error">{error}</p>}
      <form onSubmit={addTodo} className="add">
        <input
          placeholder="What needs doing?"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <button type="submit">Add</button>
      </form>
      <ul className="todos">
        {todos.map((todo) => (
          <li key={todo.id}>
            <input
              type="checkbox"
              checked={todo.completed}
              onChange={() => toggle(todo)}
            />
            {editingId === todo.id ? (
              <>
                <input
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                />
                <button onClick={() => saveEdit(todo.id)}>Save</button>
                <button className="link" onClick={() => setEditingId(null)}>
                  Cancel
                </button>
              </>
            ) : (
              <>
                <span className={todo.completed ? 'done' : ''}>{todo.title}</span>
                <button
                  className="link"
                  onClick={() => {
                    setEditingId(todo.id)
                    setEditTitle(todo.title)
                  }}
                >
                  Edit
                </button>
                <button className="link" onClick={() => remove(todo.id)}>
                  Delete
                </button>
              </>
            )}
          </li>
        ))}
        {todos.length === 0 && <li className="empty">No todos yet.</li>}
      </ul>
    </div>
  )
}
