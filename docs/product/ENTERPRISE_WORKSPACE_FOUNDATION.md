# Nền móng Workspace cho ứng dụng nội bộ một công ty

> Trạng thái: **Canonical v2 — quyết định single-company ngày 2026-08-19**
> Phạm vi: Company Root, Workspace phòng ban, Executive Workspace, membership, lead và agent scope
> Mục tiêu: tạo nền an toàn để triển khai Product Delivery, Quality Assurance và Executive Agent

## 1. Quyết định nghiệp vụ

Ứng dụng này chính là hệ thống nội bộ của **một công ty**. Người dùng không tạo công ty,
không chọn tenant và không chuyển qua lại giữa nhiều tổ chức.

```text
Company Root (một bản ghi nội bộ, UI không cho tạo/xóa)
├── Product Delivery Workspace
│   ├── Trưởng phòng + thành viên
│   └── Product Delivery Agent
├── Quality Assurance Workspace
│   ├── Trưởng phòng + thành viên
│   └── Quality Assurance Agent
└── Executive Workspace
    ├── Giám đốc + người được ủy quyền
    └── Executive Agent
        └── đọc validated brief/aggregate từ các Workspace phòng ban
```

Luồng quản trị chuẩn:

1. Company Root được hệ thống tạo một lần với slug cố định `company-root`.
2. Platform Admin tạo Workspace, chọn supporting agent và bổ nhiệm trưởng Workspace.
3. Platform Admin phân member vào từng Workspace.
4. Lead/member chỉ nhìn thấy và sử dụng Workspace được phân.
5. Admin tạo Executive Workspace và chọn giám đốc làm lead.
6. Executive Agent tổng hợp dữ liệu đã kiểm soát từ các Workspace phòng ban active.

## 2. Mô hình đối tượng

| Đối tượng | Ý nghĩa trên sản phẩm | Cách tạo |
|---|---|---|
| Company Root | Biên dữ liệu duy nhất của công ty; lưu nội bộ bằng `Workspace(type=organization, slug=company-root)` | System tạo lazy/idempotent |
| Personal Workspace | Dữ liệu cá nhân của một account | System tạo khi đăng ký |
| Department Workspace | Phòng/vùng nghiệp vụ có một agent hỗ trợ | Platform Admin |
| Executive Workspace | Không gian làm việc của giám đốc có Executive Agent | Platform Admin |

Trong schema hiện tại, Department Workspace và Executive Workspace cùng dùng bảng
`agent_workspaces`. Tên `organization_workspace_id` được giữ để tương thích migration nhưng luôn
trỏ về Company Root duy nhất.

Mỗi Workspace có đúng một `agent_profile`:

- `product_delivery`
- `quality_assurance`
- `executive`

## 3. Role và cách phân role

Role được tách theo phạm vi; không gắn một role toàn năng vào account.

### 3.1 System role

| Role | Quyền |
|---|---|
| `platform_admin` | Quản lý account, tạo/suspend Workspace, gắn agent, chọn lead/member; không tự đọc raw business data |
| `user` | Chỉ sử dụng các Personal/Business Workspace được phân |

### 3.2 Workspace business role

| Role | Quyền |
|---|---|
| `lead` | Trưởng phòng hoặc giám đốc của đúng Workspace; dùng agent và điều hành nghiệp vụ trong scope |
| `member` | Dùng agent và resource được cấp trong đúng Workspace |
| `executive_viewer` | Người được ủy quyền xem aggregate trong Executive Workspace |

Company Root Membership là quan hệ kỹ thuật để chứng minh account thuộc công ty. Khi Admin chọn
một lead/member đã đăng ký, backend explicit-enroll account đó vào Company Root nếu cần rồi mới
tạo Workspace Membership. Platform Admin không được tự chọn chính mình làm business lead/member.

Một account có thể có role khác nhau theo Workspace:

```text
user A
├── Product Delivery Workspace: lead
└── Quality Assurance Workspace: member
```

## 4. Luồng tạo Workspace phòng ban

1. Platform Admin nhập tên và key của Workspace.
2. Chọn `product_delivery` hoặc `quality_assurance` supporting agent.
3. Chọn một active non-platform account làm trưởng phòng.
4. Backend kiểm tra Company Root active và account active.
5. Backend explicit-enroll Company Membership nếu chưa tồn tại.
6. Tạo Workspace và đúng một active lead membership trong transaction.
7. Ghi audit actor, workspace, profile và lead.
8. Admin phân thêm member; user thấy Workspace ở request kế tiếp.

Lead không tạo Workspace, không tự bổ nhiệm lead khác và không tự thêm member trong baseline.

## 5. Executive Workspace và truy vấn chéo phòng ban

### 5.1 Cấp quyền cho giám đốc

1. Platform Admin tạo Workspace với `agent_profile=executive`.
2. Chọn giám đốc làm `lead`, hoặc thêm người được ủy quyền vào Executive Workspace.
3. User không có active membership trong Executive Workspace thì Executive Agent trả `DENY`.

### 5.2 Phạm vi Executive Agent

Sau khi xác thực quyền Executive Workspace, server tự suy ra source scope:

```text
all active Product Delivery Workspaces
∪ all active Quality Assurance Workspaces
trong Company Root
```

Client/model không được tự truyền danh sách Workspace để mở rộng quyền.

Executive Agent được phép:

- Đọc `WorkspaceBrief` đã validate của Delivery và QA.
- Tổng hợp progress, quality, risks, dependencies và decisions needed.
- Nêu rõ source workspace, thời điểm dữ liệu và data gaps.
- Đề xuất hành động; side effect vẫn qua HITL.

Executive Agent không được mặc định:

