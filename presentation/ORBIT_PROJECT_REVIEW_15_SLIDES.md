# Orbit AI Assistant — Kịch bản thuyết trình 15 slide

> Review theo source tại `d3537ee` và worktree ngày 01/09/2026
> Cấu trúc: **10 slide Personal Agent + 5 slide mở rộng Multi-Agent**

---

## 0. Logic trình bày đã khóa

### Một câu mô tả đúng nhất về dự án

> **Orbit là ứng dụng chat có Personal Agent giúp mỗi người dùng chuyển hội thoại được cấp quyền thành thông tin và hành động cá nhân có kiểm soát; trên cùng nền tảng, dự án mở rộng thêm các Workspace Agent chuyên biệt để xử lý nghiệp vụ Delivery và QA mà không làm rộng quyền của Personal Agent.**

### Những điểm phải nói đúng

1. **Đề tài gốc là Personal Agent trong Chat.** Pain point ban đầu là task, deadline, lịch hẹn và lời hứa bị chôn trong tin nhắn.
2. **Multi-Agent không phải pain point ban đầu và không thay thế Personal Agent.** Đây là hướng mở rộng kiến trúc, được áp dụng trong boundary khác là Organization Workspace.
3. **Personal Space và Organization Workspace tách biệt.** Personal data thuộc người dùng; Workspace data phụ thuộc membership, business role, source binding và AI consent.
4. **Product Delivery Multi-Agent đã có implementation thật trên nhánh.** Hệ thống có adaptive routing, Supervisor và bốn specialist đang hoạt động.
5. **Không nói năm specialist đã hoạt động đầy đủ.** `Capacity & Flow` có contract/code nhưng đang feature-gated vì chưa đủ dữ liệu capacity và fairness policy.
6. **Quality Assurance là một Workspace Agent riêng.** Nó không phải specialist bên trong Product Delivery.
7. **Không dùng số liệu của nhánh `main` như số đo của nhánh này.** Metric 91,9% Task F1 và 82,1% deadline trên `origin/main` thuộc source revision khác; chỉ dùng khi ghi rõ là baseline tham khảo hoặc đã chạy lại trên current SHA.
8. **Không tuyên bố đã deploy public.** Repo có Docker/Compose và local runtime, nhưng `README.md` hiện ghi chưa deploy lên domain public.

### Câu chuyện 15 slide

```text
Vấn đề trong chat
  → vì sao cần Personal Agent
  → Orbit biến hội thoại thành hành động như thế nào
  → sản phẩm đã triển khai gì
  → kiến trúc, quyền và HITL
  → bằng chứng chất lượng và giới hạn đo lường
  → vì sao nghiên cứu Multi-Agent
  → tách Personal Space khỏi Organization Workspace
  → Product Delivery adaptive multi-agent
  → Quality Agent và typed handoff
  → trạng thái, hướng phát triển và kết luận
```

---

# PHẦN I — PERSONAL AGENT

## Slide 1 — Giới thiệu đề tài

### Nội dung trên slide

**ORBIT AI ASSISTANT**  
**AI Agent Trợ lý cá nhân trong ứng dụng Chat**

> Biến hội thoại được cấp quyền thành thông tin và hành động cá nhân có kiểm soát.

- Hiểu hội thoại.
- Tổ chức công việc cá nhân.
- Chủ động đề xuất, người dùng quyết định.

### Lời thuyết trình

Orbit bắt đầu từ một bài toán rất gần với người dùng ứng dụng chat: thông tin quan trọng đã xuất hiện trong hội thoại nhưng chưa được chuyển thành việc cần làm. Dự án xây dựng một Personal Agent cho mỗi người dùng, có thể tóm tắt nội dung, tìm task và deadline, quản lý memory, reminder và Google Calendar. Agent có khả năng lập kế hoạch và gọi công cụ, nhưng các hành động ghi dữ liệu nhạy cảm vẫn phải dừng để người dùng xác nhận.

Phần chính của bài trình bày là Personal Agent. Phần cuối giới thiệu Multi-Agent như một hướng mở rộng đã được hiện thực hóa riêng trong Organization Workspace; nó không làm thay đổi bài toán gốc.

### Gợi ý hình

Cửa sổ chat ở bên trái, Orbit ở giữa, các đầu ra `Summary · Task · Reminder · Calendar` ở bên phải.

### Bằng chứng repo

`Frontend/detai.md` · `README.md` · `src/agents/graph.py` · `Frontend/user/src/pages/PersonalAssistantPage.jsx`

---

## Slide 2 — Bối cảnh và pain point thực tế

### Tiêu đề trên slide

**Công việc bị chôn trong dòng hội thoại**

### Nội dung trên slide

- Người dùng nhận nhiều tin nhắn qua chat 1–1 và nhiều nhóm.
- Một đoạn chat có thể đồng thời chứa task, owner, deadline, lịch hẹn và thay đổi quyết định.
- Sau khi đọc chat, người dùng vẫn phải tự ghi task, đặt reminder và tạo lịch.
- Khi thông tin bị sửa hoặc hủy ở tin nhắn sau, bản ghi thủ công dễ trở nên sai.

> “Mình hoàn tất checklist OAuth trước 12:00 ngày 03/09. Review kết quả lúc 15:00.”

Đoạn chat chứa:

- Cam kết công việc: hoàn tất checklist OAuth trước 12:00.
- Lịch hẹn: review lúc 15:00.

### Lời thuyết trình

