# Workspace Agent RBAC and authorization matrix

## 1. Production invariants

1. A user can have at most one active specialist Agent Workspace assignment in an organization.
2. Organization membership alone never grants Agent access. The user also needs an active `AgentWorkspaceMembership` with business role `lead` or `member`.
3. A linked group is readable only when it is active, AI-enabled, has the correct domain classification, and remains inside the server-resolved consent allowlist.
4. A Lead receives all eligible groups linked to their Agent Workspace. A Member receives only the intersection of those groups with their live conversation participation.
5. Client-supplied workspace, group, release, record, owner, and role values are untrusted. Every read and write is re-authorized on the backend.
6. LLM output cannot grant access, expand scope, approve a release, verify evidence, or execute a privileged mutation.
7. Revoked organization, Agent Workspace, conversation, or AI-consent access takes effect on the next request.
8. Mutations use audit events; state transitions use row-version optimistic concurrency where applicable.

## 2. Assignment and administration

| Operation | Platform admin | Agent Lead | Agent Member | Unassigned user |
|---|---:|---:|---:|---:|
| Create/disable Agent Workspace | Yes | No | No | No |
| Assign/change Lead | Yes | No | No | No |
| Add/revoke Agent Member | Yes | No | No | No |
| Link/unlink data-source groups | Yes | No | No | No |
| Open assigned Workspace Agent | If explicitly assigned | Yes | Yes | No |

Administrative authority and business authority are deliberately separate: an Agent Lead governs delivery or quality work, while platform administration controls membership and source assignment.

## 3. Product Delivery Agent

| Capability | Delivery Lead | Delivery Member |
|---|---|---|
| Read brief/dashboard | All authorized workspace groups and bound work | Only own tasks/milestones in groups the member actively participates in |
| Select a group for analysis | Yes | No; backend fixes the effective member scope |
| Read people/risks/messages | Workspace scope | Only scoped data required for the member view |
| Create/update dependency records | Yes | No direct governance write |
| Create/update decision records | Yes | No direct governance write |
| Create/manage Delivery-to-QA release handoff | Yes | No |
| Update tasks | Own tasks and Lead-authorized management paths | Own tasks only |
| Create durable action proposal | Yes | Yes, but only for a target already in the proposer's current scope |
| List/approve/reject action proposals | Yes | No |

For Member proposals, approval does not switch execution to the wider Lead scope. At approval time the backend re-resolves the original proposer's current scope, compares its consent hash with the stored hash, and executes only within that scope. This prevents a Lead endpoint from becoming a confused deputy.

## 4. Quality Assurance Agent

| Capability | QA Lead | QA Member |
|---|---|---|
| Read QA brief/control plane | All authorized QA groups | Own QA work and operational records in participant groups |
| Select a group for analysis | Yes | No; backend fixes the effective member scope |
| Create requirements/test-case definitions | Yes | No |
| Create/activate quality policy | Yes | No |
| Submit evidence | Yes | Yes, in an authorized participant group |
| Create/execute test run | Yes | Yes, in an authorized participant group |
| Report defect | Yes | Yes; a Member may assign only to self and omitted owner defaults to self |
| Transition test run/defect | Yes | Own test runs and own/created defects only |
| Verify/reject evidence | Yes | No, including evidence submitted by self |
| Create/decide waiver | Yes | No |
| Start/approve/reject release | Yes, subject to deterministic readiness gate | No |
| View release handoffs | All assigned to the QA workspace | Only release keys represented by the Member's own scoped QA work |
| Create durable action proposal | Yes | Yes, only for a target in current scope |
| List/approve/reject action proposals | Yes | No |

The QA split follows separation of duties: Members produce execution evidence; Leads own governance, independent verification, exceptions, and release decisions.

## 5. Enforcement chain

Every specialist request follows this chain:

`authenticated user -> active organization membership -> active Agent Workspace membership -> profile match -> business role -> linked AI-consented groups -> live participant intersection for Member -> resource ownership/action rule -> row-version check -> audit event`

A failure at any step is fail-closed. The frontend capability response only controls presentation; it is not trusted as authorization proof.

## 6. UI behavior

- The sidebar exposes one generic **Workspace Agent** entry.
- The router loads the single Agent Workspace assigned to the signed-in user.
- An unassigned user sees an empty permission state and no agent chat.
- A user with multiple active specialist assignments receives an invalid-assignment state rather than a workspace selector.
- Lead-only controls are not rendered for Members.
- QA Member operational forms include evidence, test run, and defect; governance and release-decision controls remain hidden.

## 7. Regression coverage

Automated tests cover:

- assigned versus unassigned/revoked access;
- Lead full scope versus Member participant-group intersection;
- Product Member own-work filtering;
- QA Member operational writes and Lead-only governance denials;
- QA Member denial for a hidden group and hidden release handoff;
- self-evidence verification denial and Lead verification success;
- Member ownership checks for QA record transitions;
- Member proposal target binding, Lead approval, idempotency, stale row versions, and out-of-scope denial;
- structured Product Delivery-to-QA handoff and deterministic release-gate enforcement.
