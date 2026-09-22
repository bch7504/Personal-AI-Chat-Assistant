import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useAuth } from './AuthContext'

const THEME_STORAGE_KEY = 'orbit-theme-mode'
const THEME_MODES = new Set(['light', 'dark', 'system'])
const ThemeContext = createContext(null)

const storedTheme = () => {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY)
    return THEME_MODES.has(value) ? value : null
  } catch {
    return null
  }
}

const systemPrefersDark = () => window.matchMedia?.('(prefers-color-scheme: dark)').matches === true

export function ThemeProvider({ children }) {
  const { user } = useAuth()
  const [themeMode, setThemeModeState] = useState(() => storedTheme() || 'system')
  const [systemDark, setSystemDark] = useState(systemPrefersDark)

  useEffect(() => {
    const query = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!query) return undefined
    const update = event => setSystemDark(event.matches)
    query.addEventListener?.('change', update)
    return () => query.removeEventListener?.('change', update)
  }, [])

  useEffect(() => {
    if (storedTheme()) return
    const profileTheme = user?.preferences?.theme
    if (THEME_MODES.has(profileTheme)) setThemeModeState(profileTheme)
  }, [user?.preferences?.theme])

  const resolvedTheme = themeMode === 'system' ? (systemDark ? 'dark' : 'light') : themeMode

  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = resolvedTheme
    root.style.colorScheme = resolvedTheme
    const themeColor = document.querySelector('meta[name="theme-color"]')
    themeColor?.setAttribute('content', resolvedTheme === 'dark' ? '#0d1220' : '#4466f2')
  }, [resolvedTheme])

  const setThemeMode = useCallback(mode => {
    if (!THEME_MODES.has(mode)) return
    try { window.localStorage.setItem(THEME_STORAGE_KEY, mode) } catch { /* Theme still works for this session. */ }
    setThemeModeState(mode)
  }, [])

  const toggleTheme = useCallback(() => {
    setThemeMode(resolvedTheme === 'dark' ? 'light' : 'dark')
  }, [resolvedTheme, setThemeMode])

  const value = useMemo(() => ({ themeMode, resolvedTheme, setThemeMode, toggleTheme }), [themeMode, resolvedTheme, setThemeMode, toggleTheme])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme must be used within ThemeProvider')
  return context
}
