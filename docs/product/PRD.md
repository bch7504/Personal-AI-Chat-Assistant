# PRD — Orbit Multi-Agent theo Workspace

> **Trạng thái:** Canonical v1.0
>
> **Owner:** Nhóm Multi-Agent
>
> **Cập nhật:** 2026-08-19
>
> **Release mục tiêu:** MVP nội bộ một công ty
>
> **Nguồn định hướng:** [Product Brief](BRIEF.md)
>
> **Nguồn thiết kế kỹ thuật:** [Architecture](../architecture/ARCHITECTURE.md)

## 1. Mục đích tài liệu

PRD này là nguồn chuẩn cho **Orbit Multi-Agent theo Workspace**. Nó khóa nghiệp vụ, phạm vi, yêu cầu, acceptance criteria và release gate để bốn workstream có thể phát triển song song mà không tự diễn giải khác nhau.

Khi tài liệu cũ, mockup hoặc code hiện tại khác với PRD:

- PRD quyết định **sản phẩm cần làm gì**.
- Architecture quyết định **hệ thống làm bằng cách nào**.
- Enterprise Workspace Foundation quyết định **role, membership và lifecycle**.
- Implementation Plan quyết định **ai làm, phụ thuộc nào và merge ra sao**.

## 2. Bối cảnh và cơ hội

Orbit hiện đã có chat, task, reminder, calendar, memory, Personal Agent và hai frontend User/Admin. Nền workspace mới bổ sung Company Root, Workspace phòng ban, membership, router contract và scope guard.

Cơ hội của dự án không phải tạo thêm một chatbot chung, mà biến dữ liệu công việc thành ba năng lực chuyên biệt:

1. Delivery biết tiến độ và dependency trong phòng Delivery.
2. QA biết chất lượng và release readiness trong phòng QA.
3. Executive tổng hợp bức tranh liên phòng ban từ brief có kiểm chứng.

## 3. Mô hình sản phẩm thống nhất

### 3.1 Một app là một công ty

- Mỗi deployment Orbit phục vụ đúng một công ty.
- Hệ thống tự tạo một `Workspace(type=organization, slug=company-root)` làm boundary dữ liệu.
- Admin và user không có luồng tạo “công ty”.
- Endpoint tạo organization cũ phải bị vô hiệu trong chế độ single-company.

### 3.2 “Workspace” trên UI nghĩa là gì

Trong ngôn ngữ sản phẩm, **Workspace** là phòng ban/đơn vị làm việc có một Agent gắn kèm. Trong code hiện tại, đối tượng này là `AgentWorkspace`, luôn nằm dưới Company Root.

| Thuật ngữ sản phẩm | Đối tượng code | Ví dụ |
|---|---|---|
| Company Root | `Workspace(type=organization)` | Orbit Demo Company |
| Workspace phòng ban | `AgentWorkspace` | Product Delivery, Quality Assurance |
| Workspace giám đốc | `AgentWorkspace(profile=executive)` | Executive Office |
| Thành viên công ty | `WorkspaceMembership` | User thuộc Company Root |
| Thành viên phòng ban | `AgentWorkspaceMembership` | lead/member/executive_viewer |

UI không được hiển thị Company Root như một công ty mà user có thể tạo/xóa. Admin app quản lý các Workspace con bên trong Company Root.

## 4. Mục tiêu và phi mục tiêu

### 4.1 Mục tiêu MVP

- Admin tạo, cấu hình và kiểm soát Workspace phòng ban.
- Mỗi Workspace có đúng một profile và một lead đang hoạt động.
- User chỉ khám phá và sử dụng Workspace mình được phân.
- Delivery/QA Agent trả lời read-only trong đúng nguồn đã liên kết và tạo WorkspaceBrief có provenance.
- Executive Agent tổng hợp WorkspaceBrief mà không cần quyền đọc raw chat của mọi phòng.
- Mọi side effect có preview, approval, revalidation, idempotency và audit.
- Có feature flag, eval dataset, security test và rollback path.

### 4.2 Phi mục tiêu MVP

