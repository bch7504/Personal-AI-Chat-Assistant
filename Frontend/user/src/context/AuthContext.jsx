import { createContext, useContext, useEffect, useState } from 'react'
import * as authApi from '../api/auth'
import { useToast } from './ToastContext'
import { queryClient } from '../query/queryClient'

const TOKEN_KEY = 'orbit_token'
const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const { pushToast } = useToast()
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!token) { setUser(null); setLoading(false); return }
    authApi.getMe(token)
      .then(setUser)
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY)
        setToken(null)
        setUser(null)
        pushToast('Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại.')
      })
      .finally(() => setLoading(false))
  }, [token, pushToast])

  const login = async (email, password) => {
    const data = await authApi.login({ email, password })
    queryClient.clear()
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setUser(data.user)
    setToken(data.access_token)
    return data
  }

  const loginDemo = async (accountKey) => {
    const data = await authApi.demoLogin(accountKey)
    queryClient.clear()
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setUser(data.user)
    setToken(data.access_token)
    return data
  }

  const register = async (email, password, display_name) => {
    const data = await authApi.register({ email, password, display_name })
    queryClient.clear()
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setUser(data.user)
    setToken(data.access_token)
    return data
  }

  const loginAdmin = async (email, password) => {
    const data = await authApi.adminLogin({ email, password })
    queryClient.clear()
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setUser(data.user)
    setToken(data.access_token)
    return data
  }

  const registerAdmin = async (email, password, display_name, bootstrapKey) => {
    const data = await authApi.registerAdmin({
      email,
      password,
      display_name,
      bootstrap_key: bootstrapKey,
    })
    queryClient.clear()
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setUser(data.user)
    setToken(data.access_token)
    return data
  }

  // Handles both first-time signup and returning login transparently (find-or-create on the
  // backend) - same as login/register above, just fed a Google ID token instead of a password.
  const loginWithGoogle = async (idToken) => {
    const data = await authApi.googleAuth(idToken)
    queryClient.clear()
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setUser(data.user)
    setToken(data.access_token)
    return data
  }

  const logout = () => {
    queryClient.clear()
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
  }

  const updateProfile = async (updates) => {
    const updated = await authApi.updateProfile(token, updates)
    setUser(updated)
    return updated
  }

  const changePassword = (passwords) => authApi.changePassword(token, passwords)

  const isAdmin = user?.platform_role === 'platform_admin'

  return (
    <AuthContext.Provider
      value={{ user, token, loading, isAdmin, login, loginDemo, loginAdmin, register, registerAdmin, loginWithGoogle, logout, updateProfile, changePassword }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
