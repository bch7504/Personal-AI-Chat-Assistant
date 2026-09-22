# Quality Assurance Agent Workspace — Comprehensive Upgrade Plan

> **Ngày baseline:** 2026-08-25  
> **Phạm vi:** nâng Quality Assurance (QA) từ deterministic vertical slice thành Workspace Agent có mức hoàn thiện
> tương đương Product Delivery, đồng thời khóa nền handoff Delivery ↔ QA.  
> **Nguyên tắc trạng thái:** dataset/fixture/registry name không được tính là capability đã triển khai.

## 0. Trạng thái triển khai sau upgrade 2026-08-25

Phần nền sử dụng được đã được triển khai trong nhánh hiện tại; bảng dưới đây là trạng thái code thật, không phải
capability dự kiến:

| Hạng mục | Trạng thái | Bằng chứng chính |
|---|---|---|
| QA readiness fail-closed | `implemented` | Pending test => `AT_RISK`; critical/required failure => `NOT_READY`; exact readiness output validation |
| QA Core tools | `implemented` | 10 read capabilities: work item, test status, messages, people, brief, defect register, execution summary, gate evidence, traceability gap, release handoff |
| QA LangGraph + system prompt | `implemented` | Profile-owned input/planner/snapshot/output graph; model chỉ thấy authorized snapshot |
| Hard guardrails | `implemented` | Injection/secret output block, source requirement, exact readiness preservation, bounded recursion/runtime |
| Workspace Agent Memory | `implemented` | Durable Delivery/QA thread, 12-message context, 30-day TTL, owner/workspace/profile/scope-hash binding |
| Unified router | `implemented-foundation` | `POST /api/v1/workspaces/{id}/agent-router/invoke`; profile lấy từ server DB và chạy lại policy pipeline |
| Delivery ↔ QA handoff | `implemented-foundation` | Durable `ReleaseCandidate`, Lead-only transitions, row version, audit, QA gate blocks approval, structured status visible to Delivery |
| QA UI parity | `implemented` | Chat transcript, LLM answer, evidence/readiness cards, prompt suggestions và server thread resume |
| Migration/regression | `passed` | Alembic 21 upgrade/downgrade/upgrade; Ruff; frontend build; 451 passed, 1 skipped |

Các hạng mục production nâng cao vẫn được giữ trong roadmap, không báo cáo nhầm là đã hoàn tất: normalized riêng các bảng
Defect/TestCase/TestRun/Policy/Waiver, immutable `QualityBrief` publication/event queue, HITL reminder/meeting/waiver,
browser E2E, live-LLM/load/soak và staging canary. Chúng không chặn vertical slice hiện tại nhưng là release gate trước
khi bật rộng ngoài canary..

## 1. Kết luận baseline

QA hiện **chạy được** cho deterministic release brief, Lead/Member scope, source-bound work item, API/UI và runtime
isolation. QA hiện **chưa ngang Product Delivery agentic form** vì chưa có QA LangGraph, chưa gọi LLM, system prompt
chưa đi vào execution path, chưa có profile-owned input/output guardrail nodes và chưa có live QA eval harness.

Các blocker ghi nhận ở baseline và trạng thái sau triển khai:

1. Pending test từng có thể cho `READY`: **đã sửa**, hiện trả `AT_RISK`.
2. Bug và test execution còn dùng compatibility enum chung: **đã thêm transition matrix**, normalized entity vẫn thuộc roadmap.
3. Status update: **đã có transition policy**; evidence/waiver approval đầy đủ vẫn thuộc roadmap.
4. `release_target` compatibility string: **đã có thêm durable `ReleaseCandidate`** làm typed Delivery–QA handoff.
5. Quality brief mới là candidate trong response, chưa có durable publish/store/lineage.
6. Đã có domain/tool/graph/runtime/memory/router/handoff/migration tests; live LLM/load/browser E2E vẫn thuộc roadmap.
7. `quality_brief_v1.json` **đã có provenance source** và strict contract từ chối factual brief không nguồn.