- Multi-company SaaS và tenant onboarding.
- User hoặc lead tự tạo Workspace.
- Agent tự thêm/xóa thành viên, đổi lead hay liên kết data source.
- Agent-to-agent conversation tự do.
- Executive đọc raw chat, memory cá nhân hoặc direct message của toàn công ty.
- Autonomous action không có con người xác nhận.
- Workflow engine tổng quát cho mọi loại phòng ban.

## 5. Persona và quyền

### 5.1 Persona

| Persona | Nhu cầu | Quyền chính |
|---|---|---|
| Platform Admin | Tạo cấu trúc và kiểm soát truy cập | Admin app, provisioning, membership, source binding, audit |
| Workspace Lead | Điều hành một phòng ban | Dùng Agent trong Workspace, xem brief, xác nhận hành động được phép |
| Workspace Member | Làm việc trong một phòng ban | Dùng Agent và đọc dữ liệu thuộc scope được cấp |
| Executive Viewer | Xem bức tranh liên phòng ban | Dùng Executive Agent với aggregate scope trên WorkspaceBrief |

### 5.2 Hai lớp role

System role:

- `platform_admin`: vào Admin control plane.
- `user`: vào User app; quyền dữ liệu tiếp tục phụ thuộc membership.

Business role:

- `lead`: đúng một người/Workspace đang hoạt động.
- `member`: thành viên Delivery hoặc QA Workspace.
- `executive_viewer`: thành viên được cấp quyền Executive Workspace.

### 5.3 Quy tắc quyền

- `platform_admin` không tự động có quyền đọc dữ liệu nghiệp vụ.
- `lead` không tự động có system role Admin.
- Membership Company Root là điều kiện cần; AgentWorkspace membership là điều kiện đủ cho specialist scope.
- Executive aggregate scope chỉ phát sinh từ membership Executive Workspace.
- Client không được gửi `business_role`, `agent_profile`, allowed resource hay policy decision để tự cấp quyền.

## 6. Đối tượng và invariant

### 6.1 Đối tượng chính

- Company Root
- Agent Workspace
- Workspace Membership
- Agent Workspace Membership
- Linked Conversation/Resource
- Agent Invocation
- WorkspaceBrief
- ExecutiveBrief
- ActionProposal/Approval
- Audit Event

### 6.2 Invariant bắt buộc

1. Chỉ có một Company Root có slug `company-root`.
2. Mọi Agent Workspace thuộc Company Root hiện hành.
3. `key` của Agent Workspace là duy nhất trong Company Root.
4. Mỗi Agent Workspace có một `agent_profile` bất biến sau khi tạo trong MVP.
5. Mỗi Agent Workspace đang hoạt động có đúng một lead đang hoạt động.
6. Platform Admin không được làm lead/member nghiệp vụ bằng provisioning flow chuẩn.
7. Specialist Workspace chỉ liên kết group conversation cùng Company Root, AI enabled và đúng classification.
8. Một conversation chỉ thuộc tối đa một Agent Workspace trong MVP.
9. Executive Workspace không liên kết raw conversation.
10. ExecutiveBrief chỉ dùng WorkspaceBrief cùng Company Root, đúng schema và chưa hết hạn.
11. Thu hồi membership/consent làm mất quyền ở lần kiểm tra kế tiếp.
12. Side effect không chạy nếu proposal hết hạn, payload thay đổi hoặc quyền không còn hợp lệ.

## 7. Luồng người dùng chuẩn

### 7.1 Admin tạo Workspace phòng ban

1. Admin mở trang Workspaces.
2. UI tải Company Root do hệ thống quản lý.
3. Admin nhập name, key, profile và chọn lead từ tài khoản active.
4. Server kiểm tra Admin, Company Root, profile và lead.
5. Server bảo đảm lead là thành viên Company Root, tạo AgentWorkspace và lead membership trong một transaction.
6. Server ghi audit event.
7. UI hiển thị Workspace mới cùng profile, lead và trạng thái.

### 7.2 Admin quản lý thành viên và nguồn

1. Admin chọn Workspace.
2. Thêm member hoặc executive_viewer phù hợp profile.
3. Với Delivery/QA, Admin liên kết group conversation đúng classification.
4. Với Executive, UI không hiển thị chức năng link raw conversation.
5. Đổi lead phải hạ lead cũ thành member và duy trì đúng một lead.
6. Không thể revoke lead trước khi có lead thay thế.