Pain point không phải người dùng thiếu một ứng dụng quản lý task. Vấn đề là khoảng trống từ hội thoại đến hành động. Thông tin đã có trong chat nhưng người dùng phải đọc lại, diễn giải và nhập sang nhiều nơi. Khi hội thoại dài hoặc có nhiều người, việc xác định ai thực sự cam kết, deadline nào là mới nhất và lịch nào đã bị đổi trở nên khó hơn.

Orbit giải quyết chính khoảng trống này: hiểu dữ liệu chat trong phạm vi được phép và đưa nó vào một quy trình cá nhân có thể kiểm tra.

### Gợi ý hình

Một luồng chat dài; ba đoạn được highlight là `Task`, `Deadline`, `Meeting`.

### Bằng chứng repo

`Frontend/detai.md` · `docs/testing/PERSONAL_AGENT_END_TO_END_TEST_SCRIPT.md` · `src/api/chat_routes.py` · `src/websocket/`

---

## Slide 3 — Vì sao cần Agent, không chỉ cần chatbot?

### Tiêu đề trên slide

**Trả lời là chưa đủ — hệ thống phải biết lập kế hoạch và hành động đúng**

### Nội dung trên slide

Một chatbot chủ yếu tạo câu trả lời. Orbit phải thực hiện cả chu trình:

1. Xác định ý định.
2. Chọn đúng nguồn dữ liệu.
3. Hỏi lại khi thiếu ngày, giờ hoặc thời lượng.
4. Gọi đúng tool.
5. Kiểm tra kết quả.
6. Xin xác nhận trước side effect.
7. Duy trì ngữ cảnh qua nhiều lượt.

| Hữu ích | An toàn | Hiệu quả |
|---|---|---|
| Hiểu tiếng Việt/Anh và câu tự nhiên | Không đọc ngoài quyền, không tự ghi dữ liệu | Giới hạn tool/token và tránh xử lý dư |

### Lời thuyết trình

Nếu chỉ tóm tắt một đoạn văn, chatbot có thể đủ. Nhưng khi người dùng nói “đặt lịch họp team”, hệ thống phải nhận ra thiếu ngày, giờ bắt đầu và thời lượng; hỏi đúng phần còn thiếu; kiểm tra Calendar; tạo bản nháp; rồi dừng chờ xác nhận. Khi người dùng bổ sung thông tin ở lượt sau, agent phải tiếp tục đúng kế hoạch cũ.

Vì vậy Orbit được thiết kế như một agent có state, plan, tools, memory và human-in-the-loop, không phải một hộp chat chỉ sinh văn bản.

### Gợi ý hình

Vòng lặp `Understand → Plan → Tool → Verify → Confirm → Act`.

### Bằng chứng repo

`src/agents/nodes/personal_query_router_node.py` · `src/agents/nodes/personal_plan_node.py` · `src/agents/nodes/personal_clarification_node.py` · `src/api/routes.py`

---

## Slide 4 — Phạm vi sản phẩm Personal Agent

### Tiêu đề trên slide

**Một người dùng — một Personal Space — một trợ lý riêng**

### Nội dung trên slide

Personal Agent hỗ trợ:

- Phân tích hội thoại mà người dùng có quyền đọc và đã bật AI.
- Tasks, Task Inbox và deadline cá nhân.
- Reminders bền vững.
- Google Calendar riêng của từng người dùng.
- Personal Memory và preference.
- Personal Assistant thread có thể tiếp tục qua nhiều lượt.

> Personal Agent trả lời cho **người dùng hiện tại**. Nó không tự trở thành agent quản trị phòng ban và không có quyền đọc toàn bộ tổ chức.

```text
JWT user
  → server tự resolve Personal Space
  → Tasks / Memory / Reminders / Calendar của user

Conversation request
  → participant check
  → AI consent check
  → authorized message view
```

### Lời thuyết trình

Personal Space là namespace nội bộ được hệ thống tự tạo và resolve theo tài khoản đăng nhập. Frontend không cần chọn Organization Workspace để dùng Personal Assistant. Nếu phân tích một conversation cụ thể, backend kiểm tra riêng membership của conversation và AI consent.

Đây là quyết định quan trọng: Personal Agent được cá nhân hóa nhưng không thể mở rộng quyền chỉ bằng cách client gửi một `workspace_id`.

### Gợi ý hình

Một vòng bảo vệ quanh user, bên trong có `Task · Memory · Reminder · Calendar`; conversation đi qua hai cổng `Participant` và `AI consent`.

### Bằng chứng repo

`src/services/workspace_service.py` · `src/api/routes.py` · `docs/architecture/ARCHITECTURE.md` · `tests/test_auth.py`

---

## Slide 5 — Giải pháp end-to-end

### Tiêu đề trên slide

**Từ tin nhắn đến hành động — luôn giữ nguồn và quyền quyết định**

### Pipeline trên slide

```text
1. Hội thoại được cấp quyền
        ↓
2. Guardrail + Intent Router
        ↓
3. Kế hoạch / Clarification
        ↓
4. Tool đọc dữ liệu hoặc tạo bản nháp
        ↓
5. Response quality + Output guardrail
        ↓
6. Người dùng xác nhận nếu có side effect
        ↓
7. Task / Reminder / Google Calendar / Memory
```

> **AI hiểu và đề xuất — code kiểm soát phạm vi — người dùng quyết định hành động.**

### Lời thuyết trình

Orbit không gửi toàn bộ dữ liệu cho model rồi tin vào câu trả lời. Backend tạo context theo quyền, agent lập kế hoạch có giới hạn, tool chỉ đọc hoặc ghi đúng tài nguyên được phép, sau đó kết quả còn đi qua lớp kiểm tra đầu ra.

