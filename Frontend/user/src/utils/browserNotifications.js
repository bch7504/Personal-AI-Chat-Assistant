export function isNotificationSupported() {
  return typeof window !== 'undefined' && 'Notification' in window
}

export function getNotificationPermission() {
  return isNotificationSupported() ? Notification.permission : 'unsupported'
}

export async function requestNotificationPermission() {
  if (!isNotificationSupported()) return 'unsupported'
  if (Notification.requestPermission.length === 0) return Notification.requestPermission()
  return new Promise(resolve => Notification.requestPermission(resolve))
}

export function notifyTaskSuggested(task, { onClick } = {}) {
  if (!isNotificationSupported() || Notification.permission !== 'granted') return null
  try {
    const notification = new Notification('Orbit spotted a commitment', {
      body: task.title,
      tag: `task-suggested-${task.id}`,
    })
    notification.onclick = () => {
      window.focus()
      onClick?.()
      notification.close()
    }
    return notification
  } catch {
    return null
  }
}

export function notifyReminderFired(reminder, { onClick } = {}) {
  if (!isNotificationSupported() || Notification.permission !== 'granted') return null
  try {
    const notification = new Notification(reminder.title || 'Orbit reminder', {
      body: reminder.message || 'Đã đến giờ cho việc bạn cần theo dõi.',
      tag: `reminder-fired-${reminder.id}`,
      requireInteraction: true,
    })
    notification.onclick = () => {
      window.focus()
      onClick?.()
      notification.close()
    }
    return notification
  } catch {
    return null
  }
}