### 7.3 Thành viên dùng Specialist Agent

1. User app gọi endpoint “available” để lấy Workspace từ membership server-side.
2. User chọn Workspace và gửi message, scope `workspace`, target Workspace ID.
3. Router đọc profile từ database; scope resolver kiểm tra Company Root và membership.
4. Agent chỉ dùng tool trong allowlist và resource ID đã resolve.
5. Resource guard revalidate trước mỗi lần đọc nguồn.
6. Response có source, freshness, data gap và không lộ dữ liệu ngoài Workspace.

### 7.4 Giám đốc dùng Executive Agent

1. User có membership Executive Workspace gửi request scope `aggregate`, không gửi target Workspace.
2. Router chọn Executive profile một cách deterministic.
3. Scope resolver xác nhận executive entitlement và xác định các specialist Workspace đang hoạt động.
4. Executive Agent tải WorkspaceBrief đã validate, không tải raw conversation.
5. Response chỉ rõ brief nào được dùng, brief nào thiếu/hết hạn và quyết định cần đưa ra.

### 7.5 Side effect

1. Agent tạo `ActionProposal` chứa payload, hash, expiry và idempotency key.
2. UI hiển thị preview chính xác.
3. Người có quyền approve/reject.
4. Backend revalidate actor, scope, consent, payload hash và expiry.
5. Executor chạy đúng một lần và ghi audit.

## 8. Yêu cầu chức năng

### FR-01 — Company boundary (P0)

- Hệ thống phải tạo/lấy Company Root khi backend startup.
- Admin app chỉ đọc metadata Company Root.
- Tạo organization từ Admin/User flow phải bị chặn.
- Mọi Workspace, source và brief phải thuộc Company Root.

**Acceptance:** startup lặp lại không tạo Company Root thứ hai; request tới company ID khác trả 404/403 và không rò rỉ sự tồn tại của dữ liệu.

### FR-02 — Admin Workspace provisioning (P0)

- Chỉ Platform Admin được create/list/update/suspend/archive Agent Workspace.
- Create yêu cầu `name`, `key`, `agent_profile`, `lead_email`.
- Profile chỉ nhận `product_delivery`, `quality_assurance`, `executive`.
- Create Workspace và assign lead phải atomic.
- Mọi thay đổi phải có audit event.

**Acceptance:** user thường nhận 403; duplicate key nhận 409; lead không hợp lệ không để lại Workspace mồ côi.

### FR-03 — Membership và lead (P0)

- Admin được add/revoke member và đổi lead.
- User phải active và thuộc Company Root trước khi có AgentWorkspace membership; provisioning có thể enroll tài khoản active theo quyết định rõ ràng của Admin.
- Specialist chỉ nhận `lead/member`; Executive Workspace nhận `lead/member/executive_viewer` trong baseline, UI ưu tiên `executive_viewer` cho người chỉ xem.
- Không được để Workspace active không có lead.

**Acceptance:** revoke lead hiện tại bị chặn đến khi có lead thay thế; membership revoked biến mất khỏi user discovery và mất quyền gọi Agent.

### FR-04 — User Workspace discovery (P0)

- User app chỉ có read-only endpoint liệt kê Workspace mà user có membership active.
- Không hiển thị form create/edit/member management cho user.
- Empty state phải hướng dẫn liên hệ Admin, không mời user tự tạo Workspace.

**Acceptance:** sửa ID trên client không làm xuất hiện Workspace ngoài quyền; màn hình user không có nút Create Workspace.

### FR-05 — Data source binding và consent (P0)

- Chỉ Admin liên kết/hủy liên kết source trong MVP.
- Delivery/QA chỉ nhận group conversation cùng Company Root, `ai_enabled=true` và classification khớp profile.
- Việc resolve dữ liệu phải tính `ai_policy_version` thành consent scope hash.
- Direct conversation và message của author không cho phép AI đóng góp phải bị loại trước prompt.
- Executive Workspace không nhận raw conversation.

**Acceptance:** đổi consent giữa hai tool call làm request bị dừng với reason `CONSENT_CHANGED`; source ngoài allowlist trả `RESOURCE_NOT_ALLOWED`.