Với Calendar hoặc Reminder, tool tạo interrupt có payload cụ thể. UI hiển thị nút Xác nhận hoặc Hủy. Khi resume, backend kiểm tra lại actor, thread và consent hash trước khi thực hiện.

### Gợi ý hình

Pipeline bảy bước, bước 6 dùng màu nổi để thể hiện human-in-the-loop.

### Bằng chứng repo

`src/agents/graph.py` · `src/api/routes.py` · `src/agents/tools/calendar_tool.py` · `src/agents/tools/reminder_tool.py`

---

## Slide 6 — Trải nghiệm người dùng đã triển khai

### Tiêu đề trên slide

**Hai cách dùng AI trong cùng ứng dụng Chat**

### AI Panel trong conversation

- Chọn request window theo số tin hoặc khoảng thời gian.
- `Summarize`: tóm tắt conversation đang mở.
- `Extract tasks`: tạo task suggestion cho người đang đăng nhập.
- `Find schedule`: tìm mốc lịch được nhắc trong chat.
- `Deadlines`: tìm hạn chót trong chat.
- `Suggest reminder`: tạo bản nháp reminder và chờ xác nhận.
- `Ask Orbit`: hỏi tự do về conversation.

### Personal Assistant riêng

- Hỏi về task, lịch, reminder, memory và tin nhắn cũ.
- Lập kế hoạch nhiều bước, gọi nhiều tool nếu cần.
- Hỏi lại khi Calendar/Reminder còn thiếu dữ kiện.
- Lưu thread và pending confirmation qua PostgreSQL.
- Hiển thị process summary an toàn, không lộ chain-of-thought.

### Lời thuyết trình

Hai bề mặt này có mục đích khác nhau. AI Panel xử lý conversation đang mở trong request window cụ thể. Personal Assistant là luồng riêng cho câu hỏi và kế hoạch cá nhân nhiều bước.

Ví dụ, `Find schedule` chỉ tìm lịch được nhắc trong hội thoại; nó không khẳng định Google Calendar đang trống. Muốn kiểm tra lịch thật, Personal Agent phải gọi Calendar tool. Phân biệt này giúp tránh trình bày quá khả năng sản phẩm.

### Gợi ý hình

Mockup chia đôi: `Conversation AI Panel` và `Personal Assistant`.

### Bằng chứng repo

`Frontend/user/src/components/chat/AIPanel.jsx` · `Frontend/user/src/components/ai/PersonalAIChat.jsx` · `docs/testing/PERSONAL_AGENT_END_TO_END_TEST_SCRIPT.md`

---

## Slide 7 — Vòng lặp quản lý công việc cá nhân

### Tiêu đề trên slide

**Orbit không chỉ phát hiện task — nó duy trì cả vòng đời công việc**

### Luồng trên slide

```text
Tin nhắn mới
  → kiểm tra quyền + ngân sách
  → LLM relevance filter
  → trích cam kết từ cửa sổ hội thoại có giới hạn
  → code xác minh owner/evidence và chống trùng
  → task suggestion realtime
  → Accept / Dismiss
  → Task Inbox
  → Reminder liên kết / Calendar cá nhân
```

### Giá trị thực tế

- Giảm thao tác đọc lại và nhập dữ liệu bằng tay.
- Task giữ `conversation_id` và `source_message_ids` để truy nguồn.
- Deadline thay đổi có thể đồng bộ reminder liên kết.
- Timeline hợp nhất Tasks, Reminders và Calendar để xếp ưu tiên, phát hiện xung đột.
- Gợi ý được tạo chủ động nhưng chưa tự biến thành hành động đã duyệt.

### Lời thuyết trình

Ở luồng proactive, hệ thống không chặn thao tác gửi tin. Background task kiểm tra quyền, chạy bước phân loại relevance bằng LLM, sau đó chỉ phân tích một cửa sổ hội thoại có giới hạn. Owner không được tin trực tiếp từ output model; code kiểm tra ai tự cam kết, ai đã xác nhận và ai chỉ được mời.

Sau khi task được chấp nhận, reminder có thể liên kết với deadline. Personal timeline tổng hợp task, reminder và Calendar để phát hiện task quá hạn, deadline dồn sát, lịch chồng nhau hoặc reminder rơi vào giữa cuộc họp.

### Gợi ý hình

Vòng đời từ chat bubble đến Task Inbox, Reminder và Calendar; mỗi artifact có đường quay về source message.

### Bằng chứng repo

`src/services/proactive_service.py` · `src/services/timeline_service.py` · `src/services/personal_schedule_analysis_service.py` · `src/services/reminder_service.py`

---

## Slide 8 — Kiến trúc Personal Agent

### Tiêu đề trên slide

**LLM là một thành phần trong hệ thống — không phải toàn bộ hệ thống**

### Kiến trúc trên slide

```text
React User App
  ├─ Chat / AI Panel
  ├─ Personal Assistant
  ├─ Tasks / Inbox / Memory
  └─ Reminders / Calendar
             │ REST + WebSocket
             ▼
FastAPI Core
  ├─ Auth / Conversation / Consent
  ├─ LangGraph Personal Agent
  ├─ Task / Reminder / Calendar / Memory services
  ├─ Usage / Audit / Guardrail
  └─ Realtime events
             │
             ▼
PostgreSQL + AsyncPostgresSaver + APScheduler
             ├─ Google Calendar API
             └─ Gemini / Groq / OpenAI
```