## 2. Mục tiêu và non-goals

### 2.1 Mục tiêu

- QA có cùng composition form với Delivery: profile → runner → scoped tools → authorized snapshot → LangGraph →
  output guardrail → runtime response.
- Readiness luôn do deterministic policy engine quyết định; LLM chỉ giải thích facts/risks/recommendations.
- Bug, test case, test run, release check và waiver có lifecycle đúng nghiệp vụ.
- Lead/Member/Executive/Delivery consumer có capability rõ ràng và fail closed.
- Mọi fact có source; mọi brief có release/build identity, freshness, policy version và lineage.
- QA runtime chết không làm Delivery/Core/Personal chết; Delivery chỉ thấy Quality gate unavailable/stale.
- Delivery ↔ QA giao tiếp qua typed contract do Core validate/store, không gọi raw tool/runtime của nhau.
- Có executable QA harness cho domain, graph, security, API, live LLM, browser và fault isolation.

### 2.2 Không làm trong upgrade này

- Không xây Jira/TestRail clone đầy đủ.
- Không cho LLM tự approve release, tự waive gate hoặc tự thay đổi bug/test state.
- Không cho Delivery đọc raw QA conversation và ngược lại.
- Không cho Executive đọc raw specialist data.
- Không triển khai cell/Redis/distributed queue trước khi local dedicated-runtime gates xanh.

## 3. Inventory QA hiện tại

### 3.1 Capability đã có implementation thật

| Capability | Trạng thái | Implementation | Ghi chú |
|---|---|---|---|
| Resolve QA profile/context | `implemented` | `quality_assurance_runner.py` | Server-owned profile/scope |
| Lead/Member read scope | `implemented` | `QualityReadScope` + scope resolver | Release/group/member scoped |
| Query QA work items | `implemented` | `quality_work_items.py` + repository | `ToolResult`, scope và resource revalidation |
| Deterministic readiness | `implemented` | `evaluate_release_readiness` | Pending test fail-closed thành `AT_RISK` |
| Build Quality brief | `implemented` | `quality_brief.py` | Source-backed, 15-minute expiry |
| Capability/read brief API | `implemented` | `quality_routes.py` | Runtime failure trả partial |
| Create work item | `implemented-human-API` | `POST .../quality/work-items` | Lead-only; không phải agent tool |
| Update work-item status | `implemented-human-API` | `PATCH .../status` | Có state transition policy; model không tự mutation |
| QA runtime adapter/container | `implemented` | runtime adapter + Compose service | Embedded/remote; target pin |
| QA LangGraph | `implemented` | `workspace_quality_graph.py` | Required snapshot, citation và exact readiness validation |
| QA memory/router | `implemented` | `workspace_agent_memory_service.py` + gateway | Durable bounded thread; unified server-owned routing |
| QA UI | `implemented` | `QualityAgentPage.jsx` | Chat/evidence/readiness/handoff và server thread resume |

### 3.2 Tool registry hiện tại

Registry hiện cho phép các read capability sau. Core gọi chúng để tạo authorized snapshot; model runtime chỉ được bind
`get_quality_snapshot`, không được query database trực tiếp:

| Tool name | Có code thật? | Model đang gọi? | Đánh giá |
|---|:---:|:---:|---|
| `get_quality_work_items` | Có | Qua snapshot | QA items theo release/group/member scope |
| `get_release_test_status` | Có | Qua snapshot | Deterministic readiness |
| `search_quality_messages` | Có | Qua snapshot | Bounded consented evidence search |
| `get_quality_people` | Có | Qua snapshot | Owner resolver tối thiểu, không trả email |
| `build_quality_brief` | Có | Qua snapshot | Source-backed deterministic brief |
| `get_defect_register` | Có | Qua snapshot | Defect register và severity aggregation |
| `get_test_execution_summary` | Có | Qua snapshot | Progress/status aggregation |
| `get_release_gate_evidence` | Có | Qua snapshot | Required checks và reason codes |
| `get_requirement_traceability` | Có | Qua snapshot | Fail-explicit data gap khi chưa có requirement IDs |
| `get_release_candidate` | Có | Qua snapshot | Structured Delivery handoff, không raw Delivery data |

