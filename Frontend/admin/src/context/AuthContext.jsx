import { createContext, useContext, useEffect, useState } from 'react'
import * as authApi from '../api/auth'

const TOKEN_KEY = 'orbit_admin_token'
const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!token) { setUser(null); setLoading(false); return }
    setLoading(true)
    authApi.getMe(token)
      .then(setUser)
      .catch(() => { localStorage.removeItem(TOKEN_KEY); setToken(null); setUser(null) })
      .finally(() => setLoading(false))
  }, [token])

  const login = async (email, password) => {
    const data = await authApi.login({ email, password })
    if (data.user?.platform_role !== 'platform_admin') throw new Error('Platform administrator access is required.')
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setToken(data.access_token)
    setUser(data.user)
  }

  const logout = () => { localStorage.removeItem(TOKEN_KEY); setToken(null); setUser(null) }
  const isAdmin = user?.platform_role === 'platform_admin'

  return <AuthContext.Provider value={{ token, user, loading, isAdmin, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used within AuthProvider')
  return value
}
