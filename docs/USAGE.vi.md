# Claugram — Hướng dẫn sử dụng đầy đủ

**Claugram** là cầu nối giữa **Claude Code** và **Telegram**: điều khiển Claude từ xa và
đưa con người vào vòng lặp (human-in-the-loop). Bạn có thể ra lệnh cho Claude chạy tác vụ,
duyệt/deny các thao tác rủi ro, trả lời câu hỏi của Claude, và nhận tóm tắt — tất cả qua
một bot Telegram, kể cả khi bạn không ngồi trước máy.

- Package Python: `claugram` (cài editable), entry point CLI `claugram`.
- Nền tảng phát triển & kiểm thử: Windows 11 + PowerShell. Chạy được đa nền tảng.

---

## 1. Kiến trúc tổng quan

Claugram gồm **4 tiến trình** cùng chia sẻ **một database SQLite** ở cấp user:

| Thành phần | Vai trò |
|-----------|---------|
| **Bot / Controller** (`claugram bot` hoặc `claugram hub`) | Tiến trình **duy nhất** gọi `getUpdates` của Telegram. Nhận lệnh, đối chiếu câu trả lời/nút bấm với các câu hỏi/permission đang chờ, và đẩy tác vụ vào hàng đợi controller. |
| **MCP server** (`claugram mcp-server`) | Claude Code gọi tự động. Cung cấp các tool `notify_user`, `ask_user_question`, `request_permission`, `send_summary`, `get_pending_replies`. |
| **Hooks** (`claugram hook <event>`) | Claude Code gọi tự động ở các sự kiện lifecycle (PreToolUse, PostToolUse, Notification, Stop, UserPromptSubmit). Định tuyến permission/summary qua Telegram. |
| **Controller worker** | Chạy trong tiến trình bot. Thực thi các lệnh `/code`, `/continue`, `/test`… bằng cách gọi `claude` ở chế độ headless. |

> **Quan trọng:** Chỉ **một** bot được phép poll trên **một** bot token. Chạy 2 instance
> cùng token sẽ gây lỗi `Conflict: getUpdates`. Với nhiều dự án, dùng `claugram hub`
> (một bot quản tất cả) thay vì nhiều `claugram bot`.

**Vị trí dữ liệu (cấp user, KHÔNG nằm trong repo):**

- State DB: `%APPDATA%\claugram\state.sqlite3`
- Credentials (token): `%APPDATA%\claugram\credentials.toml`
- Có thể đổi thư mục này bằng biến môi trường `CLAUGRAM_HOME`.

**Trong mỗi dự án được onboard:**

- `.claugram/config.toml` — cấu hình dự án
- `.claugram/mcp.claugram.json` — file cấu hình MCP cho controller
- `.claude/settings.local.json` — được vá thêm block `hooks` + `env` (idempotent)
- `CLAUDE.md` — chèn block hướng dẫn Claude cách dùng các tool claugram

### Hai cách dùng claugram (Two ways to use claugram)

Claugram nối Claude ↔ Telegram theo **hai hướng**. Điểm chung: **cả hai đều cần bot đang
chạy** (`claugram hub` hoặc `claugram bot`) — vì bot là tiến trình *duy nhất* đọc tin nhắn
Telegram của bạn và ghi câu trả lời vào DB. Không có bot thì tin nhắn vẫn gửi đi được nhưng
**câu trả lời/nút bấm của bạn không bao giờ tới được Claude** (sẽ treo tới khi timeout).

**① Điều khiển từ Telegram (bạn → Claude).** Bạn ở xa, gõ `/code`, `/continue`… trên điện
thoại. Controller (trong tiến trình bot) chạy `claude` headless trên máy bạn, rồi trả kết quả
về Telegram. **Bạn chủ động ra lệnh.** Đây là cách dùng chính, chỉ cần chạy bot.

> *Ví dụ:* Đang đi cà phê, bạn nhắn `/code thêm nút dark-mode vào Settings`. Claude chạy trên
> máy ở nhà, xin duyệt sửa file → bạn bấm **Allow** trên Telegram → xong, nó gửi summary về.

**② Human-in-the-loop trong session Claude local (Claude → bạn).** Bạn **ngồi tại máy**, mở
Claude Code như bình thường nhưng gắn thêm MCP server của claugram:

```bash
claude --mcp-config .claugram/mcp.claugram.json
```

