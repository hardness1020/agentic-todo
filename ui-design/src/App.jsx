// App.jsx — orchestrates the Tally dashboard, the floating assistant, and a
// richer cosmetic "agent": multi-step tool sequences with narrated, visible
// tool-call activity and reactive highlights across todos, reminders & memory.
const { useState, useRef, useCallback, useEffect } = React;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let _id = 1000;
const nextId = () => ++_id;

const SEED_TODOS = [
  { id: 1, title: "Buy groceries for the week", done: false },
  { id: 2, title: "Email Sam the quarterly report", done: false },
  { id: 3, title: "Book dentist appointment", done: true },
  { id: 4, title: "Water the plants", done: false },
  { id: 5, title: "Draft Q3 planning doc", done: false },
];
const SEED_REMINDERS = [
  { id: 11, label: "Stand up & stretch", schedule: "every hour", next: "next in ~1h" },
  { id: 12, label: "Review tomorrow's calendar", schedule: "every weekday at 5pm", next: "next at 5pm" },
];
const SEED_MEMORY = [
  { id: 21, value: "You prefer short, lowercase todo titles" },
  { id: 22, value: "Your standup is at 9:30am" },
];
const SEED_NOTIS = [
  { id: 31, title: "Reminder", body: "Stand up & stretch", time: "2 min ago", read: false },
  { id: 32, title: "Reminder", body: "Review tomorrow's calendar", time: "1 hr ago", read: true },
];
const SEED_MSGS = [
  { role: "assistant", text: "Hi — I'm ToDo. Ask me to add, complete, schedule, or remember things and watch your dashboard update in real time.", steps: [] },
];

const PENDING_TEXT = {
  create_todo: "Creating todo…", complete_todo: "Completing…", delete_todo: "Deleting…",
  update_todo: "Updating…", schedule_cron: "Scheduling reminder…", cancel_cron: "Cancelling…",
  remember: "Saving to memory…", recall: "Recalling…", list_todos: "Reading list…",
  get_todo_stats: "Checking stats…",
};

