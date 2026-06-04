import { useState } from 'react'
import { getToken, setToken } from './api.js'
import AuthView from './AuthView.jsx'
import Dashboard from './Dashboard.jsx'

export default function App() {
  const [authed, setAuthed] = useState(!!getToken())

  function handleLogin(token) {
    setToken(token)
    setAuthed(true)
  }

  function handleLogout() {
    setToken(null)
    localStorage.removeItem('username')
    setAuthed(false)
  }

  return authed ? (
    <Dashboard onUnauthorized={handleLogout} />
  ) : (
    <AuthView onLogin={handleLogin} />
  )
}