### 3.3 Mutation/HITL tool còn trong roadmap

| Tool name | Trạng thái |
|---|---|
| `propose_quality_reminder` | `not_started` |
| `propose_quality_meeting` | `not_started` |
| `propose_bug_assignment` | `not_started` |
| `propose_quality_waiver` | `not_started` |

### 3.4 Action chỉ xuất hiện trong dataset, chưa là capability

Các expected action sau là fixture expectation, không có registry/tool/executor thật:

- `preview_quality_meeting`
- `preview_quality_reminder`
- `preview_bug_assignment`
- `preview_bug_update`
- `preview_reapproval`
- `ignore_injection_and_build_brief`

Không được demo hoặc báo cáo các action này là đã hoạt động.

### 3.5 Harness hiện tại

| Harness/artifact | Hiện trạng | Giá trị chứng minh |
|---|---|---|
| QA executable suites | Đã có | Domain, tools, graph, API, runtime, memory, router, handoff và migration |
| `quality_brief_v1.json` | Source-backed fixture | Chứng minh strict serialization/provenance |
| `multi_agent_workspace_v1.jsonl` | 150 cases/10 category | Có 33 case target QA profile |
| Dataset generator/validator | Đạt | Chỉ chứng minh dataset current/well-formed |
| `test_multi_agent_dataset.py` | 6 structural tests | Không chạy QA implementation |
| QA graph fake-LLM harness | Đã có | Tool bắt buộc, injection, citation, readiness không override |
| QA live API evaluator | Không có | Chưa chấm policy/source/readiness thực tế |
| Browser E2E | Không có | Chưa chứng minh UI role/error/freshness |
| Kill-container/load/soak | Không có | Chưa đủ production isolation/SLO |

### 3.6 Agent Memory hiện tại

| Profile | Short-term thread/checkpoint | Long-term memory | Kết luận |
|---|---|---|---|
| Product Delivery | Có `WorkspaceAgentThread` + bounded message history | Không tự ghi business facts vào Personal Memory | Thread bind user/workspace/profile/scope hash, TTL 30 ngày |
| Quality Assurance | Có cùng durable thread contract nhưng namespace/profile tách biệt | Không tự ghi business facts vào Personal Memory | Resume sai owner/workspace/profile/revoked scope fail closed |

Personal Agent có `AgentThread` + LangGraph checkpointer và private Memory, nhưng Delivery/QA không được reuse Personal
thread hoặc Personal Memory. `WorkspaceAgentThread` hiện bind
`organization_workspace_id + agent_workspace_id + profile + actor_user_id + public_thread_id + authorization_scope_hash`,
TTL, ownership và revoke handling. Workspace
thread chỉ giữ tối đa 12 message user/assistant, không giữ tool payload hay authorization snapshot; durable business facts vẫn ở domain tables, không
được ghi thành conversational memory tự do.

### 3.7 Router hiện tại

- Delivery và QA endpoint đều gọi `route_agent_request` rồi `build_agent_context`; profile được resolve từ server-owned
  `AgentWorkspace`, không tin client.
- Cả hai router đã được mount trong `src/main.py` qua endpoint profile-specific.
- Đã có unified public `POST /api/v1/workspaces/{workspace_id}/agent-router/invoke`; gateway lấy profile từ DB rồi
  dispatch qua toàn bộ policy pipeline của endpoint chuyên biệt.
- Runtime URL/mode hiện cấu hình theo profile/environment; chưa route per Workspace record, canary/version/status.