Khi đó Claude có thể **chủ động nhắn cho bạn** qua Telegram khi cần: `ask_user_question` (hỏi
quyết định), `request_permission` (xin duyệt), `notify_user`/`send_summary` (báo tiến độ). Hữu
ích khi bạn giao một việc dài rồi rời bàn.

> *Ví dụ:* Bạn giao một refactor lớn rồi đi họp. Giữa chừng Claude phân vân "đổi tên API này có
> ảnh hưởng public interface — tiếp tục?" → nó ping Telegram, bạn trả lời "có" từ phòng họp →
> session ở máy tiếp tục.

> **Lưu ý:** hook mà `claugram init` đã cài sẵn vào `settings.local.json` **đã tự** định tuyến
> permission + gửi stop-summary cho session local rồi. Cờ `--mcp-config` chỉ **thêm** các tool
> để Claude *chủ động* hỏi/nhắn (những việc nó tự quyết định gọi). Nếu bạn chỉ điều khiển từ xa
> (cách ①) thì **không cần** cách ②.

| | Ai khởi xướng | Claude chạy ở đâu | Cần bot chạy? |
|---|---|---|---|
| **① hub/bot** | Bạn (từ Telegram) | Controller spawn headless | ✅ Có (chính nó) |
| **② --mcp-config** | Claude (khi cần bạn) | Session bạn mở ở terminal | ✅ Có (để nhận trả lời) |

---

## 2. Cài đặt

### 2.1. Yêu cầu

- Python 3.11+ (dự án phát triển trên 3.13)
- Claude Code CLI (`claude`) đã cài và đăng nhập
- Một bot Telegram (tạo qua **@BotFather**) và **chat id** của bạn

### 2.2. Cài package

```bash
git clone https://github.com/cuongnguyengit/claugram
cd mini-claude-remote-control
pip install -e .
claugram version
```

### 2.3. Lấy bot token & chat id

1. Chat với **@BotFather** → `/newbot` → nhận **token** dạng `1234567890:AA...`.
2. Lấy **chat id**: nhắn gì đó cho bot của bạn, rồi mở
   `https://api.telegram.org/bot<TOKEN>/getUpdates` — trường `message.chat.id` là chat id.

> **Bảo mật token:** không commit token vào repo. Claugram lưu token ở
> `%APPDATA%\claugram\credentials.toml` (cấp user). Nếu token từng bị lộ (ví dụ dán vào chat),
> hãy `/revoke` qua @BotFather và tạo lại.

---

## 3. Onboard một dự án

```bash
cd D:/path/to/your-project
claugram init --chat-id <YOUR_CHAT_ID>
```

Lần đầu, truyền token qua một trong các cách:

```bash
# đọc token trực tiếp và lưu vào credentials cấp user (user:default)
claugram init --chat-id 123456789 --bot-token 1234567890:AA...

# hoặc đọc từ biến môi trường
setx CLAUGRAM_BOT_TOKEN "1234567890:AA..."     # PowerShell/Windows
claugram init --chat-id 123456789 --bot-token env:CLAUGRAM_BOT_TOKEN
```

Các lần sau (token đã lưu), chỉ cần:

```bash
claugram init --chat-id 123456789
```

Tuỳ chọn hữu ích của `init`:

| Cờ | Ý nghĩa |
|----|--------|
| `--project <path>` | Chỉ định thư mục dự án (mặc định: tự phát hiện) |
| `--bot-token <ref>` | Token, hoặc `env:VAR`, hoặc `raw:<token>` |
| `--chat-id <id>` | Chat id được phép điều khiển bot |
| `--mode interactive\|headless` | Kiểu tích hợp |
| `--transport telegram\|fake` | Kênh nhắn tin (fake = giả lập, để test offline) |
| `--install-service` | Cài dịch vụ chạy nền khi đăng nhập |
| `--dry-run` | Chỉ in hành động, không ghi |
| `--force` | Ghi đè cấu hình đã có (dùng để **re-patch** khi nâng cấp) |

Kiểm tra sau khi onboard:

```bash
claugram doctor      # chẩn đoán: token, chat, hooks, MCP, session storage…
claugram status      # trạng thái hiện tại của dự án
```

> **Sau khi `init` hoặc `init --force`:** phải **reload session Claude Code** trong dự án đó,
> vì hook chỉ được nạp lúc khởi tạo session.

---

## 4. Chạy bot

### 4.1. Một dự án

```bash
claugram bot --project D:/path/to/your-project
# (claugram controller là alias, framing như một dịch vụ chạy nền)
```

