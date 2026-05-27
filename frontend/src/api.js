const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000/api'
const TOKEN_KEY = 'access_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

// Raised when the API returns 401 so callers can redirect to login.
export class UnauthorizedError extends Error {}

async function request(path, { method = 'GET', body, auth = true } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (auth) {
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }
  const resp = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (resp.status === 401) {
    setToken(null)
    throw new UnauthorizedError('Session expired')
  }
  const data = resp.status === 204 ? null : await resp.json()
  if (!resp.ok) {
    const err = new Error('Request failed')
    err.data = data
    throw err
  }
  return data
}

export const api = {
  register: (username, password) =>
    request('/auth/register', { method: 'POST', body: { username, password }, auth: false }),
  login: (username, password) =>
    request('/auth/token', { method: 'POST', body: { username, password }, auth: false }),
  listTodos: () => request('/todos/'),
  createTodo: (title, description = '') =>
    request('/todos/', { method: 'POST', body: { title, description } }),
  updateTodo: (id, patch) =>
    request(`/todos/${id}/`, { method: 'PATCH', body: patch }),
  deleteTodo: (id) => request(`/todos/${id}/`, { method: 'DELETE' }),
}