### LangGraph flow chính

```text
Input Guardrail
  → Personal Query Router
  → Personal Plan
  → Clarify hoặc Planner
  → Tools
  → Response Quality
  → Output Guardrail
  → Process Summary
  → Compact Thread
```

### Điểm kỹ thuật

- Explicit Memory write có đường deterministic riêng.
- Một lượt có tool budget theo server plan; mặc định hiện tại là 8.
- Thread và interrupt được lưu bền vững bằng PostgreSQL checkpointer.
- Tools gồm summary, task extraction, task/memory/timeline reads, Calendar và Reminder CRUD.

### Lời thuyết trình

Kiến trúc tách trách nhiệm rõ ràng. LLM xử lý ngôn ngữ và lựa chọn tool trong một plan bị giới hạn. Tính đúng của quyền, deadline linking, conflict calculation, quota và side effect nằm ở service/code.

Nhờ checkpointer, người dùng có thể rời trang rồi quay lại đúng thread hoặc tiếp tục confirmation đang chờ. Đây là khác biệt quan trọng so với API chat stateless.

### Bằng chứng repo

`src/agents/graph.py` · `src/agents/tools/__init__.py` · `src/main.py` · `src/services/scheduler.py`

---

## Slide 9 — Quyền riêng tư, an toàn và kiểm soát chi phí

### Tiêu đề trên slide

**Trust được xây bằng boundary và kiểm tra bằng code**

### 1. Data boundary

- User chỉ đọc conversation mà mình là participant.
- AI consent được kiểm tra riêng với quyền đọc conversation.
- Context chỉ chứa message trong request window và consent scope.
- Platform admin không có API đọc raw chat, Task, Memory hoặc Reminder cá nhân.

### 2. Action boundary

- Calendar/Reminder write đi qua typed interrupt.
- Resume kiểm tra lại actor, thread và consent hash.
- Payload mơ hồ phải clarification; không tạo side effect trước xác nhận.

### 3. Model boundary

- Input/output guardrail.
- Chat, memory và tool result được coi là dữ liệu không tin cậy.
- Response quality kiểm tra fact bắt buộc.
- Tool budget chặn loop không kiểm soát.

### 4. Cost boundary

- Usage được ghi theo từng account.
- Daily AI allowance được cô lập theo tài khoản.
- Chat mới bị chặn khi hết budget; confirm đang chờ vẫn được hoàn tất.

### Lời thuyết trình

Orbit không dùng prompt để thay thế authorization. Quyền được kiểm tra trước khi tạo context và kiểm tra lại ở thời điểm hành động. Một thay đổi consent giữa lúc đề xuất và lúc xác nhận làm đề xuất cũ không còn hợp lệ.

Chi phí cũng là một boundary sản phẩm: hệ thống ghi usage theo account và không để một người dùng tiêu hết quota của người khác.

### Gợi ý hình

Bốn vòng bảo vệ quanh agent: `Data · Action · Model · Cost`.

### Bằng chứng repo

`src/services/authorization_service.py` · `src/services/consent_service.py` · `src/services/guardrail_service.py` · `src/services/usage_service.py`

---

## Slide 10 — Bằng chứng chất lượng và giới hạn hiện tại

### Tiêu đề trên slide

**Độ chính xác phải được đo theo từng lớp, không gộp thành một con số**

### Bằng chứng có thể công bố cho đúng nhánh

| Lớp | Bằng chứng |
|---|---|
| Regression hiện tại | **1002 passed, 1 skipped** trong full backend pytest chạy trực tiếp trên worktree ngày 01/09/2026 |
| Guardrail | **300/300** case trong regression matrix ngày 31/08; report lúc đó ghi **986 pass, 1 skip** cho full suite |
| Frontend | User và Admin production build **pass** khi review ngày 01/09; User 773 modules, Admin 50 modules |
| Task extraction smoke | README ghi lần gần nhất với `gpt-4o-mini`: **Title F1 100% trên 8 case**, **Date accuracy 100% trên 7 case có ngày** |
| Personal E2E coverage | Bao phủ clarification, multi-tool plan, HITL, memory, proactive task, reminder sync và Calendar |

### Giới hạn cần nói chuyên nghiệp

- Bộ extraction 8 case chỉ là **smoke benchmark nhỏ**, chưa đại diện mọi cách diễn đạt thực tế.
- Quality và latency thay đổi theo provider/model/quota; metric phải đi kèm model, dataset, prompt version và commit SHA.
- `eval/results/agent_acceptance_latest.md` trên nhánh là kết quả cũ ngày 14/08, không đại diện code hiện tại.
- Metric 91,9%/82,1% trên `origin/main` thuộc revision khác; không trình bày như metric của branch nếu chưa rerun.
- Google Calendar phụ thuộc OAuth và network; khi nguồn thiếu, agent phải báo data gap thay vì suy đoán.

### Hướng nâng chất lượng

1. Freeze dataset 100–150 case VI/EN, có phủ định, sửa deadline, hủy lịch và hội thoại nhiều người.
2. Chạy lại acceptance trên đúng current SHA với provider/model được công bố.
3. Theo dõi precision, due-date accuracy, unsupported claim, HITL, latency và accept/edit/dismiss rate.
4. Biến lỗi thực tế đã ẩn dữ liệu thành regression case.

### Lời thuyết trình

Với Orbit, “accuracy” không chỉ là câu trả lời nghe hợp lý. Hệ thống phải đo riêng task extraction, date resolution, routing, source grounding, memory isolation và side effect trước confirmation.