Do đó trạng thái chính xác là **đã có unified Agent Gateway foundation; chưa có runtime registry/canary per Workspace**.

## 4. Target architecture

```text
Public QA API
  → feature/profile router
  → AgentContext + Lead/Member capability
  → workspace/resource/consent revalidation
  → QA read-only executor
      → get_release_candidate_reference
      → get_quality_gate_policy
      → get_quality_work_items
      → get_quality_test_runs
      → search_quality_messages
      → get_quality_people
  → deterministic readiness engine
  → validated Quality snapshot + QualityBrief candidate
  → signed runtime request
  → QA LangGraph
      → input_guardrail
      → planner
      → get_quality_snapshot (only model-visible data tool)
      → require_snapshot_and_citations
      → output_guardrail
  → runtime response + sources + usage
  → audit/metrics
```

Core giữ database credential, authorization và actual repository tools. QA runtime chỉ nhận compact signed snapshot;
không nhận JWT, DB credential hoặc raw capability. Đây là cùng boundary đã chứng minh ở Delivery.

## 5. Domain model phải khóa trước LangGraph

### 5.1 Shared ReleaseCandidate — Delivery sở hữu

```text
ReleaseCandidate
- id
- organization_workspace_id
- delivery_agent_workspace_id
- delivery_milestone_id
- release_key (canonical, case-normalized)
- version/build_number/commit_sha
- environment
- planned_release_at
- status: draft | qa_requested | qa_in_progress | approved | rejected | released | cancelled
- quality_policy_version
- row_version
- created_by / created_at / updated_at
```

QA chỉ tham chiếu `release_candidate_id`; không sửa milestone/deadline/status Delivery ngoài một typed proposal.

### 5.2 QA entities tối thiểu

```text
QualityDefect
- id, release_candidate_id, source_conversation_id
- severity: low | medium | high | critical
- status: open | triaged | in_progress | fixed | verified | closed | reopened | waived
- owner_id, evidence_ids, waiver_id?, row_version

QualityTestCase
- id, release_candidate_id, suite, title
- required, owner_id, source_conversation_id

QualityTestRun
- id, test_case_id, release_candidate_id, build_number, environment
- status: planned | running | passed | failed | blocked | skipped
- started_at, completed_at, evidence_ids

QualityReleaseCheck
- id, release_candidate_id, policy_key, required
- status: pending | passed | failed | blocked | waived
- evidence_ids, waiver_id?

QualityGatePolicy
- id/version
- blocking severities
- required suites/checks
- minimum coverage
- waiver roles/expiry
```

Migration phải additive. Dữ liệu `Task` QA hiện tại được giữ làm compatibility bridge và backfill có kiểm soát;
không tự suy diễn release/build hoặc quyền rộng.

### 5.3 Transition rules

- Bug không được nhận `passed/failed/testing`.
- Test run không được nhận `fixed/closed`.
- `fixed → verified/closed` cần evidence hoặc verifier.
- `failed/blocked → passed` cần một TestRun/evidence mới, không sửa lịch sử cũ.
- `waived` cần ActionProposal/approval, reason, approver, expiry và policy version.
- Mọi mutation revalidate actor, workspace, release, resource, current row version và transition.

## 6. Readiness policy v2

Thứ tự precedence bắt buộc:

1. `NOT_READY` khi có active critical defect, required check failed/blocked, required test failed/blocked, hoặc policy
   hard gate không đạt.
2. `AT_RISK` khi có high/medium/low active defect, required check pending, required/selected test planned/running,
   coverage dưới threshold, stale/missing evidence, inconsistent build/environment hoặc data gap.
3. `READY` chỉ khi mọi required check/test pass cho đúng release candidate + build + environment, không active
   blocking defect, coverage đạt policy và không có data gap.

Output phải chứa `policy_version`, `evaluated_release_candidate_version`, reason codes và source IDs. LLM không
được thay đổi readiness hoặc reason codes.

