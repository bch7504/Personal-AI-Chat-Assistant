# Orbit frontends

`Frontend/` là npm workspace chứa hai ứng dụng Vite chỉ chạy local:

- `user/` — ứng dụng người dùng tại <http://localhost:5173>.
- `admin/` — ứng dụng quản trị tại <http://localhost:5174>.
- `shared/` — style dùng chung.

## Cài đặt

```bash
cd Frontend
npm install
```

## Chạy

```bash
# User app
npm run dev:user

# Admin app, chạy ở terminal khác
npm run dev:admin
```

Backend cần chạy tại <http://127.0.0.1:8000>. Cả development và build local đều dùng URL này làm mặc định.

## Cấu hình tùy chọn

Chỉ cần tạo file môi trường nếu muốn đổi URL hoặc bật Google Sign-In:

```powershell
Copy-Item user\.env.example user\.env
Copy-Item admin\.env.example admin\.env
```

Các biến hỗ trợ:

- User: `VITE_API_BASE_URL`, `VITE_WS_BASE_URL`, `VITE_ADMIN_APP_URL`, `VITE_GOOGLE_CLIENT_ID`.
- Admin: `VITE_API_BASE_URL`, `VITE_USER_APP_URL`.

## Build kiểm tra

```bash
npm run build
```

Output được tạo trong `user/dist/` và `admin/dist/`; đây là build local để kiểm tra, không có cấu hình triển khai cloud.
