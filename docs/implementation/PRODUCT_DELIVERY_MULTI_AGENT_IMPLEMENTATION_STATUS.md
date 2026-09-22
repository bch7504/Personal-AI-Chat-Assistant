# Product Delivery Multi-Agent — implementation status

> Verified: 2026-08-29  
> Architecture baseline: `PRODUCT_DELIVERY_ADAPTIVE_ORCHESTRATION_PLAN_V3.md`  
> Overall: **adaptive agent-first production MVP implemented; staged rollout and advanced data foundations remain**

## 1. Operational architecture

Product Delivery chat now selects the minimum sufficient path:

```text
Member / Lead -> Workspace Agent
  -> greeting/help/clarification: policy response, no business data
  -> single-domain business: one LLM-backed specialist
  -> cross-domain business: bounded specialist DAG
  -> one governed response
```

There is no direct-tool chatbot response for a business-data request. Exact task lookup is delegated to Task Intelligence, which invokes `get_delivery_task_details`, reasons over the minimal authorized result with an LLM, and returns a typed result to the Workspace Agent. Greetings, acknowledgements, role-aware capability help, clarification, out-of-scope turns and hard refusals use deterministic `workspace_only`: zero LLM calls, zero specialists and zero business-data reads. The direct-tool contract remains only as an internal compatibility primitive and is not emitted by the chat router.

Active specialists (one agent per independent business capability, not per tool):

- Delivery Task Intelligence — exact task, My Work and group/workspace task aggregation
- Risk & Dependency
- Planning & Forecast
- Evidence & Knowledge

Capacity & Flow remains feature-gated because reliable capacity and historical flow data are not yet sufficient for workforce recommendations.

## 2. Multi-agent and governance controls

- The Workspace Agent is the only user-facing agent and owns intent routing, delegation, dependency ordering, failure policy and final synthesis.
- Unknown text fails safely to clarification; it can no longer trigger an implicit Delivery Health scan.
- Specialists cannot call each other directly. The supervisor creates a bounded DAG and passes only validated upstream results to dependent agents.
- Agent-to-agent inputs carry workflow/run identity, tenant/workspace scope, subject references, dependency IDs, allowed tools, context hash and authorization expiry.
- Agent-to-agent outputs carry facts, metrics, gaps, recommendations, sources, model usage, tool-call summaries, upstream-result hashes and an output hash.
- Downstream facts are accepted only when their declared upstream hashes match completed dependency results.
- Tools remain deterministic data/action adapters. The runtime validates the specialist registry, allowlist and tool-call budget before every invocation.
- Workspace membership, business role, source groups and consent are revalidated server-side before dispatch.
- Writes remain proposal/approval operations with optimistic locking and durable audit records.
- Workflow, supervisor run, child run, event, lineage, model, token, fallback and tool-call metadata are persisted.
- The UI exposes execution mode, specialist status, tools used, upstream-agent count, model usage, gaps/fallbacks and Lead approvals.

## 3. Agent-first plan status

| Item | Status | Evidence / remaining boundary |
|---|---|---|
| AF-MA-01 — Task Intelligence | Complete for MVP | Exact and scoped task reads are LLM-backed specialist executions using an authorized task tool. |
| AF-MA-02 — Agent-first routing | Complete | Accepted chat requests cannot use `direct_tool`; disabled router/supervisor/specialist-LLM configuration fails closed. |
| AF-MA-03 — A2A contracts | Complete for MVP | Dependency IDs, subject references, validated upstream hashes, sources, usage and tool summaries are typed and persisted. |
| AF-MA-04 — Supervisor DAG | Complete for MVP | Ready nodes execute in bounded parallel stages; dependent nodes receive validated prior results; unresolved DAGs fail closed. |
| AF-MA-05 — Tool boundary | Complete for production MVP | Runtime-visible executor uses only the server-authorized data pack and registry allowlist. A separately deployed signed callback Tool Gateway is the hardened end state. |
| AF-MA-06 — Persistence/API/UI | Complete for MVP | Migration 26 adds run lineage; APIs and UI expose agent communication without leaking the broad workspace snapshot. |
| AF-MA-07 — Quality gates | Local gates complete | Regression, lint, frontend build, migration and Docker E2E pass. Load, fault-injection, adversarial canary and production SLO gates require staging/traffic. |