## 7. Tool catalog đích

### 7.1 Read-only Core tools

| Tool | Trách nhiệm | Ưu tiên |
|---|---|---|
| `get_release_candidate_reference` | Đọc structured release/build/milestone do Delivery publish | P0 |
| `get_quality_gate_policy` | Đọc gate policy version hiện hành | P0 |
| `get_quality_work_items` | Compatibility query cho defect/test/check hiện tại | P0 |
| `get_quality_test_runs` | Test progress theo release/build/environment | P0 |
| `search_quality_messages` | Bằng chứng từ linked, consented QA groups | P1 |
| `get_quality_people` | Resolve owner/verifier tối thiểu, không lộ PII dư thừa | P1 |
| `build_quality_brief` | Chạy readiness v2 và tạo brief candidate | P0 |

Mọi read tool nhận `QualityReadScope`, revalidate từng resource, trả `ToolResult`, không trả ORM/raw exception.

### 7.2 Model-visible runtime tool

Chỉ bind `get_quality_snapshot` trong QA LangGraph. Tool là closure trên snapshot đã authorize; nó không query DB và
wrap toàn bộ payload như untrusted evidence. Điều này giảm tool injection và giữ runtime isolation.

### 7.3 Mutation/HITL proposals

| Tool | Kết quả trước approval | Executor sau approval |
|---|---|---|
| `propose_quality_reminder` | `ActionProposal` | Shared reminder executor |
| `propose_quality_meeting` | `ActionProposal` | Shared calendar executor |
| `propose_bug_assignment` | `ActionProposal` | QA domain executor |
| `propose_bug_transition` | `ActionProposal` | QA transition executor |
| `propose_quality_waiver` | `ActionProposal` | Lead/release-authority approval executor |

Model không gọi executor trực tiếp. Proposal có payload hash, TTL, idempotency key và revalidation khi approve.

## 8. Role/capability matrix

| Actor | Raw QA scope | Readiness | Mutation | Cross-workspace |
|---|---|---|---|---|
| QA Lead | Linked QA groups toàn Workspace | Workspace/group | Create; transition theo policy; propose waiver | Đọc structured ReleaseCandidate |
| QA Member | Group đang tham gia + item của mình | My Work | Transition assigned item theo policy | Không đọc Delivery raw data |
| Delivery Lead | Không raw QA | Đọc published QualityBrief của release mình quản lý | Không sửa QA; có thể request reassessment | Publish ReleaseCandidate |
| Executive viewer | Không raw specialist data | Đọc fresh published briefs | Không mutation specialist | Aggregate brief only |
| Platform Admin | Runtime/health metadata | Không mặc định có tenant facts | Provision/suspend runtime | Cần support grant riêng nếu đọc data |

## 9. QA LangGraph và guardrails

Tạo profile-owned modules:

```text
src/agents/profiles/workspace_quality_state.py
src/agents/profiles/workspace_quality_guardrails.py
src/agents/profiles/workspace_quality_graph.py
src/agents/profiles/quality_assurance_executor.py
```

Graph:

```text
input_guardrail
  ├─ blocked → END
  └─ planner
       ├─ get_quality_snapshot → planner
       └─ require_snapshot
            → deterministic_output_validation
            → output_guardrail
            → END
```

Hard rules:

- Prompt injection/secret extraction bị chặn trước LLM.
- Snapshot text được sanitize/wrap; content không thể cấp quyền hoặc đổi policy.
- Planner bắt buộc gọi snapshot đúng một lần trước factual answer.
- Fact quan trọng phải trích source; không source thì safe response/data gap.
- Output không được đổi readiness/reason/policy version.
- Không productivity scoring, sentiment-based performance inference hoặc PII dư thừa.
- Recursion/tool/token/timeout budget riêng QA; usage được log theo Workspace.

## 10. UI/API parity với Product Delivery