Điểm mạnh hiện tại là regression và guardrail có bằng chứng rộng. Phần cần tiếp tục đầu tư là live-model benchmark trên đúng commit hiện tại. Cách trình bày này không đánh đồng unit test với độ chính xác của LLM.

### Gợi ý hình

Ba tầng `Deterministic correctness → Safety/Security → Live model quality`, kèm thanh `Next: current-SHA evaluation`.

### Bằng chứng repo

`eval/results/guardrail_regression_report.md` · `scripts/eval_extract_tasks.py` · `docs/testing/METRICS.md` · `eval/results/agent_acceptance_latest.md`

---

# PHẦN II — HƯỚNG MỞ RỘNG MULTI-AGENT

## Slide 11 — Vì sao nghiên cứu Multi-Agent sau Personal Agent?

### Tiêu đề trên slide

**Không mở rộng quyền của Personal Agent — tách bài toán phức tạp thành năng lực có boundary**

### Nội dung trên slide

Đề tài gốc vẫn là:

> Personal Agent giúp một người dùng xử lý hội thoại và công việc cá nhân.

Khi số loại nghiệp vụ và tool tăng, một agent duy nhất phải đồng thời hiểu:

- Task và tiến độ.
- Blocker và dependency.
- Milestone và kế hoạch.
- Evidence và quyết định.
- Test, defect và release gate.

Ba vấn đề kiến trúc xuất hiện:

1. Context và tool set quá rộng, dễ gọi thừa hoặc chọn sai.
2. Khó quy trách nhiệm và đánh giá từng loại suy luận.
3. Một scope chung dễ làm mờ ranh giới quyền.

> Giữ **một agent giao tiếp với người dùng**, nhưng chỉ delegate cho specialist khi yêu cầu thật sự cần một hoặc nhiều năng lực độc lập.

### Lời thuyết trình

Multi-Agent trong Orbit không bắt nguồn từ việc Personal Agent “không đủ quyền quản lý nhóm”. Dự án chủ động không cấp quyền đó cho Personal Agent.

Hướng Multi-Agent xuất phát từ bài toán kiến trúc: khi một request nghiệp vụ cần nhiều loại phân tích, hệ thống phải chia trách nhiệm, giới hạn context và giữ provenance. Nhánh hiện tại áp dụng hướng này trong Organization Workspace — một boundary riêng có membership và role riêng.

### Gợi ý hình

Một agent với quá nhiều tools được tách thành `Workspace Agent → bounded specialists`; phía dưới ghi `Personal Agent remains separate`.

### Bằng chứng repo

`docs/implementation/PRODUCT_DELIVERY_ADAPTIVE_ORCHESTRATION_PLAN_V3.md` · `docs/implementation/PRODUCT_DELIVERY_MULTI_AGENT_IMPLEMENTATION_STATUS.md`

---

## Slide 12 — Personal Space và Organization Workspace

### Tiêu đề trên slide

**Hai trust boundary trên cùng nền tảng — không phải một agent được tăng quyền**

### Bảng so sánh

| | Personal Agent | Workspace Agent |
|---|---|---|
| Người sử dụng | Mỗi user đã đăng nhập | User được gán `lead/member` |
| Mục tiêu | Công việc và lịch cá nhân | Nghiệp vụ Product Delivery hoặc QA |
| Dữ liệu | Personal Task, Memory, Reminder, Calendar; conversation được cấp quyền | Group/source được Admin link, work item và artifact trong Workspace |
| Resolve scope | Server resolve theo `user_id` | Membership + profile + role + linked source + consent |
| Memory | Private thread và Personal Memory | Thread riêng theo user/workspace/profile/scope hash |
| Hành động | Chính user xác nhận | Proposal, Lead approval và revalidation |

### Invariant cần nhấn mạnh

- Personal Memory không được dùng như Workspace business fact.
- Workspace Agent không đọc raw personal chat hoặc personal Calendar/Memory mặc định.
- Product Delivery và QA không đọc raw data của nhau.
- Handoff liên agent dùng typed artifact, không truyền toàn bộ conversation.

### Lời thuyết trình

Đây là slide thay thế hoàn toàn logic sai “từ câu hỏi của tôi sang câu hỏi của nhóm”. Quan hệ đúng là hai luồng song song trên cùng platform.

Personal Agent tối ưu cho người dùng cá nhân. Organization Workspace là vùng nghiệp vụ được Admin provision, có Lead/Member và nguồn dữ liệu được link rõ. Tách boundary cho phép mở rộng agent mà không đánh đổi quyền riêng tư của phần Personal.

### Gợi ý hình

Hai hình tròn tách biệt `Personal Space` và `Organization Workspace`, cùng nối vào `Orbit Core`; giữa hai hình chỉ có cầu `Typed handoff`.

### Bằng chứng repo

`docs/architecture/ARCHITECTURE.md` · `docs/architecture/WORKSPACE_AGENT_RBAC_MATRIX.md` · `src/services/workspace_agent_memory_service.py`

---

## Slide 13 — Product Delivery Adaptive Multi-Agent

### Tiêu đề trên slide

**Dùng số agent tối thiểu đủ để hoàn thành mục tiêu**

### Luồng trên slide

```text
Lead / Member
  → Product Delivery Workspace Agent
  → policy + scope + intent routing
      ├─ workspace_only: 0 specialist
      ├─ single_specialist: 1 specialist
      └─ multi_specialist: DAG 2–4 specialist
  → governed synthesis
  → facts / recommendations / gaps / sources
```

### Bốn specialist đang hoạt động

