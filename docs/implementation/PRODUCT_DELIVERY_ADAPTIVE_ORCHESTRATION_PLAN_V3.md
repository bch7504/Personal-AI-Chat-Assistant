# Product Delivery Adaptive Orchestration Plan v3

> Status: canonical routing and cost-control amendment  
> Date: 2026-08-27  
> Supersedes: the rule that every accepted chat turn must invoke a specialist and the default fallback from unknown text to Delivery Health  
> Retains: Workspace Agent as the only conversational entry point, specialist LLMs for business reasoning, deterministic tools, RBAC, A2A lineage, HITL and auditability

## 1. Corrected product principle

The system must use the **minimum sufficient orchestration** for the user's actual goal.

- A conversational turn is not automatically a business-data request.
- A business-data request invokes the smallest sufficient specialist set.
- Cross-domain analysis creates a bounded DAG only when the question genuinely needs multiple independent capabilities.
- Uncertainty triggers clarification, never an implicit portfolio-wide scan.
- More agents are not evidence of better multi-agent design. Correct delegation, isolated context, governed result chaining and measurable business value are.

## 2. Target decision pipeline

```text
authenticate + resolve workspace membership
  -> hard input/security policy
  -> high-confidence intent routing
      -> workspace_only
      -> single_specialist
      -> multi_specialist DAG
      -> clarification / out_of_scope
  -> revalidate source scope before every business read
  -> execute only the selected path
  -> output guardrail + audit + memory
```

The router chooses a plan; it does not grant authorization. A user message cannot request a higher role, add a source or choose its own specialist/tool allowlist.

## 3. Execution modes and budgets

| Mode | Use case | Specialist count | Target LLM calls | Business data read | Durable business workflow |
|---|---|---:|---:|---:|---:|
| `workspace_only` | greeting, thanks, capability help, clarification, out-of-scope | 0 | 1 Workspace LLM; 0 for hard policy refusal | No | No |
| `single_specialist` | exact task, My Work, decision status, work status | 1 | 1–2 | Minimal domain slice | Yes |
| `multi_specialist` | blocker impact, dependency, milestone, release, explicit Delivery Health | 2–4 | specialists + at most one synthesis | Authorized slices only | Yes |

Budgets are ceilings, not quotas. The system must not add agents merely to reach a count.

## 4. Intent taxonomy

### 4.1 Workspace-only

- `greeting`
- `acknowledgement`
- `capability_help`
- `clarification`
- `out_of_scope`

These paths use role/membership metadata only. They must not load the Delivery tool bundle, create specialist runs or expose portfolio diagnostics.

### 4.2 Single-domain business

- `task_lookup` -> Task Intelligence
- `my_work_priority` -> Task Intelligence
- `work_health` -> Delivery Task Intelligence
- `decision_status` -> Evidence & Knowledge
- data-gated `capacity_analysis` -> Task Intelligence until Capacity activation

### 4.3 Cross-domain business

- `blocker_analysis` -> Task -> Risk + Planning
- `dependency_analysis` -> Work -> Risk -> Planning
- `milestone_health` -> Work + Planning -> Risk
- `change_impact` -> Work -> Planning -> Risk
- `release_delivery_readiness` -> Work -> Planning + Risk -> Evidence
- explicit `delivery_health` -> Work + Planning + Risk -> conditional Evidence

## 5. Routing policy

1. Match exact conversational forms before business keywords.
2. Match explicit subject and high-confidence business intent.
3. Preserve cross-domain routing when impact analysis is explicitly requested.
4. Run Delivery Health only for explicit health/overview/workspace-wide language.
5. Return a concrete clarification question for unresolved text.
6. Never use “unknown” as permission to read all workspace data.
7. Deployment gates may reduce a plan but may never add a specialist.

Future semantic routing may classify unresolved safe requests with a structured low-temperature model. Its output remains advisory: low confidence must clarify, and hard scope/tool policy remains deterministic.

## 6. Workspace-only response boundary

Workspace-only responses are policy-owned and role-aware:

- Lead capability help describes workspace/group analysis and governed control-plane actions.
- Member capability help describes own-work and authorized-group boundaries.
- Authorized greeting, acknowledgement, capability and clarification turns use exactly one Workspace LLM with the profile system prompt and input/output guardrails; they never fan out to specialists.
- Hard policy refusals remain deterministic so hostile prompt text is not forwarded to a model.
- Out-of-scope responses redirect to Product Delivery capabilities without leaking data.
- Memory stores only the user/assistant text under the existing owner/workspace/scope binding.

Telemetry must record `execution_mode=workspace_only`, intent, `specialist_count=0`, actual `llm_calls`, model/fallback metadata and `data_accessed=false`.

## 7. UI behavior

- Workspace Agent navigation is rendered only for a user with exactly one active Agent Workspace assignment; direct URL and API access remain server-gated.
- Workspace-only response: show `Workspace Agent`, the safe model/fallback trace and no Multi-agent DAG, portfolio cards or source diagnostics.
- Single specialist: show `Workspace Agent -> Specialist`, specialist name and tool summary.
- Multi specialist: show DAG participants, tool summaries and upstream-result counts.
- Explain `partial` and fallback only when a business workflow exists.
- Never expose full system prompts, tokens, credentials or raw authorization hashes.

## 8. Security and failure policy

- Workspace membership and role are resolved before every path.
- Member-supplied group selectors fail with HTTP 403 before tool/LLM invocation.
- Provider failure falls back within the selected plan; it cannot expand the plan.
- Output rejection is explicit and audited.
- A task outside Member scope returns the same not-found-in-authorized-scope result as an absent task.
- Unknown text cannot trigger broad data reads.

## 9. Quality gates

### AO-MA-01 — Conversational routing

- greetings and acknowledgements use `workspace_only`;
- capability responses differ by role;
- ambiguous text clarifies;
- obvious out-of-scope text redirects.

### AO-MA-02 — No unnecessary execution

- greeting test proves no Tool Gateway read;
- no specialist runtime call;
- no Delivery business workflow/run;
- no source, portfolio payload or data gap;
- UI shows no DAG.

### AO-MA-03 — Minimal specialist selection

- exact task and My Work use Task only;
- work status uses Work only;
- blocker impact uses Task/Risk/Planning;
- Delivery Health requires explicit language.

### AO-MA-04 — Authorization

- Lead/Member capability matrices remain correct;
- forged Member group selection is HTTP 403;
- foreign task returns zero facts;
- outsider cannot reach router/tool/LLM.

### AO-MA-05 — Cost and operability

- record selected mode, intent, specialist count and LLM calls;
- alert on budget violations by intent;
- measure clarification rate, incorrect fan-out rate, p95 latency, fallback rate and tokens per completed user goal.

## 10. Definition of done

- `hello` returns only a role-aware Workspace Agent greeting with `0` specialist and at most `1` Workspace LLM call.
- Unrecognized text asks one useful clarification question.
- No implicit Delivery Health fallback remains.
- Business routes retain LLM-backed specialists and verified A2A lineage.
- Member scope forgery returns 403 rather than 500.
- Frontend build, routing/API/RBAC regression and Docker E2E pass.

## 11. Implementation status — 2026-08-27

- Natural Vietnamese task-progress questions, including `tiến độ task của các nhóm như thế nào rồi`, route to `task_progress_summary`.
- That intent uses only `task_intelligence` and `planning_forecast`; it does not fan out to every specialist.
- PostgreSQL demo data is idempotently seeded with 3 Delivery groups, 13 assigned members, 24 messages, 15 tasks, 9 checkpoints, 3 dependencies and 3 decisions.
- Tasks capture `created_at`, `started_at` and `completed_at`; deterministic tools calculate seven-day throughput, median cycle time and median lead time without asking an LLM to invent metrics.
- The authenticated WebSocket publishes `route_selected`, `context_ready`, `specialist_dispatch_started`, `specialists_completed`, `synthesis_completed` and `failed` events, correlated by `client_request_id`.
- The UI shows the active specialist DAG, dependency relation, allowed tools and completed phase while the request is running; credentials, prompts and tokens are not exposed.
- Verified against the real Docker stack: the task-progress scenario returned `success`, no data gaps, and a two-specialist trace.