QA dùng shared Workspace Agent shell nhưng giữ profile-owned content:

- Workspace selector, role card, group selector và release selector.
- Chat transcript + prompt suggestions theo Lead/Member.
- Cards: readiness, required checks, test progress, defect severity, coverage, build/environment.
- Evidence drawer có source/freshness/deep link.
- States: initializing, feature-disabled, denied, empty, partial, stale, runtime degraded, conflict, error.
- Work-item mutation UI hiển thị allowed transitions từ server, không hard-code role/policy ở client.
- Không lưu sensitive transcript lâu dài vào `localStorage`; dùng server-side thread hoặc session-only state theo policy.

Public API giữ profile endpoint hiện tại trong giai đoạn chuyển tiếp. API mới phải additive và không để frontend biết
runtime endpoint.

## 11. Delivery ↔ QA handoff foundation

Không direct agent-to-agent call. Luồng canonical:

```text
Delivery Lead/API
  → publish ReleaseCandidate
  → Core validates + stores + emits QualityAssessmentRequested
  → QA builds assessment from its own sources
  → Core validates + publishes immutable QualityBrief
  → Delivery reads latest compatible QualityBrief summary
```

Invariants:

- Correlation bằng `organization_workspace_id + release_candidate_id + candidate_version`.
- QA brief phải khớp build/environment/policy version; mismatch → `AT_RISK/data_gap`.
- Delivery chỉ nhận brief, không raw QA resource IDs nếu actor không có QA entitlement.
- QA chỉ nhận ReleaseCandidate structured reference, không raw Delivery chat.
- Brief immutable, versioned, expiring, content-hashed, có `supersedes_id`.
- Event/retry read-only dùng idempotency key; không synchronous circular call.
- QA down → Delivery hiển thị gate unavailable/stale, không coi là READY và không chết theo.

## 12. Executable QA harness target

### 12.1 Dataset

- Tạo `eval/datasets/quality_agent_v2.jsonl` hoặc version 2 của multi-agent dataset với schema riêng.
- Ít nhất 120 QA cases: readiness matrix, transitions, role/scope, source, injection, freshness, release mismatch,
  HITL, runtime failure và Delivery handoff.
- Generator deterministic; `--check` phải phát hiện fixture drift.
- Quality brief golden fixtures phải có source-backed facts hoặc explicit data gap; không chấp nhận factual fixture
  không nguồn.

### 12.2 Deterministic scorers

- Exact readiness/reason/policy version.
- Required-source recall và forbidden-source leakage.
- Correct tool sequence (`get_quality_snapshot` before factual output).
- Role/policy decision exact match.
- State transition and HITL correctness.
- Release/build/environment identity match.
- No fabricated fact/source.

LLM judge chỉ chấm narrative clarity/grounding; không chấm hoặc override authorization/readiness.

### 12.3 Test suites

```text
tests/test_agents/test_quality_domain.py
tests/test_agents/test_quality_scope.py
tests/test_agents/test_quality_tools.py
tests/test_agents/test_quality_brief.py
tests/test_agents/test_quality_executor.py
tests/test_agents/test_workspace_quality_graph.py
tests/test_agents/test_quality_api.py
tests/test_agents/test_quality_delivery_handoff.py
tests/test_agents/test_quality_runtime_isolation.py
tests/test_agents/test_workspace_agent_threads.py
tests/test_agents/test_workspace_invocation_gateway.py
tests/e2e/test_quality_workspace.py
scripts/eval_quality_agent.py
```

Required negative/fault cases:

- Guessed Workspace/group/release ID.
- Member reads another member's item.
- Consent/membership revoke between context and query.
- Prompt/tool-output injection.
- Stale brief and release/build mismatch.
- Critical bug, pending test, missing required check, coverage gap.
- Invalid state transition and waiver replay.
- Runtime target/profile/version/signature mismatch.
- Kill QA runtime while Delivery/Core remain available.
- QA saturation while Delivery latency/health remain within gate.

