import { apiFetch } from './client'

export const register = ({ email, password, display_name }) =>
  apiFetch('/auth/register', { method: 'POST', body: { email, password, display_name } })

export const registerAdmin = ({ email, password, display_name, bootstrap_key }) =>
  apiFetch('/auth/admin/register', {
    method: 'POST',
    body: { email, password, display_name, bootstrap_key },
  })

export const login = ({ email, password }) => apiFetch('/auth/login', { method: 'POST', body: { email, password } })

export const listDemoAccounts = () => apiFetch('/auth/demo-accounts')

export const demoLogin = (account_key) =>
  apiFetch('/auth/demo-login', { method: 'POST', body: { account_key } })

export const adminLogin = ({ email, password }) =>
  apiFetch('/auth/admin/login', { method: 'POST', body: { email, password } })

// One endpoint handles both first-time signup and returning login for a Google account - see
// src/api/auth_routes.py::google_auth.
export const googleAuth = (id_token) => apiFetch('/auth/google', { method: 'POST', body: { id_token } })

export const getMe = (token) => apiFetch('/auth/me', { token })

export const updateProfile = (token, updates) => apiFetch('/auth/me', { method: 'PATCH', token, body: updates })

export const changePassword = (token, { current_password, new_password }) =>
  apiFetch('/auth/me/password', { method: 'POST', token, body: { current_password, new_password } })
