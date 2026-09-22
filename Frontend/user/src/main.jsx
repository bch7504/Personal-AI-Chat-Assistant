import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { GoogleOAuthProvider } from '@react-oauth/google'
import 'bootstrap/dist/css/bootstrap.min.css'
import 'bootstrap-icons/font/bootstrap-icons.css'
import 'bootstrap/dist/js/bootstrap.bundle.min.js'
import '../../shared/styles.css'
import './assistant.css'
import './workspace-management.css'
import './workspace-agent.css'
import './theme.css'
import './public.css'
import AppRouter from './router/AppRouter'
import { AuthProvider } from './context/AuthContext'
import { WorkspaceProvider } from './context/WorkspaceContext'
import { ToastProvider } from './context/ToastContext'
import { ThemeProvider } from './context/ThemeContext'
import { queryClient } from './query/queryClient'

// Empty clientId just disables the Google button's provider context (GoogleLogin quietly
// no-ops/errors on click instead of crashing at import time) when GOOGLE_OAUTH is unset - dev
// without a Google Cloud OAuth client configured still works for the existing email/password flow.
ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <GoogleOAuthProvider clientId={import.meta.env.VITE_GOOGLE_CLIENT_ID || ''}>
        <ToastProvider>
          <AuthProvider><ThemeProvider><WorkspaceProvider><AppRouter /></WorkspaceProvider></ThemeProvider></AuthProvider>
        </ToastProvider>
      </GoogleOAuthProvider>
    </QueryClientProvider>
  </React.StrictMode>
)
