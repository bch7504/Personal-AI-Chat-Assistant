# Product Brief — Orbit Multi-Agent theo Workspace

> **Trạng thái:** Canonical v1.0
>
> **Cập nhật:** 2026-08-19
>
> **Phạm vi:** Ý tưởng sản phẩm, giá trị và ranh giới MVP. Yêu cầu chi tiết nằm trong [PRD](PRD.md); thiết kế kỹ thuật nằm trong [Architecture](../architecture/ARCHITECTURE.md).

## 1. Tóm tắt một câu

Orbit là ứng dụng AI nội bộ của **một công ty**, trong đó Admin tạo các Workspace phòng ban, chỉ định trưởng phòng và thành viên, còn mỗi Workspace được gắn một Agent chuyên môn; giám đốc dùng Executive Agent để xem bức tranh liên phòng ban qua các bản brief đã kiểm chứng.

## 2. Bài toán

Thông tin vận hành doanh nghiệp đang nằm rải rác trong chat, task, lịch và ghi chú. Ba nhóm người gặp ba vấn đề khác nhau:

- Nhân viên và trưởng phòng mất thời gian tổng hợp tiến độ, rủi ro và việc cần làm của chính phòng ban.
- QA khó ghép trạng thái test, blocker và mức sẵn sàng phát hành thành một kết luận nhất quán.
- Giám đốc cần góc nhìn toàn công ty nhưng không nên đọc trực tiếp mọi hội thoại riêng hay dữ liệu thô của từng phòng.

Một trợ lý chung không giải quyết tốt bài toán này vì không có ranh giới dữ liệu, trách nhiệm chuyên môn và quyền truy cập rõ ràng.

## 3. Ý tưởng sản phẩm

Orbit tách hệ thống thành ba lớp:

1. **Company boundary:** ứng dụng tương ứng với đúng một công ty. Company Root do hệ thống khởi tạo, không phải đối tượng để người dùng tự tạo.
2. **Business Workspace:** Admin tạo Workspace phòng ban, chọn loại Agent, chỉ định một trưởng phòng và quản lý thành viên.
3. **Agent runtime:** request được router quyết định theo scope và profile; policy kiểm tra quyền trước khi Agent hoặc tool đọc dữ liệu.

Ba Workspace Agent của MVP:

| Agent | Workspace phục vụ | Giá trị chính |
|---|---|---|
| Product Delivery Agent | Phòng Product/Delivery | Tổng hợp tiến độ, milestone, blocker, dependency và quyết định cần đưa ra |
| Quality Assurance Agent | Phòng QA | Tổng hợp test status, defect, release risk và kết luận readiness |
| Executive Agent | Workspace của ban giám đốc | Ghép các WorkspaceBrief hợp lệ thành bức tranh liên phòng ban và đề xuất ưu tiên |

Personal Agent hiện có vẫn phục vụ dữ liệu cá nhân, nhưng **không phải** một trong ba Workspace Agent của dự án multi-agent.

## 4. Mô hình nghiệp vụ cốt lõi

### 4.1 Ai tạo và quản lý Workspace

- Chỉ `platform_admin` dùng Admin app để tạo Workspace phòng ban.
- Khi tạo, Admin chọn `agent_profile` và một tài khoản đang hoạt động làm lead.
- Mỗi Workspace có đúng một lead đang hoạt động.
- Admin thêm, thu hồi hoặc đổi thành viên; lead vận hành nghiệp vụ nhưng không tự tạo Workspace mới trong MVP.
- User app chỉ hiển thị các Workspace mà server xác nhận người dùng đang là thành viên.

### 4.2 Giám đốc được cấp quyền thế nào

- Admin tạo một Executive Workspace và thêm giám đốc vào đó.
- Thành viên Executive Workspace có aggregate scope trong cùng Company Root.
- Executive Agent chỉ tiêu thụ `WorkspaceBrief` có nguồn, còn hạn và đúng schema từ Delivery/QA Agent.
- Executive Agent không mặc định đọc raw chat, memory cá nhân hay dữ liệu riêng của phòng ban.

### 4.3 Hai lớp role không được trộn

| Lớp | Giá trị chính | Mục đích |
|---|---|---|
| System role | `platform_admin`, `user` | Quyền dùng Admin control plane hay User app |
| Workspace business role | `lead`, `member`, `executive_viewer` | Quyền nghiệp vụ bên trong Agent Workspace |

Admin không tự động trở thành thành viên nghiệp vụ; lead cũng không tự động có quyền Admin.

## 5. Trải nghiệm chính

### Admin

1. Đăng nhập Admin app.
2. Tạo Workspace, nhập tên/key, chọn profile và lead.
3. Thêm thành viên và liên kết các group conversation phù hợp với Delivery hoặc QA Workspace.
4. Theo dõi trạng thái Workspace và audit log.

### Thành viên phòng ban

1. Đăng nhập User app và thấy các Workspace được phân công.
2. Mở Workspace Agent tương ứng.
3. Hỏi tiến độ, rủi ro, blocker hoặc release readiness trong đúng scope.
4. Xem câu trả lời kèm nguồn, data gap và thời điểm dữ liệu.
5. Xác nhận trước mọi hành động tạo/sửa/xóa task, reminder, lịch hoặc thông báo.

