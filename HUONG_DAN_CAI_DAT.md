# Tool Voice — Hướng dẫn cài đặt (cho người dùng)

## Yêu cầu máy
- **Windows 11** (hoặc Windows 10 mới), 64-bit.
- **Card đồ họa NVIDIA** (GTX/RTX) còn trống ~6GB VRAM trở lên, **driver NVIDIA mới**.
- **~30GB trống** ổ C (cho Linux engine + model) và mạng Internet (lần đầu tải nhiều).
- **Ảo hóa (Virtualization) bật trong BIOS** — hầu hết máy đời mới đã bật sẵn. Nếu báo lỗi WSL, vào BIOS bật "Intel VT-x / AMD-V / SVM".

## Cài đặt
1. Chạy **`ToolVoice-Setup-1.0.0.exe`** → cài xong có icon **Tool Voice** ngoài desktop + trong Start Menu.
2. Mở **Tool Voice** lần đầu:
   - App kiểm tra máy. Nếu **chưa có Linux engine**, nó sẽ xin quyền Admin → bấm **Yes**, để nó cài WSL.
   - Hiện thông báo **"Khởi động lại máy"** → **restart máy**.
3. Mở lại **Tool Voice**:
   - App tự cài engine TTS trong Linux (tải torch + model, **lần đầu ~15–30 phút**, có thanh tiến trình).
   - Lần đầu khởi động engine nhanh sẽ **warmup ~2–3 phút** (compile), các lần sau nhanh.
4. Cửa sổ Tool Voice mở ra → dùng bình thường. Từ lần sau mở app chỉ mất ~30s.

> **Không cần tạo tài khoản/mật khẩu Linux gì cả** — app tự lo.

## Chế độ chạy
- **Nhanh (Linux/WSL, ~2–3 giây/câu):** mặc định, nếu máy cài được WSL.
- **Thường (Windows, ~13 giây/câu):** tự động dùng nếu máy **không** cài được WSL (vd ảo hóa tắt) — app vẫn chạy được, chỉ chậm hơn.

## Cập nhật
Khi có bản mới, mở app sẽ tự thông báo và tải bản cập nhật (chỉ vài MB cho phần giao diện).

## Nếu gặp lỗi
- "WSL/virtualization" → vào BIOS bật ảo hóa, hoặc app sẽ tự chạy chế độ Windows chậm hơn.
- Cài kẹt ở bước tải → kiểm tra mạng, mở lại app (nó tự tiếp tục chỗ dở).
- Hết dung lượng ổ C → dọn bớt rồi mở lại.
