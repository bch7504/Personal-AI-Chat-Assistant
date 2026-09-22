import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import ToastStack from '../components/common/ToastStack'

const ToastContext = createContext(null)
let nextId = 0

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const timers = useRef(new Map())

  const dismissToast = useCallback((id) => {
    setToasts(previous => previous.filter(toast => toast.id !== id))
    const timer = timers.current.get(id)
    if (timer) clearTimeout(timer)
    timers.current.delete(id)
  }, [])

  const pushToast = useCallback((message, variant = 'error') => {
    const id = ++nextId
    setToasts(previous => [...previous, { id, variant, message }])
    timers.current.set(id, setTimeout(() => dismissToast(id), 5000))
  }, [dismissToast])

  useEffect(() => () => {
    for (const timer of timers.current.values()) clearTimeout(timer)
    timers.current.clear()
  }, [])

  return (
    <ToastContext.Provider value={{ pushToast }}>
      {children}
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </ToastContext.Provider>
  )
}

export function useToast() {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast must be used within a ToastProvider')
  return context
}