### FR-06 — Invocation, router và context (P0)

- Client invocation chỉ chứa message, conversation ID tùy chọn, requested scope và target Workspace tùy chọn.
- Personal scope → Personal profile, không target.
- Workspace scope → profile đọc từ target AgentWorkspace.
- Aggregate scope → Executive profile, không target.
- Intent phải nằm trong allowlist của profile.
- Backend tạo trusted `AgentContext` gồm trace, actor, request, authorization và runtime.

**Acceptance:** profile/scope/intent mismatch bị từ chối trước model call; client chèn trường quyền thừa bị schema reject.

### FR-07 — Product Delivery Agent (P0)

- Trả lời tiến độ, milestone, blocker, dependency, ownership và decision needed.
- Chỉ dùng Delivery sources và tool allowlist.
- Phân biệt fact với inference/recommendation.
- Có thể tạo Delivery WorkspaceBrief theo contract.
- Reminder/meeting chỉ là proposal cần approval.

**Acceptance:** câu hỏi QA chuyên sâu không bị trả lời như Delivery fact; mọi fact quan trọng có source hoặc được ghi data gap.

### FR-08 — Quality Assurance Agent (P0)

- Trả lời test progress, defect/blocker, coverage gap và release readiness.
- Kết luận readiness chỉ nhận `READY`, `AT_RISK`, `NOT_READY` và phải có evidence.
- Chỉ dùng Quality sources và tool allowlist.
- Có thể tạo Quality WorkspaceBrief.
- Reminder/meeting chỉ là proposal cần approval.

**Acceptance:** không kết luận READY khi evidence thiếu; trạng thái thiếu được nêu trong data gap.

### FR-09 — WorkspaceBrief lifecycle (P0)

- Brief có schema version, producer profile, period, generated/expiry time, source references và data gaps.
- Delivery brief không chứa release readiness; Quality brief có thể chứa readiness.
- Server validate profile/type/source boundary trước khi lưu hoặc publish.
- Brief hết hạn không được Executive dùng như dữ liệu hiện hành.
- Việc regenerate phải có lineage và audit.

**Acceptance:** brief sai profile, source khác Workspace, timestamp không timezone-aware hoặc expiry không hợp lệ bị reject.

### FR-10 — Executive Agent (P0)

- Chỉ entitlement trong Executive Workspace mới gọi aggregate scope.
- Đầu vào nghiệp vụ là WorkspaceBrief đã validate.
- Output gồm facts, risks, cross-workspace dependencies, decisions, recommendations và data gaps.
- Không đọc raw chat/direct message/memory cá nhân mặc định.
- Khi không có brief hợp lệ, trả data gap thay vì suy đoán.

**Acceptance:** ExecutiveBrief không có source brief chỉ hợp lệ khi khai báo data gap; không được trùng brief ID.

### FR-11 — Tool policy và HITL (P0)

- Mỗi profile có registry gồm allowed scope, intent, prompt version và tool allowlist.
- Tool dữ liệu phải nhận trusted context và revalidate resource.
- Read-only được chạy khi policy ALLOW.
- Create/update/delete/send/invite đều cần ActionProposal và approval.
- Execute phải idempotent và chống replay.

**Acceptance:** gọi tool ngoài allowlist bị chặn; proposal hết hạn hoặc payload hash khác không chạy; double approve không tạo side effect thứ hai.

### FR-12 — Audit và observability (P0)

- Ghi trace ID cho invocation, policy, tool call, brief và action.
- Audit các thay đổi Workspace, membership, source binding, brief publication và side effect.
- Log không chứa token, secret hoặc raw personal content không cần thiết.
- Có metric allow/deny, latency, tool error, data gap, stale brief và approval outcome.

**Acceptance:** có thể lần từ ExecutiveBrief về WorkspaceBrief và SourceReference mà không cần log raw prompt.

### FR-13 — UI/UX (P0)

Admin app cần:

- Danh sách Workspace trong Company Root.
- Form create với profile và lead bắt buộc.
- Detail để đổi lead, quản lý member, status và source binding.
- Audit/feedback lỗi rõ ràng.

User app cần:

