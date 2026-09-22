# Tài liệu Orbit

Tài liệu kỹ thuật và đánh giá được giữ lại để giải thích thiết kế và tái lập kết quả của dự án cá nhân. Hướng dẫn chạy hiện hành nằm trong [`README.md`](../README.md).

Tài liệu thuyết trình và bản xuất HTML/PDF được đặt riêng tại [`../presentation/`](../presentation/README.md).

```text
docs/
├── product/          # Product brief, PRD và mô hình Workspace
├── architecture/     # Kiến trúc, system overview, RBAC và guardrail
├── implementation/   # Hồ sơ thiết kế/triển khai lịch sử
├── testing/          # Dataset, playbook, test script và metrics
└── reports/          # Kết quả đánh giá đã chạy
```

| Thứ tự | Tài liệu | Câu hỏi được trả lời |
|---|---|---|
| 1 | [Product Brief](product/BRIEF.md) | Sản phẩm là gì, giải quyết vấn đề nào và phạm vi MVP ra sao? |
| 2 | [PRD](product/PRD.md) | Nghiệp vụ, yêu cầu và acceptance criteria là gì? |
| 3 | [Architecture](architecture/ARCHITECTURE.md) | Component, data flow, authorization và current/target state được thiết kế thế nào? |
| 4 | [Enterprise Workspace Foundation](product/ENTERPRISE_WORKSPACE_FOUNDATION.md) | Company Root, Workspace, role, membership và lifecycle hoạt động ra sao? |
| 5 | [Multi-Agent Implementation Plan](implementation/MULTI_AGENT_IMPLEMENTATION_PLAN.md) | Phụ thuộc, sequencing và release gate hoạt động thế nào? |
| 6 | [Multi-Agent Test Dataset](testing/MULTI_AGENT_TEST_DATASET.md) | Golden cases, taxonomy và eval data được chuẩn hóa thế nào? |
| 7 | [Multi-Agent System Evaluation Playbook V2](testing/MULTI_AGENT_SYSTEM_EVALUATION_PLAYBOOK_V2.md) | Kiểm thử routing, specialist DAG, memory, security, fault isolation và chấm release gate thế nào? |
| 8 | [Multi-Agent Chat Test Script](testing/MULTI_AGENT_CHAT_TEST_SCRIPT.md) | Copy câu hỏi nào vào UI và kỳ vọng agent/luồng/câu trả lời ra sao? |
| 9 | [Multi-Agent Chat Robustness Test](testing/MULTI_AGENT_CHAT_ROBUSTNESS_TEST_SCRIPT.md) | Agent có còn route và trả lời đúng khi người dùng đổi cách diễn đạt, viết tắt, typo hoặc sửa ý giữa thread không? |
| 10 | [Workspace Agent Prompt & Guardrail V2](architecture/WORKSPACE_AGENT_PROMPT_GUARDRAIL_V2.md) | Policy nhiều lớp, deterministic workspace-only và mapping nguyên lý Deep Agents được triển khai ra sao? |
| 11 | [Kết quả kiểm thử Multi-Agent 2026-08-29](reports/MULTI_AGENT_EVALUATION_RESULTS_2026-08-29.md) | 26 chat case đã được cover thế nào, lỗi nào đã sửa và release gate hiện ra sao? |

## Tài liệu hỗ trợ đang dùng

- [Kịch bản kiểm thử Personal Agent](testing/PERSONAL_AGENT_END_TO_END_TEST_SCRIPT.md)
- [Product Delivery Adaptive Orchestration V3](implementation/PRODUCT_DELIVERY_ADAPTIVE_ORCHESTRATION_PLAN_V3.md)
- [Trạng thái triển khai Product Delivery](implementation/PRODUCT_DELIVERY_MULTI_AGENT_IMPLEMENTATION_STATUS.md)
- [Demo Task Governance](implementation/PRODUCT_DELIVERY_TASK_GOVERNANCE_DEMO.md)
- [Kế hoạch nâng cấp Quality Agent](implementation/QUALITY_AGENT_WORKSPACE_COMPREHENSIVE_UPGRADE_PLAN.md)
- [Ma trận RBAC Workspace Agent](architecture/WORKSPACE_AGENT_RBAC_MATRIX.md)
- [Báo cáo guardrail regression](../eval/results/guardrail_regression_report.md)

Các tệp trong `implementation/` là hồ sơ lịch sử của quá trình phát triển, không phải hướng dẫn vận hành. Dự án hiện chỉ hỗ trợ chạy local.

## Quy tắc single source of truth

- `product/BRIEF.md` khóa ý tưởng và ranh giới sản phẩm.
- `product/PRD.md` khóa hành vi và acceptance.
- `architecture/ARCHITECTURE.md` khóa giải pháp kỹ thuật và security boundary.
- `product/ENTERPRISE_WORKSPACE_FOUNDATION.md` khóa nghiệp vụ role/membership.
- `implementation/MULTI_AGENT_IMPLEMENTATION_PLAN.md` chỉ quản lý execution; không được tự thay đổi product/architecture contract.
- Mọi tài liệu phải phân biệt rõ **đã có trong code** và **mục tiêu cần triển khai**.
- Khi đổi contract, role, profile hoặc data boundary, PR phải cập nhật tài liệu canonical tương ứng cùng lúc.

## Thuật ngữ bắt buộc

- Một deployment Orbit là **một công ty**.
- `Company Root` là boundary ẩn do hệ thống tạo.
- “Workspace” trên sản phẩm là `AgentWorkspace` phòng ban nằm dưới Company Root.
- Ba Workspace Agent của MVP là `product_delivery`, `quality_assurance`, `executive`.
- Personal Agent là compatibility flow riêng, không tính là Workspace Agent thứ tư.
- Platform Admin tạo Workspace và phân lead/member; user không tự tạo Workspace.
- Executive Agent aggregate `WorkspaceBrief`, không mặc định đọc raw chat liên phòng ban.

## Tài liệu đã loại bỏ

Các giáo trình AI20K, AI log, branch report, kế hoạch lịch sử, wireframe cũ, Personal Agent spec rời rạc và các bản thiết kế trùng lặp đã được bỏ khỏi `docs/`. Chúng vẫn có thể khôi phục từ lịch sử Git nếu cần tra cứu, nhưng không còn là nguồn dùng để triển khai Multi-Agent.