## 13. Implementation phases và PR map

### Q0 — Freeze baseline và failing tests (0.5–1 ngày)

- Ghi ADR domain/status/readiness v2.
- Thêm regression test chứng minh pending test hiện cho READY sai.
- Freeze current API/fixture compatibility.

**Gate:** test mới fail đúng nguyên nhân; không sửa expected để che bug.

### Q1 — Domain model + migration (1.5–2 ngày)

- Add ReleaseCandidate reference, defect/test/test-run/check/policy entities hoặc typed tables tối thiểu.
- Add transition/version/evidence constraints và compatibility adapter từ Task QA.

**Gate:** fresh upgrade, upgrade existing data, idempotent upgrade, downgrade rehearsal; không backfill quyền rộng.

### Q2 — Readiness v2 + strict contracts (1 ngày)

- Implement state-specific enums, transition matrix và readiness precedence.
- Add policy/release/build identity vào assessment/brief.

**Gate:** exhaustive decision table; `READY + pending/stale/gap/mismatch` bằng 0.

### Q3 — Scoped repositories + Core tools (1.5 ngày)

- Implement P0 read tools và `QualityReadOnlyExecutor`.
- Revalidate workspace/resource/consent trước mỗi read.

**Gate:** cross-workspace leakage 0; every returned fact source-backed; tool error normalized.

### Q4 — QA LangGraph + LLM runtime (1.5 ngày)

- Add QA state, graph, input/output guardrails, required snapshot/citation node.
- Use existing signed runtime contract and separate QA container.

**Gate:** fake LLM tool-call tests, injection never reaches planner, skipped tool/citation rejected, readiness unchanged.

### Q4A — Workspace Agent Thread/Memory boundary (1–1.5 ngày)

- Tạo Workspace-owned thread metadata và checkpointer namespace cho cả Delivery/QA.
- Bỏ sensitive Delivery transcript khỏi durable `localStorage`; UI dùng public thread ID do server quản lý.
- Revalidate membership/resource/consent trên mỗi resume; revoke/expiry fail closed.
- Không tự động đưa Workspace output vào Personal Memory và không dùng Personal checkpointer pool làm shared failure
  domain trong production remote mode.

**Gate:** thread IDOR 0; Delivery thread không resume trong QA/Workspace khác; revoke/expiry fail closed; kill một
runtime không làm checkpoint/memory của runtime kia lỗi.

### Q5 — Unified routing foundation + API/UI parity (1.5–2 ngày)

- Wire compact snapshot to runtime; usage/audit/degraded behavior.
- Thêm unified invocation schema/endpoint gọi cùng router/context/executor nhưng giữ endpoint cũ tương thích.
- Chuẩn bị runtime registry interface theo `agent_workspace_id`; frontend không biết runtime URL.
- Upgrade QA chat/cards/evidence/freshness/role UX.

**Gate:** route/profile/scope mismatch fail trước retrieval; Lead/Member browser scenarios; runtime failure retains
deterministic view; no client-side authorization.

### Q6 — HITL proposals (1 ngày)

- Implement reminder/meeting/assignment/transition/waiver proposals and shared executor integration.

**Gate:** no side effect before approval; payload tamper/replay/expired/revoked actor fail closed.

### Q7 — Live QA harness + security/fault suite (1.5 ngày)

- Build executable evaluator/scorers and QA v2 dataset.
- Run embedded/remote parity, container-kill and bounded-load tests.

**Gate:** policy/readiness/source exactness 100% for deterministic cases; unauthorized leakage 0.

### Q8 — Delivery ↔ QA handoff (1.5–2 ngày)

- Add ReleaseCandidate publication, QualityAssessmentRequested and durable QualityBrief publication.
- Add Delivery read model/card for current Quality gate.

**Gate:** no raw cross-workspace access; stale/missing/mismatch fail closed; either runtime can fail independently.