- Danh sách Workspace được phân.
- Badge profile và business role.
- Chat/brief view theo Workspace.
- Source, freshness, data gap và approval card.
- Empty/denied/loading/error/stale state.

**Acceptance:** UI không cho user tự tạo Workspace; Executive view không có raw conversation browser; denied state không tiết lộ tên Workspace ngoài quyền.

## 9. Yêu cầu phi chức năng

### Security

- Deny by default.
- Authorization trước retrieval và revalidation tại tool boundary.
- Không dùng prompt instruction thay cho access control.
- Secret/credential được mã hóa và không xuất hiện trong log.
- Critical scope test phải chạy trong CI.

### Reliability

- Transaction cho create Workspace + lead.
- Idempotency cho action và brief publication.
- Brief có expiry/freshness rõ ràng.
- Feature flag cho từng Agent và global multi-agent kill switch.

### Performance mục tiêu MVP

- Workspace discovery p95 dưới 500 ms trong môi trường staging chuẩn.
- Policy/scope resolution p95 dưới 300 ms, không tính LLM.
- Read-only Agent response p95 dưới 15 giây với dataset demo.
- Executive aggregation p95 dưới 20 giây với tối đa 20 brief hiện hành.

### Accessibility và UX

- Keyboard usable cho form, selector và approval.
- Focus/error state rõ ràng; không chỉ dùng màu để biểu đạt trạng thái.
- Ngôn ngữ UI thống nhất: Company, Workspace, Lead, Member, Agent profile.

### Maintainability

- Contract có version và backward-compatibility test.
- Profile-specific code tách khỏi router/policy dùng chung.
- Không merge feature nếu chỉ hoạt động bằng mock mà không ghi rõ trạng thái.

## 10. Dữ liệu và API boundary

### 10.1 API baseline đã có

| Mục đích | Endpoint |
|---|---|
| Company metadata | `GET /api/v1/admin/company` |
| Admin list Company Root | `GET /api/v1/admin/workspaces` |
| Admin create Workspace | `POST /api/v1/workspaces/{company_id}/agent-workspaces` |
| Admin list/update Workspace | `GET/PATCH /api/v1/workspaces/{company_id}/agent-workspaces...` |
| Admin member/source management | Các route con `/members` và `/conversations` |
| User discovery | `GET /api/v1/workspaces/{company_id}/agent-workspaces/available` |

### 10.2 API cần hoàn thiện

- Endpoint invoke Workspace Agent dùng `AgentInvocationRequest`.
- Endpoint lấy lịch sử/result theo trace/thread trong Workspace.
- Endpoint generate/list/get/publish WorkspaceBrief.
- Endpoint invoke/list ExecutiveBrief.
- Endpoint proposal approve/reject/execute có idempotency.

Tên endpoint có thể thay đổi trong Architecture/API spec, nhưng boundary quyền không được thay đổi.

## 11. Trạng thái triển khai

| Capability | Current | Target MVP |
|---|---|---|
| Single Company Root | Hoạt động | Hardening/migration coverage |
| Admin Workspace provisioning | Hoạt động baseline | UX + transaction/invariant hoàn chỉnh |
| Membership/source management | Hoạt động baseline | Policy theo profile + audit coverage |
| User discovery | Hoạt động | Workspace Agent experience |
| Contracts/registry/router/scope guard | Có code và unit test | Tích hợp vào API runtime |
| Delivery Agent | Chỉ có profile/contract/tool names | Prompt, tools, brief pipeline, UI |
| QA Agent | Chỉ có profile/contract/tool names | Prompt, tools, readiness, brief pipeline, UI |
| Executive Agent | Có entitlement/contract/tool names | Brief store, aggregate runtime, UI |
| HITL multi-agent | Có ActionProposal contract | Durable proposal/approval executor |

## 12. Metrics

### Product

- Tỷ lệ câu hỏi demo được trả lời với nguồn hợp lệ.
- Thời gian tạo weekly Delivery/QA brief so với làm thủ công.
- Tỷ lệ ExecutiveBrief chỉ ra đúng cross-workspace dependency trong golden dataset.
- Tỷ lệ approval/reject và số action bị chặn do stale/revoked permission.

### Quality và safety

