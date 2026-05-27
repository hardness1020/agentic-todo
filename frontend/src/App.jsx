import { useState } from 'react'
import { getToken, setToken } from './api.js'
import AuthView from './AuthView.jsx'
import TodoList from './TodoList.jsx'

export default function App() {
  const [authed, setAuthed] = useState(!!getToken())

  function handleLogin(token) {
    setToken(token)
    setAuthed(true)
  }

  function handleLogout() {
    setToken(null)
    setAuthed(false)
  }

  return (
    <div className="container">
      <header>
        <h1>TODO</h1>
        {authed && (
          <button onClick={handleLogout} className="link">
            Log out
          </button>
        )}
      </header>
      {authed ? (
        <TodoList onUnauthorized={handleLogout} />
      ) : (
        <AuthView onLogin={handleLogin} />
      )}
    </div>
  )
}