Adaptive amendment AO-MA-01 through AO-MA-04 is implemented: conversational routing, no unnecessary execution, minimal specialist selection and Member forged-scope HTTP 403 are covered by automated and live E2E checks.

The older PD-MA backlog remains useful for domain rollout. Work, Risk, Planning and Evidence vertical slices are operational; asynchronous outbox/resume, richer history/baselines, Capacity activation and production canary remain deferred.

## 4. Verification evidence

Kết quả regression và live chat mới nhất được ghi tại
[Kết quả kiểm thử Multi-Agent 2026-08-29](../reports/MULTI_AGENT_EVALUATION_RESULTS_2026-08-29.md). Chu kỳ này bổ sung
checkpoint handoff, routing-precedence matrix, deterministic follow-up memory và cross-profile raw-data denial.

Verification performed on 2026-08-27:

- Python regression suite: `499 passed, 1 skipped`.
- Focused agent-first tests cover exact-task delegation, allowlist tampering rejection, supervisor DAG result chaining, RBAC and per-run lineage/model usage.
- Ruff on the changed orchestration/runtime/API scope: passed.
- Frontend production build: passed (`765` modules transformed).
- Docker Compose configuration: valid.
- PostgreSQL migration: `20260827_26 (head)`.
- Backend and isolated Product Delivery runtime health checks: ready.
- Exact-task E2E: `single_specialist`, `task_lookup`, Task Intelligence completed with `llm_used=true`, two total LLM calls, `get_delivery_task_details`, one authorized fact, persisted lineage and no broad portfolio payload.
- Blocker E2E: `multi_specialist`, Task Intelligence completed first; Risk and Planning consumed its exact output hash as an upstream dependency; four total LLM calls and persisted per-agent tool/lineage records.
- RBAC E2E: authorized Member succeeded within assigned scope; an account outside the workspace received HTTP 403.
- Adaptive routing E2E: `hello` returns `workspace_only`, one Workspace LLM, zero specialist, zero source and no new Delivery workflow; capability help and ambiguous input also avoid portfolio reads. An unassigned account receives no available Agent Workspace and HTTP 403 on direct chat access.
- Scope-forgery E2E: Member-selected Customer Portal now returns HTTP 403 rather than the previous unhandled 500.

One live Risk result was rejected by the output guardrail and safely replaced by deterministic fallback. This is expected fail-safe behavior and is surfaced in the result; it is not reported as a zero-fallback run.

## 5. Remaining production gates

1. Replace the transitional authorized-data-pack executor with a separately deployed, signed and short-lived Tool Gateway callback when runtime isolation crosses a trust boundary.
2. Add durable asynchronous dispatch/outbox/resume if workflows become long-running or cross-process; keep the synchronous DAG for short reads.
3. Capture immutable task/milestone history and planning baselines before enabling strong forecast/change-impact claims.
4. Establish capacity inputs and fairness policy before enabling Capacity & Flow recommendations.
5. Run staging load, provider-failure, timeout and prompt-injection suites; define p95 latency, error, fallback and cost alerts.
6. Canary with Delivery teams and measure time-to-decision, blocker age, stale-work reduction and approval acceptance.
7. Replace local JWT/signing values with managed secrets before any non-local deployment.

The intended boundary is deliberate: the Workspace Agent owns conversation and clarification, specialists own bounded business reasoning, and tools own deterministic access/actions. Multi-agent is used only where delegation or cross-domain reasoning creates real user value; simple business reads use one specialist, while non-business conversational turns use none.
