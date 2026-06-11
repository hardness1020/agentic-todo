// agent.jsx — the richer cosmetic "agent": intent parsing, multi-step
// op extraction, and cron/schedule helpers. Pure logic, no React.
// (No real LLM — a local stand-in that mirrors the PRD's tool catalog.)

function capitalize(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

// Split a sentence into clauses on natural connectors.
function splitClauses(t) {
  return t
    .split(/\s*,\s*|\s+then\s+|\s+and then\s+|\s+also\s+|\s+and\s+(?=mark|complete|finish|delete|remove|remind|schedule|remember|note|add|create|rename|update|change|cancel|stop)/i)
    .map((c) => c.trim())
    .filter(Boolean);
}

// Turn free text into an ordered list of structured ops.
function parseTurn(text) {
  const ops = [];
  for (let clause of splitClauses(text.toLowerCase())) {
    const timey = /(every|hourly|daily|each|tomorrow|tonight|\bat \d|\d\s?(am|pm)|minute|min\b|hour|weekday|weekend|morning|evening|noon|week)/.test(clause);

    if (/(cancel|stop|remove|delete).*(reminder|schedule|cron|alert)/.test(clause) ||
        (/(cancel|stop)/.test(clause) && /reminder/.test(clause))) {
      ops.push({ type: "cancel_cron", text: clause });
    } else if (/(remember|note that|keep in mind|don't forget that|for future)/.test(clause)) {
      const v = clause.replace(/.*?(remember|note that|keep in mind|don't forget that|for future)\s*(that\s+)?/, "").trim();
      ops.push({ type: "remember", value: v });
    } else if (/(what do you (know|remember)|recall|what did i tell you|my preferences)/.test(clause)) {
      ops.push({ type: "recall", text: clause });
    } else if ((/(remind|schedule|reminder|set up|set a|nudge)/.test(clause)) && timey) {
      ops.push({ type: "schedule_cron", text: clause });
    } else if (/(rename|update|change|edit).*(to)\s+/.test(clause)) {
      ops.push({ type: "update_todo", text: clause });
    } else if (/(delete|remove|clear|get rid of|throw out)/.test(clause)) {
      ops.push({ type: "delete_todo", text: clause });
    } else if (/(complete|finish|mark.*done|\bdone\b|check off|tick off|cross off)/.test(clause)) {
      ops.push({ type: "complete_todo", text: clause });
    } else if (/(how many|stats|progress|how am i doing|how's my)/.test(clause)) {
      ops.push({ type: "get_todo_stats", text: clause });
    } else if (/(what's on|whats on|what is on|list|show me|what do i have|my todos|my list|to-?do)/.test(clause) && !/(add|create|new)/.test(clause)) {
      ops.push({ type: "list_todos", text: clause });
    } else if (/(add|create|new todo|put|i need to|i have to|remind me to|gotta)/.test(clause)) {
      let title = clause
        .replace(/.*?(add a todo to|add a todo|add task|add|create a todo|create|new todo to|new todo|put|remind me to|i need to|i have to|gotta)\s*/, "")
        .replace(/\bplease\b/g, "")
        .replace(/\bto my (list|todos)\b/g, "")
        .trim();
      title = capitalize(title);
      if (title) ops.push({ type: "create_todo", title });
      else ops.push({ type: "chat", text: clause });
    } else {
      ops.push({ type: "chat", text: clause });
    }
  }
  return ops.length ? ops : [{ type: "chat", text }];
}

// ----- selection of a target todo for complete/delete/update -----
const STOPWORDS = new Set([
  "the", "and", "todo", "task", "item", "this", "that", "one", "please", "off",
  "mark", "done", "complete", "completed", "finish", "finished", "check", "tick",
  "cross", "delete", "remove", "removed", "clear", "get", "rid", "throw", "out",
  "rename", "update", "change", "edit", "for", "you", "your", "with", "from",
]);
function pickTarget(open, all, text) {
  const pool = all;
  // explicit keyword match against titles, ignoring common command words
  const words = text.replace(/[^a-z\s]/g, " ").split(/\s+/)
    .filter((w) => w.length > 2 && !STOPWORDS.has(w));
  let hit = pool.find((t) => words.some((w) => t.title.toLowerCase().includes(w)));
  if (hit) return hit;
  if (/(newest|latest|last|most recent)/.test(text)) return (open[open.length - 1] || pool[pool.length - 1]);
  if (/(oldest|first|earliest)/.test(text)) return (open[0] || pool[0]);
  return open[0] || pool[0];
}

// ----- cron + schedule humanizers -----
function humanCron(t) {
  if (/(every )?(hour|hourly)/.test(t)) return "every hour";
  if (/weekday/.test(t)) return "every weekday at 9am";
  if (/weekend/.test(t)) return "every weekend at 10am";
  const min = t.match(/every (\d+)\s*(min|minute)/);
  if (min) return `every ${min[1]} minutes`;
  if (/(daily|every day|each day|morning)/.test(t)) return "every day at 9am";
  if (/evening|tonight/.test(t)) return "every day at 7pm";
  if (/noon/.test(t)) return "every day at noon";
  if (/(weekly|every week)/.test(t)) return "every Monday at 9am";
  if (/tomorrow/.test(t)) return "tomorrow at 9am";
  const at = t.match(/at (\d{1,2})\s?(am|pm)?/);
  if (at) return `every day at ${at[1]}${at[2] || "am"}`;
  return "in a minute";
}
function cronExpr(t) {
  if (/(every )?(hour|hourly)/.test(t)) return "0 * * * *";
  if (/weekday/.test(t)) return "0 9 * * 1-5";
  if (/weekend/.test(t)) return "0 10 * * 0,6";
  const min = t.match(/every (\d+)\s*(min|minute)/);
  if (min) return `*/${min[1]} * * * *`;
  if (/(daily|every day|each day|morning)/.test(t)) return "0 9 * * *";
  if (/evening|tonight/.test(t)) return "0 19 * * *";
  if (/(weekly|every week)/.test(t)) return "0 9 * * 1";
  return "* * * * *";
}
function reminderBody(t) {
  const m = t.match(/(?:remind me to|reminder to|nudge me to|schedule|to)\s+(.*?)(?:\s+every|\s+each|\s+at\b|\s+daily|\s+hourly|\s+tomorrow|\s+tonight|\s+in \d|$)/);
  let body = m && m[1] ? m[1].trim() : "";
  body = body.replace(/\b(a reminder|reminder)\b/g, "").trim();
  return body || "your scheduled reminder";
}
function nextFireLabel(t) {
  if (/(every )?(hour|hourly)/.test(t)) return "next in ~1h";
  const min = t.match(/every (\d+)\s*(min|minute)/);
  if (min) return `next in ~${min[1]}m`;
  if (/weekday|daily|every day|morning/.test(t)) return "next at 9am";
  return "next in ~1m";
}

Object.assign(window, { parseTurn, pickTarget, humanCron, cronExpr, reminderBody, nextFireLabel, capitalize });
