Thông tin đề tài

Tên đề tài: AI Agent Trợ lý cá nhân trong Chat (tóm tắt hội thoại, nhắc việc, lên lịch)

🎯 Thực trạng

Người dùng nền tảng chat của Tập đoàn X nhận hàng trăm tin nhắn mỗi ngày qua nhiều nhóm (gia đình, công việc, cộng đồng Doanh nghiệp bất động sản X); các việc cần làm, lịch hẹn, lời hứa bị chôn vùi trong luồng tin nhắn và dễ bị bỏ lỡ.

🔴 Vấn đề

Cần một AI Agent cá nhân gắn trong app chat, tự động đọc hội thoại được người dùng cho phép, tóm tắt các cuộc trò chuyện dài, trích xuất việc cần làm/lịch hẹn, chủ động lập kế hoạch nhắc việc và tạo sự kiện lịch; agent phải biết lập kế hoạch nhiều bước, gọi tool (calendar, reminder, tìm kiếm tin cũ), lưu memory ngữ cảnh người dùng và khi thông tin tin mơ hồ.

🔒 Ràng buộc
Human-in-the-loop bắt buộc xác nhận trước khi tạo/gửi lịch hay nhắc cho người khác
Bảo mật và quyền riêng tư tin nhắn (agent chỉ đọc hội thoại được cấp quyền, tôn trọng E2E — chỉ xử lý phía client hoặc trong vùng đã giải mã của người dùng, không lưu nội dung thô ra ngoài)
Độ chính xác trích xuất task cao (giảm false reminder)
Tối ưu độ trễ và chi phí (chỉ tóm tắt khi cần, cache embedding, batch LLM call)
🛠️ Tech stack gợi ý
LLM: GPT-4o-mini / Claude Haiku cho tóm tắt & trích xuất task
Orchestration: LangGraph (planner–executor + node human confirm)
Vector DB: Qdrant / pgvector lưu memory & lịch sử
Realtime: WebSocket (Socket.IO) đẩy nhắc việc
Tools: Google Calendar API
Scheduler: cron / BullMQ
Semantic search
Backend: FastAPI / Node NestJS
Frontend: React/Next.js + Tailwind
Mobile-friendly
Deploy: Docker + Railway/Render/Vercel
Postgres
Redis
✅ Yêu cầu đầu ra

Cơ bản:

App deploy online, đăng nhập, ≥2 vai trò (người dùng thường & admin)
Agent tóm tắt hội thoại theo yêu cầu, trích xuất task và tạo nhắc việc có xác nhận, hiển thị lịch cá nhân
Có memory hội thoại và xử lý lỗi cơ bản

Nâng cao:

Agent chủ động (proactive) phát hiện cam kết/lịch hẹn ngay khi tin nhắn tới, gợi ý tạo reminder
Đồng bộ Google Calendar 2 chiều
Dashboard 'inbox nhiệm vụ' ưu tiên
Cảnh báo khi vượt hạn mức token/chi phí
Đánh giá độ chính xác trích xuất task trên bộ test