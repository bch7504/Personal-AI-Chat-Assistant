import { useCallback, useEffect, useState } from 'react'
import {
  approveWorkspaceSupportGrant,
  listWorkspaceSupportGrants,
  rejectWorkspaceSupportGrant,
  revokeWorkspaceSupportGrant,
} from '../../api/workspaces'
import { useAuth } from '../../context/AuthContext'

export default function SupportGrantPanel({ workspaceId, canApprove }) {
  const { token } = useAuth()
  const [grants, setGrants] = useState([])
  const [error, setError] = useState('')
  const [workingId, setWorkingId] = useState('')

  const refresh = useCallback(() => {
    if (!workspaceId || !canApprove) return Promise.resolve()
    setError('')
    return listWorkspaceSupportGrants(token, workspaceId)
      .then(setGrants)
      .catch((err) => setError(err.detail || 'Could not load support requests.'))
  }, [token, workspaceId, canApprove])

  useEffect(() => { refresh() }, [refresh])

  const act = async (grantId, action) => {
    setWorkingId(grantId)
    setError('')
    try {
      await action(token, workspaceId, grantId)
      await refresh()
    } catch (err) {
      setError(err.detail || 'Could not update the support request.')
    } finally {
      setWorkingId('')
    }
  }

  if (!canApprove) return null
  const visible = grants.filter((grant) => grant.status === 'requested' || grant.status === 'approved')

  return (
    <section className="content-card settings-support p-3">
      <div className="card-toolbar">
        <div>
          <h3>Support access requests</h3>
          <span>Explicit, time-limited platform support access</span>
        </div>
      </div>
      {error && <div className="auth-error mb-2">{error}</div>}
      {!visible.length ? (
        <p className="text-muted small mb-0">No active or pending support requests.</p>
      ) : visible.map((grant) => (
        <div className="d-flex align-items-center justify-content-between gap-3 border-top py-2" key={grant.id}>
          <div>
            <strong>{grant.requested_scope}</strong>
            <small className="d-block text-muted">
              {grant.reason} · {grant.status === 'requested' ? 'request expires' : 'access expires'}{' '}
              {new Date(grant.expires_at).toLocaleString()}
            </small>
          </div>
          {grant.status === 'requested' ? (
            <div className="d-flex gap-2">
              <button
                className="btn btn-sm btn-outline-danger"
                disabled={workingId === grant.id}
                onClick={() => act(grant.id, rejectWorkspaceSupportGrant)}
              >
                Reject
              </button>
              <button
                className="btn btn-sm btn-primary"
                disabled={workingId === grant.id}
                onClick={() => act(grant.id, approveWorkspaceSupportGrant)}
              >
                Approve
              </button>
            </div>
          ) : (
            <button
              className="btn btn-sm btn-outline-danger"
              disabled={workingId === grant.id}
              onClick={() => act(grant.id, revokeWorkspaceSupportGrant)}
            >
              Revoke
            </button>
          )}
        </div>
      ))}
    </section>
  )
}