- Critical data leak: 0.
- Unauthorized model/tool call: 0.
- Unsupported claim rate trên golden dataset: mục tiêu dưới 5%.
- Brief freshness/data gap coverage: 100% response executive.
- P0/P1 automated test pass: 100% trước release.

## 13. Test và acceptance scenarios

Tối thiểu phải có:

1. Admin tạo đủ ba Workspace và gán lead thành công.
2. User thường không tạo/update Workspace được.
3. Member Delivery không đọc QA source và ngược lại.
4. Người không thuộc Workspace không gọi Agent bằng ID sửa tay.
5. Revoked member mất discovery và quyền ở request tiếp theo.
6. Consent đổi giữa request và tool call bị chặn.
7. Delivery/QA brief sai source/profile/expiry bị reject.
8. Executive chỉ dùng brief hợp lệ và báo brief thiếu/hết hạn.
9. Action chưa approve, hết hạn hoặc bị replay không gây side effect.
10. Feature flag tắt profile làm request fail closed.
11. Admin không đọc business data chỉ vì có platform role.
12. UI không hiển thị create Workspace ở User app.

Golden cases và taxonomy chi tiết nằm tại [Multi-Agent Test Dataset](../testing/MULTI_AGENT_TEST_DATASET.md).

## 14. Rollout và release gate

### Feature flags

- `MULTI_AGENT_ENABLED`
- `PRODUCT_DELIVERY_AGENT_ENABLED`
- `QUALITY_ASSURANCE_AGENT_ENABLED`
- `EXECUTIVE_AGENT_ENABLED`

### Thứ tự bật

1. Internal seed environment.
2. Delivery read-only.
3. QA read-only.
4. WorkspaceBrief generation.
5. Executive read-only aggregation.
6. HITL side effects từng loại.

### Release gate

- Migration up/down hoặc rollback procedure đã kiểm chứng.
- Backend tests, frontend builds và critical security tests xanh.
- Không còn API nào tin role/profile/allowed scope từ client.
- Demo dataset có Delivery, QA, cross-workspace dependency, stale brief và denial cases.
- Audit/provenance truy vết end-to-end.
- Runbook tắt từng Agent mà không làm hỏng Personal Agent/chat hiện có.

## 15. Rủi ro và biện pháp

| Rủi ro | Biện pháp |
|---|---|
| Nhầm Company Root với Workspace phòng ban | Chuẩn hóa thuật ngữ UI và tài liệu; dùng `AgentWorkspace` trong code |
| Admin vô tình có quyền đọc mọi dữ liệu | Tách platform role khỏi business membership |
| Executive trở thành “superuser AI” | Chỉ aggregate WorkspaceBrief; không raw source mặc định |
| Model vượt scope | Filter trước prompt + resource guard tại tool boundary |
| Brief cũ gây quyết định sai | Expiry, data gap, stale badge và refuse-to-assert |
| Hai team thay contract cùng lúc | Versioned contract, fixtures và một owner integration |
| Side effect lặp | Payload hash, idempotency key và durable approval state |
| Demo mock bị hiểu là production | Bảng Current/Target và evidence gate bắt buộc |

## 16. Definition of Done

MVP chỉ được coi là hoàn thành khi:

- Ba luồng Delivery, QA, Executive chạy qua API và UI thật.
- Mọi response quan trọng có provenance/freshness/data gap.
- Cross-workspace denial, revocation và consent-change tests xanh.
- Side effect có HITL durable và idempotent.
- Admin/User UI tuân thủ đúng quyền.
- Feature flags, audit, metrics và rollback đã được diễn tập.
- Bộ tài liệu canonical và code không còn mâu thuẫn về single-company, role hay Workspace ownership.

## 17. Tài liệu liên quan

- [Architecture](../architecture/ARCHITECTURE.md)
- [Enterprise Workspace Foundation](ENTERPRISE_WORKSPACE_FOUNDATION.md)
- [Multi-Agent Implementation Plan](../implementation/MULTI_AGENT_IMPLEMENTATION_PLAN.md)
- [Multi-Agent Test Dataset](../testing/MULTI_AGENT_TEST_DATASET.md)
- [Hướng dẫn chạy local](../../README.md)