### 4.2. Nhiều dự án (một bot, khuyến nghị)

Onboard từng dự án (mỗi lần `init` sẽ **đăng ký** vào registry), rồi:

```bash
claugram hub
```

Trên Telegram: `/projects` để xem danh sách → `/use <n|name>` để chọn dự án đang thao tác.

---

## 5. Lệnh Telegram

| Lệnh | Tác dụng |
|------|---------|
| `/projects` | Liệt kê các dự án đã đăng ký |
| `/use <n\|name>` | Chọn dự án đang thao tác cho chat này |
| `/code <task>` | Chạy Claude cho một tác vụ (**session mới**) |
| `/ask <câu hỏi>` | Hỏi Claude (chế độ đọc chủ yếu, permission mode `plan`) |
| `/continue <prompt>` | Tiếp tục session gần nhất (hoặc session đang chọn) |
| `/status` | Trạng thái hiện tại |
| `/diff` | Tóm tắt `git diff --stat` |
| `/test` | Chạy test suite của dự án |
| `/sessions` | Liệt kê các session Claude trên đĩa (kèm tên nếu có) |
| `/session <n\|id\|name\|none>` | Chọn session để resume (`none` để bỏ chọn) |
| `/name <n\|id> <tên>` | Đặt tên thân thiện cho một session |
| `/ls [subdir]` | Liệt kê file trong dự án (như `ls`), an toàn trong project root |
| `/cat <file> [start-end]` | Xem nội dung file (có thể giới hạn dải dòng), đã redact secret |
| `/grep <regex>` | Tìm regex (không phân biệt hoa/thường) trong các file text, trả `file:line` |
| `/tree [subdir]` | Cây thư mục (bỏ qua `.git`, `node_modules`… ) |
| `/cat … \| grep … \| head N` | **Pipe** (thực hiện bằng Python, KHÔNG shell): nguồn `ls`/`cat`/`grep`/`tree` nối các filter `grep`/`head`/`tail`/`nl`/`wc`. VD: `/cat app.py \| grep def \| head 20` |
| `/approve` `/deny` | Duyệt/từ chối permission đang chờ |
| `/done` | Cho phép Claude dừng (kết thúc vòng tiếp tục) |
| `/help` | Trợ giúp |

Ngoài ra: **reply trực tiếp** vào một tin nhắn câu hỏi để trả lời đúng câu đó. Khi có
**nhiều** việc đang chờ, bot yêu cầu bạn reply đúng tin để tránh nhầm.

### Cách các lệnh chọn session (quan trọng)

Thứ tự ưu tiên khi controller quyết định resume session nào:

1. Session đã chọn tường minh qua `/session` → `--resume <id>`.
2. `/continue` → resume session được ghi nhớ gần nhất (nếu chưa có, dùng `--continue`).
3. `/code`, `/ask`, `/test` → **luôn tạo session mới** (nên `/sessions` hiện các mục riêng biệt).

**Tag hiển thị:** mỗi tin nhắn có dạng `project · <session>`, trong đó `<session>` là **tên**
bạn đặt (`/name`) hoặc 8 ký tự đầu của session id nếu chưa đặt tên. Ví dụ:
`▶️ hello-project · heavy-wip — resuming…`.

---

## 6. Cấu hình dự án (`.claugram/config.toml`)

File TOML sinh bởi `init`. Dưới đây là **toàn bộ** section và giá trị mặc định.

### `[telegram]`
```toml
[telegram]
bot_token_ref = "user:default"   # tham chiếu token (xem §7)
allowed_chat_ids = [123456789]   # các chat id được phép điều khiển
polling_timeout_sec = 30         # long-poll timeout
parse_mode = "Markdown"
transport = "telegram"           # telegram | fake  (env CLAUGRAM_TRANSPORT ghi đè)
```

### `[schedule]` — cổng thời gian
```toml
[schedule]
respect_schedule = false                       # false = luôn forward
active_days = ["mon","tue","wed","thu","fri"]  # ngày làm việc
active_window = "09:00-18:00"                  # khung giờ forward
timezone = ""                                  # rỗng = giờ hệ thống
```
Khi `respect_schedule = true`, claugram **chỉ** đẩy tin qua Telegram trong `active_days` +
`active_window`. Xem thêm §8 về các biến môi trường ghi đè.

### `[claude]`
```toml
[claude]
mode = "interactive_plus_controller"
default_permission_mode = "default"   # default | plan | acceptEdits | bypassPermissions
session_strategy = "remember_last"
mcp_server_name = "claugram"          # tên MCP server -> prefix mcp__claugram__
```