1. **Delivery Task Intelligence** — task cụ thể, My Work, tiến độ nhóm/workspace.
2. **Risk & Dependency** — blocker, dependency và hệ quả giao hàng.
3. **Planning & Forecast** — milestone, checkpoint, meeting plan và schedule recommendation.
4. **Evidence & Knowledge** — provenance, freshness, conflict và decision status.

> `Capacity & Flow` hiện **feature-gated**; chưa dùng để đưa ra workforce recommendation.

### Ví dụ routing

- “Task ORB-12 đang ở đâu?” → một Task Intelligence specialist.
- “Blocker này ảnh hưởng milestone thế nào?” → Task → Risk + Planning.
- “Release đã sẵn sàng về Delivery chưa?” → Task + Planning + Risk + Evidence.
- “Xin chào” hoặc câu mơ hồ → không đọc business data; xử lý ở `workspace_only`.

### Lời thuyết trình

Điểm quan trọng của Multi-Agent không phải lúc nào cũng gọi nhiều agent. Router chọn đường nhỏ nhất đủ giải quyết mục tiêu. Greeting không tạo workflow. Exact task chỉ dùng một specialist. Chỉ request thực sự cross-domain mới tạo DAG.

Specialist không gọi trực tiếp lẫn nhau. Supervisor truyền typed upstream result, dependency ID và hash. Nhờ đó có thể kiểm tra dữ kiện downstream đến từ run nào.

### Gợi ý hình

Router ba nhánh `0 / 1 / 2–4 specialists`; nhánh multi hiển thị DAG thay vì fan-out tự do.

### Bằng chứng repo

`src/agents/delivery_orchestration/contracts.py` · `src/agents/delivery_orchestration/request_router.py` · `src/agents/delivery_supervisor/graph.py` · `src/agents/delivery_specialists/`

---

## Slide 14 — Quality Agent và phối hợp Delivery ↔ QA

### Tiêu đề trên slide

**Agent chuyên biệt phối hợp qua artifact có kiểm chứng, không chia sẻ raw data**

### Quality Assurance Workspace Agent

- Đọc authorized QA snapshot.
- Tổng hợp work item, test run, defect, evidence, traceability gap và release candidate.
- `READY / AT_RISK / NOT_READY` do deterministic policy engine quyết định.
- LLM chỉ giải thích; không được nâng `NOT_READY` thành `READY`.

### Phân quyền nghiệp vụ

- **QA Member:** chạy test, nộp evidence, báo defect trong group được phép.
- **QA Lead:** xác minh evidence, quản lý quality policy/waiver và quyết định release.
- Platform Admin quản lý membership/source nhưng không tự có quyền business data.

### Handoff

```text
Product Delivery
  → typed ReleaseCandidate / Delivery handoff
  → Core validate + persist + audit
  → Quality Assurance
  → deterministic readiness + evidence
  → trạng thái có cấu trúc quay lại Delivery
```

### Điểm không được nói sai

- QA không phải specialist thứ năm của Product Delivery.
- Delivery không đọc raw QA conversation.
- QA không đọc raw Delivery conversation.
- Đây là typed handoff do Core kiểm soát, không phải agent-to-agent chat tự do.

### Lời thuyết trình

Quality Agent minh họa lý do cần profile riêng. Delivery có thể đánh giá tiến độ giao hàng, nhưng không được tự kết luận chất lượng đã đạt. QA dùng dữ liệu test, defect và evidence của chính workspace QA; readiness được rule engine khóa.

Hai bên phối hợp qua `ReleaseCandidate` và trạng thái có cấu trúc. Cách này cho phép truy vết và ngăn một agent mượn quyền của agent khác.

### Gợi ý hình

Hai khối `Product Delivery` và `Quality Assurance`, giữa là artifact `ReleaseCandidate`; không vẽ mũi tên raw chat.

### Bằng chứng repo

`src/agents/profiles/workspace_quality_graph.py` · `src/api/quality_routes.py` · `src/api/quality_control_routes.py` · `src/api/release_candidate_routes.py`

---

## Slide 15 — Trạng thái, hướng phát triển và kết luận

### Tiêu đề trên slide

**Từ Personal Agent đáng tin cậy đến nền tảng agent có boundary**

### Trạng thái có thể công bố

#### Personal Agent

- Chat, Quick Actions, Personal Assistant, Task, Memory, Reminder và Calendar có implementation thật.
- LangGraph có plan, clarification, tool budget, HITL, output guardrail và persistent thread.
- Guardrail matrix 300/300 pass trong report 31/08.
- User/Admin production build pass khi review ngày 01/09.

#### Workspace / Multi-Agent

- Product Delivery adaptive agent-first MVP đã được triển khai trong local/demo scope.
- Report 29/08: Product Delivery **38/38 assertions pass**.
- Robustness: **36/36 case có coverage**, live smoke **12/12 pass sau sửa**.
- Multi-agent/seed/guardrail regression tại report: **350 pass, 1 skip**.
- Backend, Product Delivery runtime và QA runtime healthy trong Docker verification.
- Quyết định hiện tại: **CONDITIONAL GO cho demo/acceptance có giám sát**.

### Hướng phát triển

1. **Đóng vòng đo chất lượng Personal Agent**  
   Rerun acceptance trên current SHA; dataset lớn hơn; ghi model/prompt/dataset/version; đo acceptance và edit rate.

2. **Ổn định vận hành Multi-Agent**  
   Provider dự phòng, `StrictLlm`, p95 latency, fallback rate, fault injection và staging load.

