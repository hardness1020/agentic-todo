import { useState } from 'react'
import { api } from './api.js'
import { formatError } from './util.js'
import Icon from './Icon.jsx'

export default function AuthView({ onLogin }) {
  const [mode, setMode] = useState('login') // 'login' | 'register'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    try {
      if (mode === 'register') {
        await api.register(username, password)
      }
      const { access } = await api.login(username, password)
      localStorage.setItem('username', username)
      onLogin(access)
    } catch (err) {
      setError(formatError(err.data, 'Invalid credentials.'))
    }
  }

  return (
    <div className="auth">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="mark">
            <Icon name="check" size={25} stroke={3} />
          </span>
          <span className="wm">ToDo</span>
        </div>
        <h1>{mode === 'login' ? 'Welcome back' : 'Create your account'}</h1>
        <p className="sub">Your calm, AI-powered to-do list.</p>
        <form onSubmit={handleSubmit}>
          {error && <p className="error">{error}</p>}
          <div className="field">
            <label>Username</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </div>
          <div className="field">
            <label>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              required
            />
          </div>
          <button className="btn-primary" type="submit">
            {mode === 'login' ? 'Log in' : 'Sign up'}
          </button>
        </form>
        <div className="switch">
          {mode === 'login' ? 'New here? ' : 'Have an account? '}
          <a
            onClick={() => {
              setMode(mode === 'login' ? 'register' : 'login')
              setError('')
            }}
          >
            {mode === 'login' ? 'Create an account' : 'Log in'}
          </a>
        </div>
      </div>
    </div>
  )
}
