// Bottom-left notification toasts (clear of the chat FAB).
import Icon from './Icon.jsx'

export default function Toasts({ items, onDismiss }) {
  return (
    <div className="toasts">
      {items.map((n) => (
        <div className="toast" key={n.id}>
          <span className="ic">
            <Icon name="bell" size={19} />
          </span>
          <div>
            <div className="tt">{n.title}</div>
            {n.body && <div className="ts">{n.body}</div>}
          </div>
          <button className="x" onClick={() => onDismiss(n.id)} aria-label="Dismiss">
            <Icon name="x" size={17} />
          </button>
        </div>
      ))}
    </div>
  )
}