function App() {
  const [screen, setScreen] = useState("auth");
  const [email, setEmail] = useState("");

  const [todos, setTodos] = useState(SEED_TODOS);
  const [reminders, setReminders] = useState(SEED_REMINDERS);
  const [memory, setMemory] = useState(SEED_MEMORY);
  const [notifications, setNotifications] = useState(SEED_NOTIS);

  const [messages, setMessages] = useState(SEED_MSGS);
  const [thinking, setThinking] = useState(false);
  const [busy, setBusy] = useState(false);

  const [chatOpen, setChatOpen] = useState(false);
  const [chatUnread, setChatUnread] = useState(0);
  const [popOpen, setPopOpen] = useState(false);
  const [badgePulse, setBadgePulse] = useState(false);

  // reactive-highlight ids, per list
  const [todoFlash, setTodoFlash] = useState(null);
  const [todoEnter, setTodoEnter] = useState(null);
  const [removingId, setRemovingId] = useState(null);
  const [remFlash, setRemFlash] = useState(null);
  const [remEnter, setRemEnter] = useState(null);
  const [memFlash, setMemFlash] = useState(null);
  const [memEnter, setMemEnter] = useState(null);

  const [toasts, setToasts] = useState([]);

  const todosRef = useRef(todos); todosRef.current = todos;

  // ---------- flash helpers ----------
  const flashTodo = useCallback(async (id, hold = 900) => { setTodoFlash(id); await sleep(hold); setTodoFlash(null); }, []);
  const enterTodo = useCallback((id) => { setTodoEnter(id); setTimeout(() => setTodoEnter(null), 260); }, []);

  // ---------- notifications ----------
  const fireNotification = useCallback((title, body) => {
    const id = nextId();
    setToasts((x) => [...x, { id, title, body }]);
    setNotifications((n) => [{ id: nextId(), title, body, time: "just now", read: false }, ...n]);
    setBadgePulse(true); setTimeout(() => setBadgePulse(false), 400);
    setBusy(true); setTimeout(() => setBusy(false), 1500);
    setTimeout(() => setToasts((x) => x.filter((t) => t.id !== id)), 6000);
  }, []);

  // ---------- direct UI actions ----------
  const addTodo = useCallback(async (title) => {
    const id = nextId();
    setTodos((x) => [...x, { id, title, done: false }]);
    enterTodo(id); flashTodo(id);
    return { id, title };
  }, [enterTodo, flashTodo]);

  const toggleTodo = useCallback(async (id, highlight = false) => {
    if (highlight) await flashTodo(id, 700);
    setTodos((x) => x.map((t) => (t.id === id ? { ...t, done: !t.done } : t)));
  }, [flashTodo]);

  const removeTodo = useCallback(async (id, highlight = false) => {
    if (highlight) await flashTodo(id, 520);
    setRemovingId(id); await sleep(260);
    setTodos((x) => x.filter((t) => t.id !== id));
    setRemovingId(null);
  }, [flashTodo]);

  // ---------- message-stream helpers (mutate the live assistant shell) ----------
  const pushPending = (tool) => setMessages((m) => {
    const c = [...m]; const last = { ...c[c.length - 1] };
    last.steps = [...last.steps, { status: "pending", tool, pending: PENDING_TEXT[tool] || "Working…" }];
    c[c.length - 1] = last; return c;
  });
  const resolvePending = (tool, label) => setMessages((m) => {
    const c = [...m]; const last = { ...c[c.length - 1] };
    const steps = [...last.steps]; steps[steps.length - 1] = { status: "done", tool, label };
    last.steps = steps; c[c.length - 1] = last; return c;
  });
  const setLastText = (text) => setMessages((m) => {
    const c = [...m]; c[c.length - 1] = { ...c[c.length - 1], text }; return c;
  });

  // ---------- execute a single op (returns conversational line) ----------
  const execute = async (op) => {
    const all = todosRef.current;
    const open = all.filter((t) => !t.done);

    if (op.type === "create_todo") {
      await addTodo(op.title);
      resolvePending("create_todo", `Created “${op.title}”`);
      return `Added “${op.title}.”`;
    }
    if (op.type === "complete_todo") {
      const target = pickTarget(open, all, op.text);
      if (target && !target.done) {
        await toggleTodo(target.id, true);
        resolvePending("complete_todo", `Marked “${target.title}” done`);
        return `Marked “${target.title}” done.`;
      }
      resolvePending("complete_todo", "Nothing open to complete");
      return "There's nothing open to complete right now.";
    }
    if (op.type === "delete_todo") {
      const target = pickTarget(open, all, op.text);
      if (target) {
        await removeTodo(target.id, true);
        resolvePending("delete_todo", `Deleted “${target.title}”`);
        return `Deleted “${target.title}.”`;
      }
      resolvePending("delete_todo", "Nothing to delete");
      return "I couldn't find that one to delete.";
    }
    if (op.type === "update_todo") {
      const m = op.text.match(/to\s+(.+)$/);
      const newTitle = capitalize((m && m[1] ? m[1] : "").trim());
      const target = pickTarget(open, all, op.text);
      if (target && newTitle) {
        await flashTodo(target.id, 700);
        setTodos((x) => x.map((t) => (t.id === target.id ? { ...t, title: newTitle } : t)));
        resolvePending("update_todo", `Renamed to “${newTitle}”`);
        return `Renamed it to “${newTitle}.”`;
      }
      resolvePending("update_todo", "Couldn't update");
      return "I couldn't tell which todo to rename.";
    }
    if (op.type === "schedule_cron") {
      const id = nextId();
      const schedule = humanCron(op.text);
      const label = capitalize(reminderBody(op.text));
      const rem = { id, label, schedule, next: nextFireLabel(op.text) };
      setReminders((r) => [rem, ...r]);
      setRemEnter(id); setTimeout(() => setRemEnter(null), 260);
      setRemFlash(id); setTimeout(() => setRemFlash(null), 900);
      // a fired reminder lands as a notification a few seconds later
      setTimeout(() => fireNotification("Reminder", label), 4200 + Math.random() * 2500);
      resolvePending("schedule_cron", `Scheduled — ${schedule}`);
      return `I'll remind you to ${label.toLowerCase()} — ${schedule}.`;
    }
    if (op.type === "cancel_cron") {
      const words = op.text.replace(/[^a-z\s]/g, " ").split(/\s+/).filter((w) => w.length > 3);
      const cur = reminders;
      let target = cur.find((r) => words.some((w) => r.label.toLowerCase().includes(w))) || cur[0];
      if (target) {
        setReminders((r) => r.filter((x) => x.id !== target.id));
        resolvePending("cancel_cron", `Cancelled “${target.label}”`);
        return `Cancelled the “${target.label.toLowerCase()}” reminder.`;
      }
      resolvePending("cancel_cron", "No reminder found");
      return "You don't have a reminder like that.";
    }
    if (op.type === "remember") {
      const id = nextId();
      const value = capitalize(op.value || "");
      setMemory((mm) => [{ id, value }, ...mm]);
      setMemEnter(id); setTimeout(() => setMemEnter(null), 260);
      setMemFlash(id); setTimeout(() => setMemFlash(null), 900);
      resolvePending("remember", `Remembered “${value}”`);
      return `Got it — I'll remember that ${(op.value || "preference").toLowerCase()}.`;
    }
    if (op.type === "recall") {
      resolvePending("recall", `Recalled ${memory.length} facts`);
      if (!memory.length) return "I don't have anything remembered yet.";
      return `Here's what I know: ${memory.map((m) => m.value.toLowerCase()).join("; ")}.`;
    }
    if (op.type === "list_todos") {
      resolvePending("list_todos", `Listed ${open.length} open`);
      const names = open.slice(0, 4).map((t) => `“${t.title}”`).join(", ");
      return open.length ? `You have ${open.length} open: ${names}${open.length > 4 ? "…" : "."}` : "Your list is all clear.";
    }
    if (op.type === "get_todo_stats") {
      const done = all.length - open.length;
      const pct = all.length ? Math.round((done / all.length) * 100) : 0;
      resolvePending("get_todo_stats", `${open.length} open · ${done} done`);
      return `You're ${pct}% done — ${open.length} open, ${done} completed.`;
    }
    // chat fallback (no tool)
    return "I can add, complete, delete, rename, schedule reminders, and remember things — try one of those.";
  };

  // ---------- the agent turn ----------
  const runAgent = async (text) => {
    setMessages((m) => [...m, { role: "user", text }]);
    setThinking(true); setBusy(true);
    await sleep(720);
    const ops = parseTurn(text);
    setThinking(false);
    setMessages((m) => [...m, { role: "assistant", text: "", steps: [] }]);

    const lines = [];
    for (const op of ops) {
      if (op.type === "chat") { lines.push(await execute(op)); continue; }
      pushPending(op.type);
      await sleep(460);
      lines.push(await execute(op));
      await sleep(240);
    }
    setLastText(lines.join(" "));
    setBusy(false);
    if (!chatOpen) setChatUnread((u) => u + 1);
  };

  // ---------- manual handlers ----------
  const onManualAdd = (title) => addTodo(title);
  const openChat = () => { setChatOpen(true); setChatUnread(0); };
  const togglePop = () => setPopOpen((p) => !p);
  const clearNotis = () => setNotifications((n) => n.map((x) => ({ ...x, read: true })));

  // close popover on outside click
  useEffect(() => {
    if (!popOpen) return;
    const onDoc = (e) => { if (!e.target.closest(".nav-wrap")) setPopOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [popOpen]);

  if (screen === "auth") {
    return <AuthScreen onLogin={(e) => { setEmail(e); setScreen("dashboard"); setTimeout(() => setChatOpen(true), 600); }} />;
  }

  const unread = notifications.filter((n) => !n.read).length;
  const initial = (email[0] || "Y").toUpperCase();

  return (
    <div className="app">
      <Header
        unread={unread} notifications={notifications} popOpen={popOpen}
        onTogglePop={togglePop} onClearNotis={clearNotis}
        initial={initial} badgePulse={badgePulse}
      />
      <div className="main">
        <h1 className="greeting">Today's focus</h1>
        <p className="subtle">Here's where things stand. Ask the assistant to make changes — watch them land.</p>
        <Stats todos={todos} />
        <div className="cols">
          <TodoList
            todos={todos} flashId={todoFlash} enteringId={todoEnter} removingId={removingId}
            onAdd={onManualAdd} onToggle={(id) => toggleTodo(id)} onDelete={(id) => removeTodo(id)}
          />
          <div className="side">
            <Reminders items={reminders} flashId={remFlash} enteringId={remEnter}
              onCancel={(id) => setReminders((r) => r.filter((x) => x.id !== id))} />
            <Memory items={memory} flashId={memFlash} enteringId={memEnter}
              onForget={(id) => setMemory((mm) => mm.filter((x) => x.id !== id))} />
          </div>
        </div>
      </div>

      <ChatWidget
        open={chatOpen} messages={messages} thinking={thinking} unread={chatUnread} busy={busy}
        onOpen={openChat} onClose={() => setChatOpen(false)} onSend={runAgent}
        onReset={() => { if (!thinking) setMessages(SEED_MSGS); }}
      />
      <Toasts items={toasts} onDismiss={(id) => setToasts((x) => x.filter((n) => n.id !== id))} />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