3. **Chỉ bật năng lực khi dữ liệu đủ tin cậy**  
   Capacity & Flow chỉ bật sau khi có lịch sử workload/flow và fairness policy; forecast mạnh chỉ dùng khi có baseline.

4. **Đưa hệ thống ra môi trường kiểm chứng thực tế**  
   Public/staging deployment, telemetry, SLO, canary, rollback và phản hồi người dùng thật.

### Câu kết

> **Giá trị của Orbit không nằm ở việc có nhiều agent. Giá trị nằm ở việc biến hội thoại thành hành động đúng nguồn, đúng phạm vi và vẫn do con người kiểm soát.**

### Lời thuyết trình

Orbit đã xây được một Personal Agent có luồng sản phẩm hoàn chỉnh và nền Workspace Agent có kiến trúc multi-agent thực tế. Hai phần không thay thế nhau: Personal giải quyết năng suất cá nhân; Workspace giải quyết nghiệp vụ chuyên biệt trong boundary được cấp.

Hướng tiếp theo không phải thêm agent bằng mọi giá. Dự án ưu tiên đo chính xác trên current SHA, ổn định provider, kiểm thử failure và chỉ bật specialist khi dữ liệu đủ tốt.

### Gợi ý hình

`Personal Agent → Governed Workspace Agents → Extensible AI Agent Platform`

### Bằng chứng repo

`eval/results/guardrail_regression_report.md` · `docs/reports/MULTI_AGENT_EVALUATION_RESULTS_2026-08-29.md` · `docs/implementation/PRODUCT_DELIVERY_MULTI_AGENT_IMPLEMENTATION_STATUS.md` · `README.md`

---

# Phụ lục A — Nhịp trình bày 12–15 phút

| Slide | Thời lượng | Trọng tâm |
|---|---:|---|
| 1 | 35 giây | Tên đề tài và lời hứa sản phẩm |
| 2 | 50 giây | Pain point từ chat đến hành động |
| 3 | 55 giây | Vì sao cần agent |
| 4 | 50 giây | Personal scope và quyền |
| 5 | 55 giây | Pipeline giải pháp |
| 6 | 60 giây | Hai trải nghiệm AI |
| 7 | 65 giây | Proactive và vòng đời công việc |
| 8 | 65 giây | Kiến trúc LangGraph/backend |
| 9 | 65 giây | Privacy, HITL và cost |
| 10 | 75 giây | Evaluation và giới hạn đo lường |
| 11 | 55 giây | Lý do kỹ thuật của Multi-Agent |
| 12 | 60 giây | Personal/Workspace boundary |
| 13 | 75 giây | Product Delivery adaptive multi-agent |
| 14 | 65 giây | QA và typed handoff |
| 15 | 60 giây | Trạng thái, roadmap, kết luận |

Tổng thời gian nói nội dung chính: khoảng 14 phút.

---

# Phụ lục B — Các phát biểu không nên dùng

| Không nên nói | Cách nói đúng |
|---|---|
| “Pain point ban đầu là quản lý cả nhóm.” | Pain point ban đầu là trợ lý cá nhân trong Chat; Workspace Agent là hướng mở rộng. |
| “Personal Agent phát triển thành Multi-Agent quản trị tổ chức.” | Personal và Workspace là hai boundary riêng trên cùng platform. |
| “Multi-Agent hiện có năm specialist hoạt động.” | Product Delivery có bốn specialist active; Capacity & Flow đang feature-gated. |
| “QA là một specialist của Product Delivery.” | QA là Workspace Agent/profile riêng và nhận typed handoff. |
| “AI tự tạo task, lịch và reminder.” | AI tạo suggestion/draft; side effect nhạy cảm cần confirmation hoặc approval. |
| “Admin đọc được dữ liệu để quản lý.” | Platform Admin quản lý account/config/audit nhưng không tự có quyền đọc raw personal/business data. |
| “Độ chính xác của hệ thống là 100%.” | Công bố riêng từng metric, cỡ mẫu, model, dataset và SHA. |
| “Branch hiện tại đạt 91,9% F1.” | 91,9% là artifact ở source revision khác trên main; phải rerun trước khi gắn cho branch. |
| “Dự án đã deploy production.” | Repo có Docker/local runtime; public deployment là bước vận hành tiếp theo. |
| “Multi-Agent càng gọi nhiều agent càng tốt.” | Router dùng số specialist tối thiểu đủ cho mục tiêu. |

---

# Phụ lục C — Câu hỏi phản biện

## 1. “Tài khoản Lead là gì?”

Lead vẫn là tài khoản user bình thường ở cấp hệ thống, nhưng có `AgentWorkspaceMembership.business_role = lead` trong đúng Organization Workspace. Lead có quyền nghiệp vụ rộng hơn Member trong workspace đó, ví dụ chọn group, review task, phê duyệt proposal hoặc quyết định release theo profile. Lead không phải Platform Admin.

## 2. “Dự án có bao nhiêu loại role?”

Có hai lớp:

- System role: `user`, `platform_admin`.
- Business role trong Agent Workspace: `lead`, `member`; schema còn có `executive_viewer`, nhưng frontend Workspace Agent hiện dispatch Product Delivery và Quality Assurance.

Không gộp Platform Admin với Workspace Lead.

## 3. “Tại sao dùng Agent thay vì gọi LLM một lần?”

Vì bài toán có state nhiều lượt, phải hỏi lại khi thiếu dữ kiện, gọi nhiều tool, duy trì thread, kiểm tra quyền và dừng để xác nhận side effect. Một lượt sinh text không đáp ứng được toàn bộ chu trình đó.

