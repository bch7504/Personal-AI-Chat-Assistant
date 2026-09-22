# Bộ dữ liệu kiểm thử Multi-Agent Workspace v1

Nguồn chuẩn là `eval/datasets/multi_agent_workspace_v1.jsonl`. Bộ dữ liệu có đúng **150 case synthetic**, dùng để khóa logic cho Product Delivery Agent, Quality Assurance Agent và Executive Agent trước khi nối dữ liệu thật.

Không sửa trực tiếp JSONL. Mọi thay đổi phải đi qua generator để kết quả có thể tái lập:

```powershell
.\.venv\Scripts\python.exe scripts\generate_multi_agent_dataset.py --write
.\.venv\Scripts\python.exe scripts\generate_multi_agent_dataset.py --check
.\.venv\Scripts\python.exe scripts\validate_multi_agent_dataset.py
.\.venv\Scripts\python.exe -m pytest tests\test_multi_agent_dataset.py -q
```

## Phân bố case

| Category | Số case | Mục đích |
|---|---:|---|
| `delivery_summary` | 15 | Milestone, blocker, overdue, dependency và source |
| `quality_readiness` | 15 | Bug/test/regression và `READY/AT_RISK/NOT_READY` |
| `executive_aggregate` | 15 | Tổng hợp đúng hai WorkspaceBrief |
| `routing` | 15 | Route deterministic tới ba profile |
| `workspace_permission` | 15 | Cross-workspace/admin/profile denial |
| `prompt_injection` | 15 | Chỉ thị độc hại trong context/tool data |
| `hitl` | 15 | Proposal, approval, edit, expiry và idempotency |
| `stale_partial_brief` | 15 | Missing/stale/masked/schema mismatch |
| `membership_consent_revoke` | 15 | Revoke/suspend/consent/cache invalidation |
| `cross_workspace_dependency` | 15 | Structured dependency và raw-access denial |

## Quan hệ với acceptance v1

`user_agent_acceptance_v1.json` vẫn là regression baseline cho Personal Agent hiện tại, có seed PostgreSQL và live LLM runner. Bộ 150 case này không thay thế nó; đây là contract/eval dataset cho kiến trúc multi-agent chưa bật feature flag.

Khi Delivery/Quality/Executive vertical slice hoàn thành, bước tiếp theo là xây runner đọc JSONL này và ánh xạ từng case thành `AgentContext` thật. Trước thời điểm đó, test hiện tại kiểm tra tính tái lập, schema, source references, permission fail-closed, HITL và các invariant nghiệp vụ.

## Quy tắc versioning

- Không sửa expected result chỉ để làm test pass.
- Thay đổi schema hoặc nghĩa policy phải tăng version dataset.
- Mỗi case ID là duy nhất và ổn định.
- Dữ liệu chỉ dùng định danh synthetic; không nhập chat hoặc thông tin nhân viên thật.
- Release report phải ghi dataset version, commit, model, prompt, schema và policy version.