### `[notifications]`
```toml
[notifications]
notify_post_edit = true
notify_post_bash = true
notify_read_tools = false     # không báo với tool chỉ-đọc (đỡ nhiễu)
notify_batch_summary = true
notify_stop_summary = true
```

### `[approval]`
```toml
[approval]
permission_timeout_sec = 86400   # chờ duyệt permission (mặc định 24h)
stop_reply_timeout_sec = 3600    # chờ reply ở Stop hook (1h)
default_on_timeout = "deny"      # deny | allow  — áp dụng khi hết giờ chờ
max_continue_rounds = 6          # số vòng "tiếp tục" tối đa (chống lặp vô hạn)
```

### `[security]` — chính sách permission
```toml
[security]
deny_shell_patterns = [
  "rm -rf /", "rm -rf ~", "format *", "del /s *",
  "git push --force*", "curl * | *sh", "iwr * | iex", "Invoke-Expression*",
]
sensitive_file_patterns = [
  ".env", ".env.*", "*credentials*", "*secret*", "id_rsa", "*.pem",
]
ask_shell_patterns = [
  "git push*", "pip install*", "npm install*", "npm publish*",
  "docker push*", "kubectl *", "terraform apply*",
]
allowed_roots = []   # ngoài project_root, thư mục nào được phép ghi
```

**Cách policy quyết định** (`evaluate_tool`):
- Tool chỉ-đọc (`Read/Grep/Glob/LS/WebFetch/WebSearch`) → **allow**.
- Tool bridge của claugram (`mcp__claugram__*`) → **allow** (không tự gate chính mình).
- `Bash` → phân loại theo `deny_/ask_shell_patterns` (allow/ask/deny).
- Ghi file: trong project → allow; ngoài `project_root`/`allowed_roots` → **deny**;
  file nhạy cảm → **ask**.
- Tool khác/không rõ (kể cả MCP server khác) → **ask** → duyệt qua Telegram.

### `[controller]`
```toml
[controller]
enabled = true
headless_output_format = "stream-json"
max_turns = 20
auto_create_branch = false
branch_prefix = "claugram/"
attach_mcp = true         # gắn MCP vào lần chạy headless
idle_timeout_sec = 600    # chỉ kill claude nếu KHÔNG có output trong N giây (0 = tắt)
```
> `idle_timeout_sec` là **idle** timeout, không phải tổng thời gian: một lần chạy dài nhưng
> vẫn stream output sẽ **không bao giờ** bị kill. Bộ đếm reset mỗi dòng output. Nhờ vậy
> resume một session **rất nặng** (đã kiểm thử ~1.8MB/1600 dòng, xong ~8s) hoạt động ổn.

---

## 7. Quản lý token (credentials)

Token **không** nằm trong repo. `bot_token_ref` trong config chỉ là **tham chiếu**:

| Dạng ref | Nguồn token |
|----------|-------------|
| `user:<name>` | `%APPDATA%\claugram\credentials.toml`, mục `[tokens.<name>]`. Mặc định `user:default`. |
| `env:<VAR>` | Biến môi trường `<VAR>` |
| `raw:<token>` | Ghi thẳng token (không khuyến nghị) |

File credentials mẫu:
```toml
[tokens]
default = "1234567890:AA..."
```

---

## 8. Biến môi trường

| ENV | Tác dụng |
|-----|---------|
| `CLAUGRAM_HOME` | Đổi thư mục user (DB + credentials). Hữu ích cho test/cô lập. |
| `CLAUGRAM_PROJECT` | Dự án hiện hành cho hook/MCP (được `settings.local.json` tự inject). |
| `CLAUGRAM_MUTE=1` | **Tắt** forward Telegram (ưu tiên cao nhất). Dùng khi ngồi code tại máy. |
| `CLAUGRAM_ALWAYS=1` | **Luôn bật** forward, bất kể `[schedule]`. |
| `CLAUGRAM_TRANSPORT` | `telegram` \| `fake` — ghi đè transport (test offline). |
| `CLAUGRAM_FAKE_DIR` | Thư mục outbox/inbox cho transport `fake`. |
| `CLAUGRAM_IN_CONTROLLER` | Đặt tự động khi chạy trong controller headless; Stop hook **không** block để tránh treo. |

**Thứ tự ưu tiên cổng forward:** `CLAUGRAM_MUTE` > `CLAUGRAM_ALWAYS` > `[schedule].respect_schedule`.