## 4. “AI có tự tạo task hay Calendar không?”

- Proactive detector có thể tạo **task suggestion** ở trạng thái chờ review.
- Quick Action `Extract tasks` tạo suggestion cho tài khoản hiện tại.
- Calendar/Reminder write từ agent phải qua confirmation.
- Workspace write phải qua proposal/approval và revalidation.

## 5. “Multi-Agent hiện đã hoàn thành đến đâu?”

Product Delivery adaptive multi-agent đã được triển khai cho local/demo MVP với router, Supervisor, bốn specialist active, typed lineage, UI và test. Quality Agent có vertical slice, deterministic readiness và Delivery↔QA handoff. Report 29/08 đưa ra `CONDITIONAL GO` cho demo có giám sát; strict-LLM/provider/staging gates vẫn là bước tiếp theo.

## 6. “Tại sao Capacity & Flow chưa bật?”

Code và contract đã có, nhưng repo chủ động feature-gate capability này vì chưa đủ lịch sử capacity/flow và fairness policy. Không dùng message count, tốc độ trả lời hoặc dữ liệu cá nhân để suy luận năng lực con người.

## 7. “Độ chính xác Personal Agent hiện bao nhiêu?”

- Branch có regression và guardrail evidence mạnh.
- README ghi extraction smoke nhỏ: 8 case, title F1 100%; 7 case có ngày, date accuracy 100%.
- Artifact acceptance rộng hơn trên branch là kết quả cũ và không đại diện code hiện tại.
- Metric 91,9%/82,1% ở main thuộc revision khác.

Trước khi công bố accuracy chính thức cho current branch, phải rerun evaluator và ghi SHA/model/dataset.

## 8. “Giới hạn quan trọng nhất của Personal Agent là gì?”

- Model quality và latency phụ thuộc provider/quota.
- Live benchmark hiện chưa đủ lớn trên current SHA.
- Calendar phụ thuộc OAuth và network ngoài hệ thống.
- Context bị giới hạn theo quyền và request window, nên agent phải báo thiếu dữ liệu thay vì giả vờ biết toàn bộ hội thoại.

## 9. “Multi-Agent có làm rò rỉ Personal Memory không?”

Không theo contract hiện tại. Workspace thread có namespace riêng theo actor/workspace/profile/scope hash; Workspace Agent không reuse Personal thread hoặc Personal Memory. Cross-profile phối hợp dùng typed artifact được Core validate.

## 10. “Điểm khác biệt nổi bật nhất của Orbit là gì?”

Orbit kết hợp ba phần:

1. Chat realtime là nguồn công việc.
2. Personal Agent chuyển nội dung được phép thành task/reminder/calendar/memory.
3. Workspace Agent mở rộng phân tích nghiệp vụ bằng specialist có scope, provenance và approval rõ ràng.

Điểm khác biệt không chỉ là câu trả lời AI mà là vòng đời hành động có nguồn và có kiểm soát.

---

# Phụ lục D — Nguồn kiểm chứng chính

## Đề bài và Personal Agent

- `Frontend/detai.md`
- `README.md`
- `docs/testing/PERSONAL_AGENT_END_TO_END_TEST_SCRIPT.md`
- `src/agents/graph.py`
- `src/agents/nodes/`
- `src/agents/tools/`
- `src/api/routes.py`
- `src/services/proactive_service.py`
- `src/services/personal_schedule_analysis_service.py`

## Personal/Workspace boundary

- `docs/architecture/ARCHITECTURE.md`
- `docs/architecture/WORKSPACE_AGENT_RBAC_MATRIX.md`
- `src/services/workspace_service.py`
- `src/services/agent_workspace_service.py`
- `src/services/workspace_agent_memory_service.py`

## Product Delivery Multi-Agent

- `docs/implementation/PRODUCT_DELIVERY_ADAPTIVE_ORCHESTRATION_PLAN_V3.md`
- `docs/implementation/PRODUCT_DELIVERY_MULTI_AGENT_IMPLEMENTATION_STATUS.md`
- `src/agents/delivery_orchestration/`
- `src/agents/delivery_supervisor/`
- `src/agents/delivery_specialists/`

## Quality Assurance và handoff

- `docs/implementation/QUALITY_AGENT_WORKSPACE_COMPREHENSIVE_UPGRADE_PLAN.md`
- `src/agents/profiles/workspace_quality_graph.py`
- `src/api/quality_routes.py`
- `src/api/quality_control_routes.py`
- `src/api/release_candidate_routes.py`

## Evaluation

- `docs/testing/METRICS.md`
- `scripts/eval_extract_tasks.py`
- `eval/results/guardrail_regression_report.md`
- `docs/reports/MULTI_AGENT_EVALUATION_RESULTS_2026-08-29.md`
- `eval/results/agent_acceptance_latest.md`

---

# Ghi chú kiểm chứng tại thời điểm review

- Source revision: `d3537ee`.
- `npm --prefix Frontend run build`: **pass** cho cả User và Admin ngày 01/09/2026.
- `python -m ruff check src tests scripts`: có một lỗi import-order trong `tests/test_guardrail_regression_matrix.py`; không tuyên bố toàn repository đang Ruff-clean.
- Full backend pytest trên worktree hiện tại: **1002 passed, 1 skipped, 31 warnings** trong 8 phút 46 giây.
- File HTML phải được đồng bộ từ nội dung Markdown này; không tiếp tục dùng logic cũ ở slide 11.