### Giám đốc

1. Mở Executive Workspace.
2. Hỏi tình hình Delivery, QA hoặc dependency liên phòng ban.
3. Nhận ExecutiveBrief từ các WorkspaceBrief hợp lệ.
4. Thấy rõ nguồn, dữ liệu thiếu, brief hết hạn và quyết định cần đưa ra.

## 6. Nguyên tắc không đánh đổi

- Server tự xác định role, profile và allowed scope; không tin các trường quyền do client gửi.
- Kiểm tra membership ở request boundary và kiểm tra lại ở tool/resource boundary.
- Không đưa dữ liệu ngoài scope vào prompt rồi mới yêu cầu model “bỏ qua”.
- Raw data không truyền trực tiếp giữa các Agent; giao tiếp bằng contract có version và provenance.
- Read-only có thể chạy ngay khi được phép; side effect luôn đi qua proposal, preview và human approval.
- Thu hồi membership hoặc consent phải có hiệu lực cho request/tool call tiếp theo.
- Câu trả lời phải phân biệt fact, inference, recommendation và data gap.

## 7. Phạm vi MVP

### Có trong MVP

- Single-company Company Root.
- Admin provisioning cho Delivery, QA và Executive Workspace.
- Lead/member management và user discovery read-only.
- Contract chung cho context, policy decision, tool result, action proposal, WorkspaceBrief và ExecutiveBrief.
- Deterministic router theo `requested_scope`, `target_agent_workspace_id`, profile và intent.
- Delivery/QA read flow có citation và tạo WorkspaceBrief.
- Executive aggregate flow chỉ đọc WorkspaceBrief hợp lệ.
- HITL cho side effect, audit, feature flags, test quyền và dataset đánh giá.

### Ngoài MVP

- Người dùng tự tạo công ty hoặc Workspace phòng ban.
- SaaS multi-tenant cho nhiều công ty.
- Agent tự cấp quyền, tự thêm thành viên hoặc tự liên kết nguồn dữ liệu.
- Executive Agent đọc toàn bộ raw chat của công ty.
- Agent-to-agent chat tự do không qua contract.
- Tự động thực thi side effect không cần xác nhận.

## 8. Trạng thái hiện tại

| Hạng mục | Trạng thái 2026-08-19 |
|---|---|
| Company Root một công ty | Đã có |
| Admin tạo Workspace, chọn profile và lead | Đã có |
| Quản lý member/lead, link conversation, audit | Đã có baseline |
| User chỉ xem Workspace được phân | Đã có |
| Agent contracts, registry, router, scope resolver, resource guard | Đã có foundation và test |
| Specialist tools và prompt Delivery/QA | Chưa hoàn chỉnh |
| Lưu, validate và publish WorkspaceBrief | Mới có contract, chưa có pipeline đầy đủ |
| Executive aggregation runtime | Mới có contract/registry/scope, chưa có flow đầy đủ |
| UI chat trong từng Workspace Agent | Chưa hoàn chỉnh |

Foundation hiện tại đủ để ba workstream Delivery, QA và Executive phát triển song song, nhưng chưa được xem là tính năng multi-agent hoàn tất.

## 9. Thành công được đo bằng gì

- 100% request ngoài membership/scope bị chặn trước khi gọi model hoặc tool dữ liệu.
- 100% side effect yêu cầu approval và revalidate trước khi execute.
- 100% ExecutiveBrief chỉ tham chiếu WorkspaceBrief hợp lệ, còn hạn và cùng Company Root.
- Demo chuẩn chạy được ba luồng Delivery, QA, Executive mà không dùng dữ liệu ngoài scope.
- Bộ eval không có critical cross-workspace leak; các câu hỏi thiếu dữ liệu trả về data gap thay vì bịa.
- Người dùng xác định được nguồn và độ mới của thông tin trong mỗi brief.

## 10. Câu chuyện demo

1. Admin tạo `delivery`, `quality` và `executive`, sau đó phân lead/member đúng vai trò.
2. Thành viên Delivery hỏi tiến độ; Delivery Agent trả về milestone, blocker và nguồn.
3. Thành viên QA hỏi release readiness; QA Agent trả về trạng thái test và rủi ro.
4. Hai Agent phát hành WorkspaceBrief đã validate.
5. Giám đốc hỏi “Bản phát hành có an toàn không?”; Executive Agent tổng hợp hai brief, chỉ ra dependency, data gap và quyết định cần đưa ra.
6. Một người ngoài Workspace thử truy cập và bị từ chối; một hành động ghi chỉ chạy sau khi người có quyền xác nhận.

## 11. Tài liệu liên quan

- [PRD](PRD.md) — yêu cầu sản phẩm và acceptance criteria.
- [Architecture](../architecture/ARCHITECTURE.md) — component, data flow, security boundary và current/target state.
- [Enterprise Workspace Foundation](ENTERPRISE_WORKSPACE_FOUNDATION.md) — nghiệp vụ Workspace và role chi tiết.
- [Multi-Agent Implementation Plan](../implementation/MULTI_AGENT_IMPLEMENTATION_PLAN.md) — phân công, dependency và release gates.
- [Multi-Agent Test Dataset](../testing/MULTI_AGENT_TEST_DATASET.md) — taxonomy và golden cases.
