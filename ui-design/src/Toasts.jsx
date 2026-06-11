// Toasts.jsx — fired-reminder notification toasts (bottom-left, clear of chat).
function Toasts({ items, onDismiss }) {
  return (
    <div className="toasts">
      {items.map((n) => (
        <div className="toast" key={n.id}>
          <span className="ic"><Icon name="bell" size={19} /></span>
          <div>
            <div className="tt">{n.title}</div>
            <div className="ts">{n.body}</div>
          </div>
          <button className="x" onClick={() => onDismiss(n.id)} aria-label="Dismiss">
            <Icon name="x" size={17} />
          </button>
        </div>
      ))}
    </div>
  );
}
window.Toasts = Toasts;
