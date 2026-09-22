# Orbit — Trợ lý AI cá nhân chạy local

Orbit là ứng dụng trợ lý AI cá nhân gồm backend FastAPI/LangGraph và hai giao diện React/Vite. Dự án được cấu hình để chạy trên máy cá nhân; không còn cấu hình cloud, CI hay hook thu thập log của công cụ AI. Docker được giữ lại như một cách build và chạy local.

## Tính năng chính

- Đăng ký, đăng nhập, JWT và phân quyền người dùng/admin.
- Chat cá nhân/nhóm theo thời gian thực bằng WebSocket.
- Trợ lý AI, tóm tắt hội thoại, trích xuất task và nhắc việc có bước xác nhận.
- Task, Memory, Reminder, Calendar và hồ sơ cá nhân.
- Product Delivery Agent, Quality Agent và các luồng multi-agent tùy chọn.
- Google Sign-In và Google Calendar tùy chọn.

## Cấu trúc dự án

```text
.
├── src/                  # Backend FastAPI, agent, service và database
├── Frontend/
│   ├── user/             # Ứng dụng người dùng — localhost:5173
│   ├── admin/            # Ứng dụng quản trị — localhost:5174
│   └── shared/           # CSS dùng chung
├── tests/                # Unit/integration test của ứng dụng
├── eval/                 # Dataset, fixture, schema và kết quả đánh giá
├── scripts/              # Script local, seed dữ liệu và chạy evaluation
├── docs/                 # Tài liệu sản phẩm, kiến trúc và kiểm thử
├── presentation/         # Tài liệu review/demo
├── Dockerfile            # Build backend/runtime image
├── docker-compose.yml    # PostgreSQL + backend + workspace runtimes local
├── .env.example          # Cấu hình backend mẫu cho local
└── pyproject.toml        # Cấu hình Python và pytest
```

`tests/`, `eval/`, các script `eval_*`/`validate_*` và tài liệu kiểm thử được giữ lại để có thể tái lập kết quả đánh giá.

## Yêu cầu

- Python 3.11 trở lên.
- Node.js 24 và npm.
- PostgreSQL 16 chạy trên máy local.
- Docker Desktop (tùy chọn, nếu muốn chạy backend/PostgreSQL bằng container).
- API key của một LLM chỉ cần khi dùng tính năng AI. Các màn hình và API không gọi LLM vẫn chạy khi chưa cấu hình key.

Mặc định dự án dùng PostgreSQL local tại `localhost:5432`, database `orbit`. SQLite chỉ được dùng cho các unit test cô lập.

## Cài đặt

### Windows PowerShell

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_local.ps1
```

Hoặc cài thủ công:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env

Set-Location Frontend
npm install
Set-Location ..
```

### macOS/Linux

```bash
bash scripts/setup.sh
```

Sau khi cài đặt, mở `.env` và điền một trong các API key nếu cần AI:

```dotenv
LLM_PROVIDER=google
GOOGLE_API_KEY=your-key
```

Tạo database local trước khi chạy backend (đổi user/mật khẩu trong `.env` nếu PostgreSQL của bạn dùng thông tin khác):

```powershell
createdb -U postgres orbit
```

Có thể đổi sang `groq`, `openai` hoặc `openrouter` và điền biến API key tương ứng. Không commit `.env` lên Git.

## Chạy local

Mở ba terminal tại thư mục dự án.

Terminal 1 — backend:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/run_dev.py
```

Trên macOS/Linux có thể dùng:

```bash
source .venv/bin/activate
python scripts/run_dev.py
```

Terminal 2 — giao diện người dùng:

```bash
cd Frontend
npm run dev:user
```

Terminal 3 — giao diện admin (tùy chọn):

```bash
cd Frontend
npm run dev:admin
```

Các địa chỉ local:

- User app: <http://localhost:5173>
- Admin app: <http://localhost:5174>
- Backend health: <http://127.0.0.1:8000/health>
- Swagger UI: <http://127.0.0.1:8000/docs>

Backend tự tạo các bảng còn thiếu trong database local ở lần chạy đầu. Tài khoản đầu tiên có email trùng `INITIAL_ADMIN_EMAIL` trong `.env` sẽ nhận quyền admin.

## Chạy bằng Docker local

Build và chạy PostgreSQL, backend cùng hai workspace runtime (`.env` là tùy chọn nếu chưa cần API key):

```powershell
docker compose up --build
```

Các cổng container chỉ bind vào `127.0.0.1`: PostgreSQL `55432`, backend `8000`, Product Delivery runtime `8010` và Quality runtime `8011`. Hai frontend vẫn chạy bằng `npm run dev:user` và `npm run dev:admin` ở máy host.

Nếu chỉ muốn dùng PostgreSQL từ Docker nhưng chạy backend bằng Python trên máy:

```powershell
docker compose up -d postgres
$env:DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:55432/orbit"
python scripts/run_dev.py
```

## Cấu hình Google tùy chọn

- Google Sign-In: điền `GOOGLE_OAUTH_CLIENT_ID` trong `.env` và `VITE_GOOGLE_CLIENT_ID` trong `Frontend/user/.env`.
- Google Calendar: điền `GOOGLE_CALENDAR_CLIENT_ID`, `GOOGLE_CALENDAR_CLIENT_SECRET` và `CREDENTIAL_ENCRYPTION_KEY` trong `.env`.
- Redirect URI local của Calendar là `http://localhost:8000/api/v1/calendar/oauth/callback`.

Tạo file frontend từ mẫu khi cần Google Sign-In:

```powershell
Copy-Item Frontend\user\.env.example Frontend\user\.env
Copy-Item Frontend\admin\.env.example Frontend\admin\.env
```

Hai frontend đã có URL local mặc định, nên bước này không bắt buộc nếu chỉ đăng nhập bằng email/mật khẩu.

## Kiểm tra chất lượng

```bash
# Backend
pytest tests/ -v
ruff check src/ tests/

# Frontend
cd Frontend
npm run build
```

Một số test PostgreSQL sẽ tự bỏ qua nếu chưa đặt `TEST_DATABASE_URL`.

## Chạy đánh giá

Các tài nguyên đánh giá nằm trong `eval/` và không bị lẫn với mã runtime.

```bash
# Đánh giá trích xuất task bằng LLM thật
python scripts/eval_extract_tasks.py

# Kiểm tra dataset multi-agent
python scripts/validate_agent_dataset.py
python scripts/validate_multi_agent_dataset.py
```

`scripts/eval_user_agent.py` yêu cầu một PostgreSQL test riêng thông qua `AGENT_EVAL_DATABASE_URL`; script từ chối database production và host không phải local để tránh ghi nhầm dữ liệu.

## Tài liệu

- [Frontend/README.md](Frontend/README.md) — cấu trúc và lệnh frontend.
- [docs/README.md](docs/README.md) — mục lục tài liệu kỹ thuật.
- [docs/product/PRD.md](docs/product/PRD.md) — yêu cầu sản phẩm.
- [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) — kiến trúc hệ thống.
- [docs/testing/MULTI_AGENT_SYSTEM_EVALUATION_PLAYBOOK_V2.md](docs/testing/MULTI_AGENT_SYSTEM_EVALUATION_PLAYBOOK_V2.md) — quy trình đánh giá multi-agent.