- Đọc raw chat, private memory, calendar hoặc file cá nhân của thành viên.
- Dùng quyền giám đốc để gọi trực tiếp tool nội bộ của Delivery/QA.
- Bỏ qua consent, resource mapping hoặc data classification.
- Suy diễn dữ liệu còn thiếu thành fact.

Luồng dữ liệu an toàn:

```text
Department resources
→ Department policy/tool boundary
→ validated WorkspaceBrief
→ Executive aggregation
→ ExecutiveBrief + sources + data_gaps
```

## 6. Authorization hiệu lực

Mỗi request specialist agent phải thỏa:

```text
account active
∩ Company Root active
∩ active Company Membership
∩ target Workspace active
∩ active Workspace Membership
∩ agent profile phù hợp
∩ allowed resource IDs
∩ consent
∩ purpose/data classification
∩ approval nếu có side effect
```

Executive request thay `target Workspace Membership` bằng active membership trong Executive
Workspace; danh sách Department Workspace nguồn do server suy ra.

Thiếu bất kỳ điều kiện nào thì `DENY`/`MASK`; không retrieval trước rồi mới lọc kết quả.

## 7. Invariant bắt buộc

1. Có đúng một Company Root với slug `company-root` trong workflow sản phẩm.
2. User/Admin không có API tạo thêm công ty.
3. Mọi Business Workspace thuộc Company Root.
4. Mỗi Workspace active có đúng một active primary lead.
5. Không revoke lead hiện tại trước khi có replacement hoặc suspend Workspace.
6. Workspace Membership active suy ra Company Membership active.
7. Platform Admin không tự có business-data entitlement.
8. Department member không truy cập Workspace phòng ban khác.
9. Executive scope chỉ mở qua membership của Executive Workspace.
10. Executive Agent chỉ dùng validated brief/aggregate, không dùng raw department content.

## 8. Lifecycle cơ bản

### Workspace

```text
active -> suspended -> active
active/suspended -> archived
```

- `active`: agent và membership có thể được authorize.
- `suspended`: từ chối request mới nhưng giữ lịch sử/audit.
- `archived`: không còn xuất hiện trong discovery; không xóa cứng dữ liệu nghiệp vụ.

### Membership

```text
active -> suspended -> active
active/suspended -> revoked
```

Thay lead thực hiện trong transaction: demote lead cũ thành member, activate lead mới và ghi audit.

## 9. API boundary baseline

```text
# Company metadata — Platform Admin only
GET   /api/v1/admin/company

# Workspace control plane — Platform Admin only
POST  /api/v1/workspaces/{company_id}/agent-workspaces
GET   /api/v1/workspaces/{company_id}/agent-workspaces
PATCH /api/v1/workspaces/{company_id}/agent-workspaces/{workspace_id}
PATCH /api/v1/workspaces/{company_id}/agent-workspaces/{workspace_id}/lead
POST  /api/v1/workspaces/{company_id}/agent-workspaces/{workspace_id}/members
DELETE /api/v1/workspaces/{company_id}/agent-workspaces/{workspace_id}/members/{membership_id}

# User discovery — current membership derived by server
GET   /api/v1/workspaces/{company_id}/agent-workspaces/available
```

`POST /api/v1/admin/workspaces` không còn tạo công ty và trả `409` vì deployment này chỉ có một
Company Root.

## 10. Audit tối thiểu

- `agent_workspace.created`
- `agent_workspace.updated`
- `agent_workspace.lead_assigned`
- `agent_workspace.member_upserted`
- `agent_workspace.membership_revoked`
- `agent_workspace.conversation_linked`
- `agent_workspace.conversation_unlinked`

Audit lưu actor, target, profile, Workspace, before/after metadata đã sanitize và timestamp; không
log raw conversation content hoặc secret.

## 11. Baseline đã triển khai

- Company Root singleton được resolve bằng slug cố định.
- Admin UI không còn màn hình tạo/chọn công ty.
- Admin tạo Workspace, chọn Delivery/QA/Executive Agent, lead và member.
- User UI chỉ discovery Workspace được phân, không có form quản trị.
- Owner/Lead/User không gọi được Workspace control plane.
- Executive Workspace là profile hợp lệ trong model/API/migration.
- Executive scope yêu cầu membership trong Executive Workspace và tự lấy các Department Workspace active.
- Một active Workspace có tối đa một active lead bằng partial unique index.
- Revoke Company Membership làm agent scope fail closed ở request kế tiếp.

## 12. Việc còn lại cho agent runtime

1. Product Delivery Agent tạo validated `WorkspaceBrief` thật.
2. Quality Assurance Agent tạo validated `WorkspaceBrief` thật.
3. Executive Agent đọc hai loại brief qua orchestrator, không gọi raw specialist tools.
4. Nối Workspace selector/context vào `/chat` hoặc màn hình agent tương ứng.
5. Thêm E2E: Admin tạo ba Workspace → ba role đăng nhập → denial/cross-workspace/aggregate pass.
6. Thêm audit before/after và reason đầy đủ cho transition nhạy cảm.

## 13. Acceptance cases bắt buộc

- Không có nút/API tạo công ty thứ hai.
- Admin tạo Delivery/QA/Executive Workspace và bổ nhiệm lead thành công.
- User thường không tạo, sửa, suspend hoặc phân member Workspace.
- Lead chỉ thấy Workspace được phân.
- Delivery user đoán QA Workspace ID bị `DENY`.
- User không thuộc Executive Workspace gọi Executive Agent bị `DENY`.
- Giám đốc trong Executive Workspace nhận scope gồm các Delivery/QA Workspace active.
- Executive output không chứa raw private chat/memory/calendar.
- Suspend/revoke membership có hiệu lực ở request kế tiếp.
- Platform Admin thiếu support grant không đọc được raw business data.
