export default function ToastStack({ toasts, onDismiss }) {
  if (!toasts.length) return null
  return (
    <div style={{ position: 'fixed', top: 24, right: 24, zIndex: 1100, display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 360 }}>
      {toasts.map(toast => (
        <div
          key={toast.id}
          role="alert"
          className={`border rounded-3 p-3 bg-body shadow-lg d-flex align-items-start gap-2 border-${toast.variant === 'success' ? 'success' : 'danger'}`}
        >
          <i className={`bi ${toast.variant === 'success' ? 'bi-check-circle-fill text-success' : 'bi-exclamation-triangle-fill text-danger'} fs-5`} />
          <div className="flex-grow-1"><small>{toast.message}</small></div>
          <button className="btn-close" aria-label="Đóng" onClick={() => onDismiss(toast.id)} />
        </div>
      ))}
    </div>
  )
}
