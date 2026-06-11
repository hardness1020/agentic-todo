// The dashboard orchestrator. Owns every piece of live state (todos, stats,
// reminders, memory, notifications, chat) and the reactive-highlight system:
// agent-driven AND manual changes are applied by diffing freshly-fetched data
// against the current data, then animating each affected row "flash first, then
// apply" (creates enter + flash, updates flash then change, deletes fade out).
// Notifications are polled every ~10s and surfaced as toasts + the header bell.
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, UnauthorizedError } from './api.js'
import { sleep } from './util.js'
import Header from './Header.jsx'
import Stats from './Stats.jsx'
import TodoList from './TodoList.jsx'
import { Reminders, Memory } from './SidePanels.jsx'
import ChatWidget from './ChatWidget.jsx'
import Toasts from './Toasts.jsx'

const POLL_MS = 10000

const GREETING = {
  role: 'assistant',
  text:
    "Hi — I'm ToDo. Ask me to add, complete, schedule, or remember things and " +
    'watch your dashboard update in real time.',
  steps: [],
}

// Insert an item at the position it occupies in `fresh`, so a new row animates
// into its correct slot before the final reconcile.
function insertInFreshOrder(list, item, fresh) {
  if (list.some((x) => x.id === item.id)) return list
  const order = fresh.map((x) => x.id)
  return [...list, item].sort(
    (a, b) => order.indexOf(a.id) - order.indexOf(b.id)
  )
}

// Diff `prev` vs `fresh` and animate the differences via the supplied setters.
async function reconcileList(prev, fresh, { setList, setFlash, setEnter, setRemoving, changed }) {
  const prevById = new Map(prev.map((x) => [x.id, x]))
  const freshById = new Map(fresh.map((x) => [x.id, x]))
  const added = fresh.filter((x) => !prevById.has(x.id))
  const removed = prev.filter((x) => !freshById.has(x.id))
  const modified = fresh.filter(
    (x) => prevById.has(x.id) && changed(prevById.get(x.id), x)
  )

  // Additions: insert in place, then enter + flash.
  for (const a of added) {
    setList((list) => insertInFreshOrder(list, a, fresh))
    setEnter(a.id)
    setFlash(a.id)
    await sleep(900)
    setEnter(null)
    setFlash(null)
  }
  // Modifications: flash the old row, then apply the change.
  for (const m of modified) {
    setFlash(m.id)
    await sleep(700)
    setList((list) => list.map((x) => (x.id === m.id ? { ...x, ...m } : x)))
    setFlash(null)
  }
  // Removals: flash, fade out, then drop.
  for (const r of removed) {
    setFlash(r.id)
    await sleep(520)
    setRemoving(r.id)
    await sleep(280)
    setList((list) => list.filter((x) => x.id !== r.id))
    setRemoving(null)
    setFlash(null)
  }
  // Final reconcile: exact match to fresh (ordering + silent field updates
  // such as a reminder's next-fire label).
  setList(() => fresh)
}

const todoChanged = (a, b) => a.title !== b.title || a.completed !== b.completed
// Deliberately ignores schedule_human / next_fire so the relative-time label
// refreshing each poll doesn't trigger a spurious flash.
const reminderChanged = (a, b) =>
  a.label !== b.label || a.cron !== b.cron || a.recurring !== b.recurring
const memoryChanged = (a, b) => a.key !== b.key || a.value !== b.value