### Q9 — Staging rollout (1 ngày + soak window)

- Feature flags per target Workspace, canary one QA Workspace, health/usage/latency dashboards and rollback.

**Gate:** staging E2E/load/fault/runbook rehearsal; no known P0/P1; rollback without restarting other runtime.

## 14. Definition of Done

Không gọi QA upgrade hoàn thành nếu thiếu một trong các điều kiện:

- Domain/state/readiness v2 được business owner phê duyệt và exhaustive tests xanh.
- QA graph thật chạy system prompt, model-visible snapshot tool và profile-owned guardrails.
- Tools registry khớp 100% implementation/executor; không còn dataset-only capability bị báo là available.
- Lead/Member/Delivery/Executive boundaries có negative tests.
- QualityBrief durable, versioned, source-backed, fresh và release/build matched.
- Live QA evaluator chạy implementation thật; structural dataset validation không được dùng thay eval.
- Embedded/remote contract parity, kill-container và target-mismatch gates xanh.
- Frontend build/browser E2E xanh cho denied/empty/partial/stale/degraded/error.
- Ruff, migration tests, relevant regression và `git diff --check` xanh.
- Feature flag vẫn tắt ngoài canary cho đến khi không còn P0/P1.

## 15. Lệnh kiểm tra chuẩn sau khi các harness được tạo

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_agents\test_quality_domain.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_agents\test_quality_scope.py tests\test_agents\test_quality_tools.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_agents\test_workspace_quality_graph.py tests\test_agents\test_quality_executor.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_agents\test_quality_api.py tests\test_agents\test_quality_delivery_handoff.py -q
.\.venv\Scripts\python.exe scripts\generate_quality_agent_dataset.py --check
.\.venv\Scripts\python.exe scripts\validate_quality_agent_dataset.py
.\.venv\Scripts\python.exe scripts\eval_quality_agent.py --mode embedded
.\.venv\Scripts\python.exe -m ruff check src tests scripts
docker compose config --quiet
npm --prefix Frontend/user run build
git diff --check
```

## 16. Thứ tự bắt đầu đề xuất

Không bắt đầu bằng prompt/UI. Bắt đầu theo thứ tự:

```text
Q0 failing business tests
→ Q1 domain/migration
→ Q2 readiness v2
→ Q3 tools/executor
→ Q4 LangGraph/LLM/guardrails
→ Q5 UI
→ Q6 HITL
→ Q7 live harness
→ Q8 Delivery handoff
→ Q9 canary
```

Owner QA chịu trách nhiệm profile/domain/tools/UI/harness. Shared Core owner review migration, scope, runtime contract,
brief publication và HITL executor. Delivery owner review ReleaseCandidate/QualityBrief compatibility; security reviewer
phê duyệt cross-workspace denial và fault-isolation gates.

## 17. Trạng thái triển khai control plane v2 — 2026-08-26

- Domain tables, migration `20260826_24`, scoped CRUD/OCC và policy-versioned readiness đã triển khai.
- QA approval đã nối vào normalized readiness; Task bridge chỉ là compatibility fallback.
- QA có 14 read capabilities trong registry/executor, gồm control plane, policy, evidence và waiver catalog.
- UI QA đã có form vận hành requirement/test case/evidence/test run/defect/policy, evidence verification và release decision; waiver API có sẵn nhưng UI chuyên sâu/dual approval vẫn cần business sign-off.
- Delivery ↔ QA dùng `ReleaseCandidate` + transactional outbox; runtime không gọi trực tiếp nhau.
- Durable HITL đã chạy cho bounded internal transitions. Reminder/meeting/external calendar và immutable published `QualityBrief` event vẫn là phase sau, không được coi là đã hoàn thành.
- Local integration/migration/build gates đã có; live-model eval, browser E2E, staging soak, canary và fault rehearsal vẫn bắt buộc trước GA.
