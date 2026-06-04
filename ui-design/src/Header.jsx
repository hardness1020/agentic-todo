// Header.jsx — sticky header (brand, notifications bell + popover, avatar)
// plus the Stats bar + momentum.

function Header({ unread, notifications, popOpen, onTogglePop, onClearNotis, initial, badgePulse }) {
  return (
    <header className="hdr">
      <div className="brand">
        <span className="wm">ToDo</span>
      </div>
      <div className="nav-wrap">
        <button
          className={"icon-btn" + (popOpen ? " active" : "")}
          onClick={onTogglePop}
          aria-label="Notifications"
        >
          <Icon name={unread > 0 ? "bell-ring" : "bell"} />
          {unread > 0 && <span className={"dot" + (badgePulse ? " pulse" : "")}>{unread}</span>}
        </button>
        {popOpen && (
          <NotificationsPopover notifications={notifications} onClear={onClearNotis} />
        )}
      </div>
      <div className="avatar">{initial}</div>
    </header>
  );
}
window.Header = Header;

function NotificationsPopover({ notifications, onClear }) {
  const hasUnread = notifications.some((n) => !n.read);
  return (
    <div className="pop" role="dialog" aria-label="Notifications">
      <div className="pop-h">
        <h3>Notifications</h3>
        {hasUnread && <button className="clear" onClick={onClear}>Mark all read</button>}
      </div>
      <div className="pop-list">
        {notifications.length === 0 && (
          <div className="pop-empty">You're all caught up.<br />Reminders you schedule land here.</div>
        )}
        {notifications.map((n) => (
          <div className={"noti" + (n.read ? "" : " unread")} key={n.id}>
            <span className="ic"><Icon name="bell" size={17} /></span>
            <div className="body">
              <div className="tt">{n.title}</div>
              <div className="bd">{n.body}</div>
              <div className="tm">{n.time}</div>
            </div>
            {!n.read && <span className="unread-dot" />}
          </div>
        ))}
      </div>
    </div>
  );
}

function Stats({ todos }) {
  const done = todos.filter((t) => t.done).length;
  const open = todos.length - done;
  const pct = todos.length ? Math.round((done / todos.length) * 100) : 0;
  return (
    <React.Fragment>
      <div className="stats">
        <div className="stat accent"><div className="num">{open}</div><div className="lab">open</div></div>
        <div className="stat good"><div className="num">{done}</div><div className="lab">done</div></div>
        <div className="stat"><div className="num">{todos.length}</div><div className="lab">total</div></div>
      </div>
      <div className="momentum">
        <div className="track"><div className="fill" style={{ width: pct + "%" }} /></div>
        <span className="pct">{pct}% done today</span>
      </div>
    </React.Fragment>
  );
}
window.Stats = Stats;
