import { useState } from 'react'
import { api } from './api.js'

export default function AuthView({ onLogin }) {
  const [mode, setMode] = useState('login') // 'login' | 'register'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  function formatError(data) {
    if (!data) return 'Something went wrong.'
    if (typeof data === 'string') return data
    if (data.detail) return data.detail
    // DRF serializer errors: { field: [messages] }
    return Object.entries(data)
      .map(([field, msgs]) => `${field}: ${[].concat(msgs).join(' ')}`)
      .join(' ')
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    try {
      if (mode === 'register') {
        await api.register(username, password)
      }
      const { access } = await api.login(username, password)
      onLogin(access)
    } catch (err) {
      setError(formatError(err.data) || 'Invalid credentials.')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="auth">
      <h2>{mode === 'login' ? 'Log in' : 'Register'}</h2>
      {error && <p className="error">{error}</p>}
      <input
        placeholder="Username"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        required
      />
      <input
        type="password"
        placeholder="Password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />
      <button type="submit">{mode === 'login' ? 'Log in' : 'Create account'}</button>
      <button
        type="button"
        className="link"
        onClick={() => {
          setMode(mode === 'login' ? 'register' : 'login')
          setError('')
        }}
      >
        {mode === 'login' ? 'Need an account? Register' : 'Have an account? Log in'}
      </button>
    </form>
  )
}
