import { useEffect } from 'react'
import { Link } from 'react-router-dom'

export const SUPPORT_EMAIL = import.meta.env.VITE_SUPPORT_EMAIL || 'fanbox2004@gmail.com'

export function PublicPageMeta({ title, description }) {
  useEffect(() => {
    const previousTitle = document.title
    const descriptionTag = document.querySelector('meta[name="description"]')
    const previousDescription = descriptionTag?.getAttribute('content')

    document.title = title
    if (descriptionTag) descriptionTag.setAttribute('content', description)

    return () => {
      document.title = previousTitle
      if (descriptionTag && previousDescription !== null) {
        descriptionTag.setAttribute('content', previousDescription)
      }
    }
  }, [description, title])

  return null
}

export default function PublicPageLayout({ children }) {
  return (
    <div className="public-site">
      <header className="public-header">
        <Link className="public-brand" to="/login" aria-label="Orbit sign in">
          <span><i className="bi bi-command" /></span>
          <strong>Orbit</strong>
          <small>AI Calendar</small>
        </Link>
        <nav aria-label="Public navigation">
          <Link to="/privacy">Privacy</Link>
          <Link to="/terms">Terms</Link>
        </nav>
        <div className="public-header-actions">
          <Link className="btn btn-light" to="/login">Sign in</Link>
          <Link className="btn btn-primary" to="/register">Get started</Link>
        </div>
      </header>

      {children}

      <footer className="public-footer">
        <div>
          <Link className="public-brand" to="/login">
            <span><i className="bi bi-command" /></span>
            <strong>Orbit</strong>
          </Link>
          <p>AI-assisted work and two-way Google Calendar event synchronization.</p>
        </div>
        <nav aria-label="Legal navigation">
          <Link to="/privacy">Privacy Policy</Link>
          <Link to="/terms">Terms of Service</Link>
          <a href={`mailto:${SUPPORT_EMAIL}`}>Contact</a>
        </nav>
        <small>© 2026 Orbit. All rights reserved.</small>
      </footer>
    </div>
  )
}
