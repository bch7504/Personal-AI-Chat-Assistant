# User Agent Acceptance Evaluation

- Dataset: `orbit-user-agent-acceptance` v`1.0.0`
- Provider/model: `groq` / `openai/gpt-oss-20b`
- Run at: `2026-08-14T08:41:21.750407+00:00`
- Database: isolated PostgreSQL `orbit_agent_test`
- Release gate: **NOT EVALUATED (partial run)**

## Metrics

| Metric | Result |
|---|---:|
| `case_pass_rate` | 50.0% |
| `tool_routing_accuracy` | 100.0% |
| `task_precision` | 100.0% |
| `task_recall` | 100.0% |
| `task_f1` | 100.0% |
| `task_due_accuracy` | N/A |
| `task_priority_accuracy` | N/A |
| `required_fact_check_pass_rate` | N/A |
| `required_fact_recall` | 100.0% |
| `forbidden_claim_rate` | 100.0% |
| `memory_retrieval_accuracy` | N/A |
| `memory_isolation_pass_rate` | N/A |
| `expired_memory_rejection_rate` | N/A |
| `hitl_preconfirmation_side_effect_rate` | N/A |
| `latency_mean_ms` | 9902.365 |
| `latency_p50_ms` | 5556.400 |
| `latency_p95_ms` | 14248.330 |
| `llm_judge_mean_score` | 0.889 |
| `unsupported_claim_rate` | 0.0% |
| `prompt_tokens` | 6319 |
| `completion_tokens` | 2939 |
| `total_tokens` | 9258 |
| `llm_request_count` | 5 |
| `estimated_cost_usd` | 0.001356 |
| `unpriced_tokens` | 0 |

## Cases

| Case | Capability | Status | Score | Latency | Tools |
|---|---|---:|---:|---:|---|
| `SUM-01` | conversation_summary | FAIL | 80.0% | 5556 ms | summarize_conversation |
| `TASK-03` | task_extraction | PASS | 100.0% | 14248 ms | extract_tasks |

## Failures

### SUM-01

- `forbidden_claims`: actual `['release ngay hôm nay']`, expected `[]`

Response:

```text
Nhóm đang chuẩn bị phát hành NovaCRM v1.0 vào thứ Sáu tuần sau với phạm vi gồm đăng nhập, nhập khách hàng qua CSV và bảng điều khiển doanh thu, nhưng chưa bao gồm tính năng phân quyền nâng cao. API import CSV đã hoàn thành, nhưng việc di chuyển dữ liệu sang staging bị treo vì email trùng, Lan Phương dự định sửa lỗi trước 16:00 ngày mai. Dashboard đã đạt độ đáp ứng 80% và cần xác nhận contract trường revenue_today trước 11:00 hôm nay, trong khi Smoke test chỉ còn ba lỗi liên quan tới Safari, timezone và thông báo trùng. Quyết định freeze schema vào 15:00 thứ Tư, Lan chịu trách nhiệm migration, Huy hoàn thiện responsive, và Mai thực hiện regression sau khi deploy staging. Ticket cấu hình Redis đã được đóng, và mặc dù Thu Mai đề nghị bỏ qua lỗi QA để release ngay hôm nay, nhóm vẫn giữ Go/no-go vào 16:30 thứ Năm, dời release nếu migration chưa ổn và không bỏ qua ba lỗi QA.
```

## Interpretation limits

- Task, routing, isolation, expiry and HITL metrics are deterministic.
- Free-form summary quality uses lexical checks plus an optional LLM judge; review failures manually.
- User satisfaction and production drift require repeated human evaluation and are not inferred from this run.