export default function Dashboard({ onUnauthorized }) {
  const [todos, setTodos] = useState([])
  const [stats, setStats] = useState({ open: 0, done: 0, total: 0 })
  const [reminders, setReminders] = useState([])
  const [memories, setMemories] = useState([])
  const [notifications, setNotifications] = useState([])
  const [toasts, setToasts] = useState([])
  const [banner, setBanner] = useState(null) // {text, error}

  const [messages, setMessages] = useState([GREETING])
  const [thinking, setThinking] = useState(false)
  const [busy, setBusy] = useState(false)

  const [chatOpen, setChatOpen] = useState(false)
  const [chatUnread, setChatUnread] = useState(0)
  const [popOpen, setPopOpen] = useState(false)
  const [badgePulse, setBadgePulse] = useState(false)

  // Reactive-highlight ids (one active per list at a time reads as "watch it act").
  const [todoFlash, setTodoFlash] = useState(null)
  const [todoEnter, setTodoEnter] = useState(null)
  const [todoRemoving, setTodoRemoving] = useState(null)
  const [remFlash, setRemFlash] = useState(null)
  const [remEnter, setRemEnter] = useState(null)
  const [remRemoving, setRemRemoving] = useState(null)
  const [memFlash, setMemFlash] = useState(null)
  const [memEnter, setMemEnter] = useState(null)
  const [memRemoving, setMemRemoving] = useState(null)

  // Refs for the reconcile/poll loops (avoid stale closures).
  const todosRef = useRef(todos)
  const remindersRef = useRef(reminders)
  const memoriesRef = useRef(memories)
  const seenNotifIds = useRef(new Set())
  const reconcilingRef = useRef(false)
  const chatActiveRef = useRef(false)
  const chatOpenRef = useRef(chatOpen)
  todosRef.current = todos
  remindersRef.current = reminders
  memoriesRef.current = memories
  chatOpenRef.current = chatOpen

  const handleError = useCallback(
    (err) => {
      if (err instanceof UnauthorizedError) onUnauthorized()
      else setBanner({ text: 'Could not reach the server. Retrying…', error: true })
    },
    [onUnauthorized]
  )

  // ── toasts ──
  const pushToast = useCallback((n) => {
    const toast = { id: n.id, title: n.title, body: n.body }
    setToasts((x) => [...x, toast])
    setTimeout(() => setToasts((x) => x.filter((t) => t.id !== n.id)), 6000)
  }, [])

  const reconcileNotifications = useCallback(
    (fresh) => {
      const seen = seenNotifIds.current
      const fresh_new = fresh.filter((n) => !seen.has(n.id))
      if (fresh_new.length) {
        fresh_new.forEach((n) => seen.add(n.id))
        // Toast oldest-first so they stack in natural order.
        ;[...fresh_new].reverse().forEach(pushToast)
        setBadgePulse(true)
        setTimeout(() => setBadgePulse(false), 400)
      }
      setNotifications(fresh)
    },
    [pushToast]
  )

  // ── unified reconcile: fetch fresh state and animate every difference ──
  const reconcile = useCallback(async () => {
    if (reconcilingRef.current) return
    reconcilingRef.current = true
    try {
      const [todosR, statsR, jobsR, memsR, notisR] = await Promise.all([
        api.listTodos(),
        api.todoStats(),
        api.listScheduledJobs(),
        api.listMemories(),
        api.listNotifications(),
      ])
      setBanner(null)
      await Promise.all([
        reconcileList(todosRef.current, todosR.results, {
          setList: setTodos,
          setFlash: setTodoFlash,
          setEnter: setTodoEnter,
          setRemoving: setTodoRemoving,
          changed: todoChanged,
        }),
        reconcileList(remindersRef.current, jobsR.results, {
          setList: setReminders,
          setFlash: setRemFlash,
          setEnter: setRemEnter,
          setRemoving: setRemRemoving,
          changed: reminderChanged,
        }),
        reconcileList(memoriesRef.current, memsR.results, {
          setList: setMemories,
          setFlash: setMemFlash,
          setEnter: setMemEnter,
          setRemoving: setMemRemoving,
          changed: memoryChanged,
        }),
      ])
      setStats(statsR)
      reconcileNotifications(notisR.results)
    } catch (err) {
      handleError(err)
    } finally {
      reconcilingRef.current = false
    }
  }, [handleError, reconcileNotifications])

  // ── initial load ──
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [chat, todosR, statsR, jobsR, memsR, notisR] = await Promise.all([
          api.listChat(),
          api.listTodos(),
          api.todoStats(),
          api.listScheduledJobs(),
          api.listMemories(),
          api.listNotifications(),
        ])
        if (cancelled) return
        setMessages([GREETING, ...chat.messages])
        setTodos(todosR.results)
        setStats(statsR)
        setReminders(jobsR.results)
        setMemories(memsR.results)
        setNotifications(notisR.results)
        seenNotifIds.current = new Set(notisR.results.map((n) => n.id))
      } catch (err) {
        if (!cancelled) handleError(err)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [handleError])

  // ── polling: cron-driven changes + new notifications ──
  useEffect(() => {
    const tick = () => {
      if (chatActiveRef.current || reconcilingRef.current) return
      reconcile()
    }
    const id = setInterval(tick, POLL_MS)
    return () => clearInterval(id)
  }, [reconcile])

  // ── close popover on outside click ──
  useEffect(() => {
    if (!popOpen) return
    const onDoc = (e) => {
      if (!e.target.closest('.nav-wrap')) setPopOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [popOpen])

  // ── chat transcript mutators (drive the live assistant shell) ──
  const appendMessage = (m) => setMessages((c) => [...c, m])
  const mutateLast = (fn) =>
    setMessages((c) => {
      const next = [...c]
      next[next.length - 1] = fn(next[next.length - 1])
      return next
    })

  const revealAssistant = async (msg) => {
    appendMessage({ role: 'assistant', text: '', steps: [] })
    await sleep(120)
    for (const step of msg.steps || []) {
      mutateLast((last) => ({
        ...last,
        steps: [...last.steps, { tool: step.tool, status: 'pending' }],
      }))
      await sleep(420)
      mutateLast((last) => {
        const steps = [...last.steps]
        steps[steps.length - 1] = { tool: step.tool, label: step.label, status: 'done' }
        return { ...last, steps }
      })
      await sleep(140)
    }
    mutateLast((last) => ({ ...last, text: msg.text }))
    await sleep(120)
  }

  // ── the chat turn ──
  const sendChat = useCallback(
    async (text) => {
      chatActiveRef.current = true
      appendMessage({ role: 'user', text })
      setThinking(true)
      setBusy(true)
      try {
        let result
        try {
          result = await api.sendChat(text)
        } catch (err) {
          setThinking(false)
          if (err instanceof UnauthorizedError) {
            onUnauthorized()
            return
          }
          const text503 =
            err.status === 503
              ? "The assistant is unavailable — no API key is configured. Your message was saved, and the rest of the app still works."
              : 'Sorry — I ran into a problem with that. Please try again.'
          appendMessage({ role: 'assistant', text: text503, steps: [], error: true })
          if (!chatOpenRef.current) setChatUnread((u) => u + 1)
          return
        }
        setThinking(false)
        const assistantMsgs = (result.messages || []).filter((m) => m.role === 'assistant')
        // Reveal the tool activity while the affected rows flash-and-update.
        await Promise.all([
          (async () => {
            for (const m of assistantMsgs) await revealAssistant(m)
          })(),
          reconcile(),
        ])
        if (!chatOpenRef.current) setChatUnread((u) => u + assistantMsgs.length)
      } finally {
        setBusy(false)
        chatActiveRef.current = false
      }
    },
    [onUnauthorized, reconcile]
  )

  const resetChat = useCallback(async () => {
    try {
      await api.resetChat()
      setMessages([GREETING])
    } catch (err) {
      handleError(err)
    }
  }, [handleError])

  // ── manual actions (reuse the same reactive reconcile) ──
  const manual = useCallback(
    async (fn) => {
      try {
        await fn()
        await reconcile()
      } catch (err) {
        handleError(err)
      }
    },
    [handleError, reconcile]
  )

  const addTodo = (title) => manual(() => api.createTodo(title))
  const toggleTodo = (todo) => manual(() => api.updateTodo(todo.id, { completed: !todo.completed }))
  const editTodo = (id, title) => manual(() => api.updateTodo(id, { title }))
  const deleteTodo = (todo) => {
    if (!window.confirm('Delete this todo?')) return
    manual(() => api.deleteTodo(todo.id))
  }
  const cancelReminder = (r) => manual(() => api.cancelScheduledJob(r.id))
  const forgetMemory = (m) => manual(() => api.forgetMemory(m.id))

  // ── notifications header actions ──
  const markAllRead = async () => {
    try {
      await api.markAllNotificationsRead()
      setNotifications((n) => n.map((x) => ({ ...x, read: true })))
    } catch (err) {
      handleError(err)
    }
  }
  const clearNotifications = async () => {
    try {
      await api.clearNotifications()
      setNotifications([])
    } catch (err) {
      handleError(err)
    }
  }

  const openChat = () => {
    setChatOpen(true)
    setChatUnread(0)
  }

  const username = localStorage.getItem('username') || ''
  const initial = (username[0] || 'Y').toUpperCase()
  const unread = notifications.filter((n) => !n.read).length
  const fresh = messages.filter((m) => m.role === 'user').length === 0

  return (
    <div className="app">
      <Header
        unread={unread}
        notifications={notifications}
        popOpen={popOpen}
        onTogglePop={() => setPopOpen((p) => !p)}
        onMarkAllRead={markAllRead}
        onClear={clearNotifications}
        initial={initial}
        badgePulse={badgePulse}
        onLogout={onUnauthorized}
      />
      <div className="main">
        <h1 className="greeting">Today's focus</h1>
        <p className="subtle">
          Here's where things stand. Ask the assistant to make changes — watch them land.
        </p>
        {banner && (
          <div className={'banner' + (banner.error ? ' error' : '')}>{banner.text}</div>
        )}
        <Stats stats={stats} />
        <div className="cols">
          <TodoList
            todos={todos}
            flashId={todoFlash}
            enteringId={todoEnter}
            removingId={todoRemoving}
            onAdd={addTodo}
            onToggle={toggleTodo}
            onEdit={editTodo}
            onDelete={deleteTodo}
          />
          <div className="side">
            <Reminders
              items={reminders}
              flashId={remFlash}
              enteringId={remEnter}
              removingId={remRemoving}
              onCancel={cancelReminder}
            />
            <Memory
              items={memories}
              flashId={memFlash}
              enteringId={memEnter}
              removingId={memRemoving}
              onForget={forgetMemory}
            />
          </div>
        </div>
      </div>

      <ChatWidget
        open={chatOpen}
        messages={messages}
        thinking={thinking}
        unread={chatUnread}
        busy={busy}
        fresh={fresh}
        onOpen={openChat}
        onClose={() => setChatOpen(false)}
        onSend={sendChat}
        onReset={resetChat}
      />
      <Toasts items={toasts} onDismiss={(id) => setToasts((x) => x.filter((t) => t.id !== id))} />
    </div>
  )
}
