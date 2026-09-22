import React from 'react'
import ReactDOM from 'react-dom/client'
import 'bootstrap/dist/css/bootstrap.min.css'
import 'bootstrap-icons/font/bootstrap-icons.css'
import 'bootstrap/dist/js/bootstrap.bundle.min.js'
import '../../shared/styles.css'
import './admin.css'
import './workspace-admin.css'
import AppRouter from './router/AppRouter'
import { AuthProvider } from './context/AuthContext'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode><AuthProvider><AppRouter /></AuthProvider></React.StrictMode>,
)