> Các biến `CLAUGRAM_*` có thể đặt trong `env` của `.claude/settings.local.json` để tự áp
> cho dự án mà không cần export thủ công (claugram tự inject `CLAUGRAM_PROJECT`).

---

## 9. Mô hình bảo mật (đọc kỹ)

- Hook **định tuyến TẤT CẢ tool** qua claugram (matcher `*`). Nhờ policy allow-list ở §6,
  tool chỉ-đọc và tool bridge của claugram tự chạy; phần còn lại cần duyệt → **về Telegram**,
  **không** rơi ra prompt terminal (đây là bug đã sửa ở v0.1).
- Hook **không bao giờ làm crash Claude**: mọi handler được bọc, luôn exit 0.
- **Redaction:** secret (token, API key, bearer…) được che trước khi gửi Telegram.
- Chỉ `allowed_chat_ids` mới điều khiển được bot.
- Khi hết giờ chờ, áp `approval.default_on_timeout` (mặc định **deny** — an toàn).

> ⚠️ **Đừng cài hook lên repo mà bạn đang ngồi code trực tiếp bằng Claude Code**, trừ khi hiểu
> rằng hook fire cho *mọi* session trong repo đó — kể cả session bạn tự mở — nên permission sẽ
> đẩy qua Telegram. Khi ngồi tại máy, đặt `CLAUGRAM_MUTE=1` để tắt.

---

## 10. Test không cần Telegram (transport giả lập)

Có thể chạy toàn bộ hệ thống offline bằng transport `fake` (ghi ra `outbox.jsonl`/`inbox.jsonl`):

```bash
setx CLAUGRAM_TRANSPORT fake
claugram init --chat-id 1 --transport fake
```

Bộ test tự động:

```bash
pip install -e .
python -m pytest -q     # 39 test
```

---

## 11. Xử lý sự cố

| Triệu chứng | Nguyên nhân / cách xử lý |
|-------------|--------------------------|
| `Conflict: terminated by other getUpdates` | Đang chạy ≥2 bot cùng token. Tắt hết, chỉ chạy 1 (`bot` hoặc `hub`). |
| Prompt permission hiện ở **terminal**, không qua Telegram | `settings.local.json` còn matcher cũ. Chạy `claugram init --force` rồi **reload session**. |
| `/continue` treo ở "working…" | Đã xử lý ở v0.1: decode UTF-8, `--strict-mcp-config`, guard `CLAUGRAM_IN_CONTROLLER`, idle timeout. Cập nhật bản mới + reload. |
| Bot không phản hồi | `claugram doctor`; kiểm tra token/chat id; kiểm tra chỉ có 1 instance. |
| Câu hỏi/permission (session local) **treo mãi** rồi timeout | Chưa chạy `claugram hub`/`bot`. Bot là tiến trình duy nhất nhận trả lời của bạn và ghi vào DB — phải chạy nó trước (xem §1 "Hai cách dùng"). |
| Onboard project mới nhưng auto-detect `/start` báo Conflict | Bot đang chạy giữ token. Truyền `--chat-id <id>` khi `init` (khỏi cần tắt bot). |
| Emoji lỗi trên Windows | Đặt `PYTHONIOENCODING=utf-8` trước khi chạy. |
| Không thấy session cũ (trước khi cài) | Bình thường — `/sessions` đọc trực tiếp `~/.claude/projects/<slug>/*.jsonl`, resume được cả session có từ trước. |

---

## 12. Gỡ cài đặt

```bash
cd D:/path/to/your-project
claugram uninstall     # gỡ hook/MCP khỏi settings.local.json, dọn block CLAUDE.md
```

---

## Phụ lục — Vòng đời một lệnh `/code`

1. Bạn gửi `/code sửa bug X` trên Telegram.
2. Bot đẩy job vào hàng đợi; controller worker chạy `claude -p ... --output-format stream-json
   --verbose --mcp-config ... --strict-mcp-config` (session mới), kèm heartbeat "still working…".
3. Trong lúc chạy, mỗi thao tác rủi ro của Claude → hook → **permission qua Telegram** (bạn
   `/approve` hoặc `/deny`, hoặc bấm nút).
4. Xong: bot gửi `✅ project · <session> — Done (n tool calls)` + tóm tắt + footer
   `↩︎ Reply to continue · /session <id8>`.
5. Bạn reply để tiếp tục cùng session, hoặc `/done` để dừng.
