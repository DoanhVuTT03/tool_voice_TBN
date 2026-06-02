# Tool Voice — Hướng dẫn Build & Phát hành (cho người phát triển)

App gồm 3 phần, tách ra để cập nhật nhẹ:

| Phần | Kích thước | Tải/đóng gói ở đâu | Đổi thường xuyên? |
|---|---|---|---|
| **App code** (`app/`: GUI + engine_src) | vài MB | Trong installer + GitHub Release (`app-vX.zip`) | Có (auto-update) |
| **Runtime** (Python + torch + fish-speech) | ~7GB | Máy đích tự dựng lần đầu (pip) | Hiếm |
| **Model** (openaudio-s1-mini) | ~3.4GB | GitHub Release `model-v1` (HF bị gated) | Không |

## Cấu trúc khi đã cài (trên máy người dùng)
```
%LocalAppData%\Programs\Tool Voice\
  ToolVoice.exe       launcher (kiểm tra update, dựng runtime/model lần đầu, mở GUI)
  config.json         github_owner/repo, port, model_base_url
  app\                tts_gui.py, version.json, engine_src\ (mã fish-speech)
  scripts\            bootstrap_runtime.ps1
  tk_bundle\          tkinter cho python-embeddable
  runtime\            (tạo lần đầu) python-embed + torch + fish-speech
  models\             (tải lần đầu) openaudio-s1-mini
```

## Build trên máy dev (Windows + GPU NVIDIA)

1. **Runtime thử nghiệm** (để test local):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\bootstrap_runtime.ps1
   ```
2. **Đóng ToolVoice.exe**:
   ```powershell
   <python> -m PyInstaller --onefile --windowed --name ToolVoice --noconfirm `
     --distpath build_output\dist --workpath build_output\pyi_build --specpath build_output `
     --paths launcher launcher\launcher_main.py
   ```
3. **Build installer** (Inno Setup):
   ```powershell
   & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\ToolVoice.iss
   ```
   → ra `build_output\installer_out\ToolVoice-Setup-1.0.0.exe`

## Phát hành lên GitHub

### Lần đầu (một lần)
1. Tạo repo (vd `tool-voice`).
2. Điền `config.json`: `github_owner`, `github_repo`, và `model_base_url`
   = `https://github.com/<owner>/<repo>/releases/download/model-v1`.
3. Tạo release **`model-v1`**, upload 5 file model: `config.json`, `special_tokens.json`,
   `tokenizer.tiktoken`, `codec.pth`, `model.pth` (mỗi file < 2GB → hợp lệ).
4. Rebuild installer (vì config.json đã đổi) và phát hành (xem dưới).

### Mỗi lần cập nhật app
1. Tăng `app/version.json` → `app_version` (vd `1.0.1`).
2. Đóng gói `app-v1.0.1.zip` = nội dung thư mục `app/`.
3. Tạo GitHub Release tag `v1.0.1`, đính kèm:
   - `app-v1.0.1.zip`  (để máy khác hot-swap nhẹ)
   - `version.json`     (chứa app_version + runtime_version)
   - `ToolVoice-Setup-1.0.1.exe`  (cho người cài mới)
4. Máy đã cài: lần mở app kế tiếp sẽ thấy thông báo cập nhật và tự tải `app-*.zip`.

> Nếu đổi phần **runtime** (vd nâng torch / sửa fish-speech lõi) → tăng `runtime_version`.
> App sẽ báo "cần cài lại" và trỏ người dùng tải installer mới (không hot-swap được phần nặng).
