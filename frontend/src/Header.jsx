// Sticky header: brand wordmark, notifications bell + popover, avatar, log out.
import Icon from './Icon.jsx'
import { relativeTime } from './util.js'

export default function Header({
  unread,
  notifications,
  popOpen,
  onTogglePop,
  onMarkAllRead,
  onClear,
  initial,
  badgePulse,
  onLogout,
}) {
  return (
    <header className="hdr">
      <div className="brand">
        <span className="mark">
          <Icon name="check" size={16} stroke={3} />
        </span>
        <span className="wm">ToDo</span>
      </div>
      <div className="nav-wrap">
        <button
          className={'icon-btn' + (popOpen ? ' active' : '')}
          onClick={onTogglePop}
          aria-label="Notifications"
        >
          <Icon name={unread > 0 ? 'bell-ring' : 'bell'} />
          {unread > 0 && (
            <span className={'dot' + (badgePulse ? ' pulse' : '')}>{unread}</span>
          )}
        </button>
        {popOpen && (
          <NotificationsPopover
            notifications={notifications}
            onMarkAllRead={onMarkAllRead}
            onClear={onClear}
          />
        )}
      </div>
      <div className="avatar">{initial}</div>
      <button className="logout" onClick={onLogout}>
        Log out
      </button>
    </header>
  )
}

function NotificationsPopover({ notifications, onMarkAllRead, onClear }) {
  const hasUnread = notifications.some((n) => !n.read)
  return (
    <div className="pop" role="dialog" aria-label="Notifications">
      <div className="pop-h">
        <h3>Notifications</h3>
        {hasUnread && (
          <button className="clear right" onClick={onMarkAllRead}>
            Mark all read
          </button>
        )}
        {notifications.length > 0 && (
          <button className={'clear' + (hasUnread ? '' : ' right')} onClick={onClear}>
            Clear
          </button>
        )}
      </div>
      <div className="pop-list">
        {notifications.length === 0 && (
          <div className="pop-empty">
            You're all caught up.
            <br />
            Reminders you schedule land here.
          </div>
        )}
        {notifications.map((n) => (
          <div className={'noti' + (n.read ? '' : ' unread')} key={n.id}>
            <span className="ic">
              <Icon name="bell" size={17} />
            </span>
            <div className="body">
              <div className="tt">{n.title}</div>
              {n.body && <div className="bd">{n.body}</div>}
              <div className="tm">{relativeTime(n.created_at)}</div>
            </div>
            {!n.read && <span className="unread-dot" />}
          </div>
        ))}
      </div>
    </div>
  )
}
