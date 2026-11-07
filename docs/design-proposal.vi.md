# Claugram — Claude Code ↔ Telegram Bridge

`claugram` là Python package dùng để biến Telegram thành kênh điều khiển và human-in-the-loop cho Claude Code đang chạy trên máy cá nhân. Tên viết tắt từ **Claude Telegram**.

Mục tiêu chính: người dùng có thể code với Claude Code trên PC ở nhà, nhưng tương tác qua Telegram khi đang ở xa. Sau khi cài package, chỉ cần chạy:

```bash
pipx install claugram
cd /path/to/project
claugram init
```

Lệnh `claugram init` sẽ onboarding từng bước, kiểm tra Claude Code, cấu hình Telegram bot, tạo MCP server config, tạo hook config, bổ sung rule vào `CLAUDE.md`, và thiết lập daemon/controller để người dùng có thể gửi prompt tiếp qua Telegram.

---

## 1. Tư tưởng thiết kế

`claugram` không cố điều khiển terminal VSCode bằng giả lập bàn phím. Thay vào đó, nó gắn vào đúng các điểm mở rộng của Claude Code:

```text
Telegram
  ↓
claugram bot/controller
  ↓
Claude Code CLI / session resume

Claude Code
  ↓
MCP tools
  ↓
Telegram ask/notify

Claude Code hooks
  ↓
Permission / PostToolUse / Stop / Notification
  ↓
Telegram approve, log, continue
```

Claude Code hiện có CLI để chạy prompt một lượt bằng `claude -p`, tiếp tục conversation gần nhất bằng `claude -c`, resume session bằng `claude -r "<session>"`, và load MCP config bằng `--mcp-config`; các điểm này là nền tảng cho controller của `claugram`.

Claude Code cũng hỗ trợ hook lifecycle như `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PostToolBatch`, `Notification`, `Stop`, `SessionStart`, `UserPromptSubmit`; đây là nền tảng cho permission bridge và Telegram notification.

Telegram Bot API là HTTP interface chính thức cho bot, hỗ trợ nhận update và gửi message; MVP nên dùng long polling để PC ở nhà không cần mở inbound port.

---

## 2. Mục tiêu

### 2.1. User goals

Người dùng cần:

1. Khởi tạo tích hợp Telegram cho từng repo bằng một lệnh.
2. Để Claude Code đang chạy trong VSCode có thể hỏi người dùng qua Telegram.
3. Khi Claude Code xin permission, người dùng có thể approve/deny qua Telegram.
4. Sau mỗi thao tác quan trọng, Claude gửi notification sang Telegram.
5. Khi Claude hoàn thành lượt làm việc, Telegram có thể gửi prompt tiếp để Claude tiếp tục.
6. Khi Claude đã stop hẳn, Telegram controller vẫn có thể resume session bằng prompt mới.
7. Tất cả hoạt động phải có whitelist chat ID, audit log, timeout, và rule an toàn.

### 2.2. Non-goals

`claugram` không nhằm:

1. Thay thế Claude Code.
2. Remote-control VSCode UI.
3. Tự động push/deploy không cần confirm.
4. Mở public server trên PC nhà.
5. Cho phép Telegram chạy shell command tự do.

---

## 3. Ba cơ chế tương tác chính

### 3.1. MCP: Claude hỏi người dùng

Dùng khi Claude đang chạy và cần hỏi người dùng:

```text
Claude Code
  → mcp__claugram__ask_user_question
  → Telegram
  → user reply
  → tool result trả về Claude
```

MCP tools trong Claude Code xuất hiện như regular tools với format `mcp__<server>__<tool>`, và hook matcher có thể match các MCP tools này.

### 3.2. Hooks: Claude báo sự kiện và xin quyền

Dùng cho các sự kiện tự động:

```text
PostToolUse       → báo đã sửa file / chạy test
PermissionRequest → hỏi approve/deny
Stop              → gửi summary, chờ reply để tiếp tục
Notification      → báo permission prompt / idle / attention
```

Claude Code hỗ trợ hook handler dạng `command`, `http`, `mcp_tool`, `prompt`, `agent`; trong đó `mcp_tool` có thể gọi tool trên MCP server đã kết nối.

### 3.3. Controller: người dùng gọi Claude từ Telegram

Dùng khi người dùng chủ động nhắn prompt:

```text
Telegram message
  → claugram controller
  → claude -p "<prompt>" --resume/session
  → stream result
  → Telegram summary
```

Đây là phần giúp Telegram không chỉ là kênh nhận notification mà còn là kênh mở lượt làm việc mới.

---

## 4. Package layout

Tên package Python:

```text
claugram
```

Entry point CLI:

```text
claugram
```

Cấu trúc repo đề xuất:

```text
claugram/
  pyproject.toml
  README.md

  src/claugram/
    __init__.py
    cli.py

    config/
      models.py
      loader.py
      writer.py
      paths.py

    telegram/
      client.py
      polling.py
      formatting.py
      approvals.py
      chat_resolver.py

    mcp/
      server.py
      tools.py

    hooks/
      post_tool_use.py
      post_tool_batch.py
      permission_request.py
      notification.py
      stop.py
      user_prompt_submit.py

    controller/
      daemon.py
      runner.py
      session_store.py
      job_queue.py

    claude/
      cli.py
      session.py
      settings_patch.py
      claude_md_patch.py
      doctor.py

    security/
      policy.py
      redaction.py
      command_classifier.py
      allow_deny.py

    storage/
      sqlite.py
      migrations.py
      audit_log.py

    templates/
      CLAUDE.claugram.md
      settings.local.patch.json
      mcp.claugram.json
      systemd.service
      windows-task.xml
```

---

## 5. CLI tiêu chuẩn

### 5.1. `claugram init`

Lệnh onboarding chính.

```bash
claugram init
```

Options:

```bash
claugram init --project .
claugram init --bot-token env:TELEGRAM_BOT_TOKEN
claugram init --chat-id 123456789
claugram init --mode interactive
claugram init --mode headless
claugram init --install-service
claugram init --dry-run
claugram init --force
```

Nhiệm vụ:

1. Detect project root.
2. Kiểm tra `claude` CLI tồn tại.
3. Kiểm tra `claude auth status`.
4. Kiểm tra Git repo.
5. Hỏi Telegram bot token.
6. Gửi hướng dẫn `/start` bot để lấy `chat_id`.
7. Ghi user secrets.
8. Tạo `.claugram/config.toml`.
9. Tạo hoặc patch `.claude/settings.local.json`.
10. Tạo hoặc patch `CLAUDE.md`.
11. Tạo MCP config.
12. Test `notify_user`.
13. Test `ask_user_question`.
14. Test permission request giả lập.
15. Hỏi có muốn install daemon không.

### 5.2. `claugram doctor`

Kiểm tra toàn bộ setup.

```bash
claugram doctor
```

Checklist:

```text
[OK] Python version
[OK] claugram version
[OK] claude CLI found
[OK] claude auth status
[OK] Telegram token valid
[OK] chat_id allowed
[OK] MCP server starts
[OK] Claude settings valid JSON
[OK] CLAUDE.md contains managed block
[OK] hooks callable
[OK] SQLite state writable
[OK] Git repo detected
```

### 5.3. `claugram mcp-server`

Chạy MCP server cho Claude Code gọi.

```bash
claugram mcp-server --project .
```

Tool names:

```text
mcp__claugram__notify_user
mcp__claugram__ask_user_question
mcp__claugram__request_permission
mcp__claugram__send_summary
mcp__claugram__get_pending_replies
```

### 5.4. `claugram bot`

Chạy Telegram polling bot.

```bash
claugram bot --project .
```

Modes:

```bash
claugram bot --foreground
claugram bot --daemon
claugram bot --once
```

### 5.5. `claugram controller`

Nhận Telegram prompt và gọi Claude Code.

```bash
claugram controller --project .
```

Nhiệm vụ:

1. Nhận message từ allowed chat.
2. Parse command `/ask`, `/code`, `/continue`, `/status`, `/diff`, `/stop`.
3. Resolve project.
4. Resolve Claude session.
5. Gọi `claude -p` hoặc resume session.
6. Stream summary về Telegram.
7. Lưu audit log.

### 5.6. `claugram hook ...`

Các script hook mà Claude Code gọi.

```bash
claugram hook post-tool-use
claugram hook post-tool-batch
claugram hook permission-request
claugram hook notification
claugram hook stop
claugram hook user-prompt-submit
```

Các lệnh này đọc JSON từ `stdin` và in JSON decision ra `stdout` nếu cần.

### 5.7. `claugram status`

```bash
claugram status
```

Hiển thị:

```text
Project: C:\...\repo
Telegram: connected
Daemon: running
Claude session: abc123
Pending approvals: 0
Pending questions: 0
Last activity: 2026-07-13 19:05
```

### 5.8. `claugram uninstall`

```bash
claugram uninstall
```

Options:

```bash
claugram uninstall --project .
claugram uninstall --keep-secrets
claugram uninstall --remove-service
```

---

## 6. File và nơi lưu cấu hình

### 6.1. User-level

Windows:

```text
%APPDATA%\claugram\
  credentials.toml
  state.sqlite3
  logs\
  approvals\
```

Linux/macOS:

```text
~/.config/claugram/
  credentials.toml
  state.sqlite3
  logs/
  approvals/
```

Không commit các file này.

### 6.2. Project-level

Trong repo:

```text
.claugram/
  config.toml
  mcp.claugram.json
  README.md

.claude/
  settings.local.json

CLAUDE.md
```

`settings.local.json` nên là local-only, không commit. Nếu team muốn chia sẻ hook mặc định, tạo thêm file template hoặc docs riêng, không tự động ghi secret vào repo.

---

## 7. Config mẫu

`.claugram/config.toml`:

```toml
version = 1
project_name = "soc-agent-builder"
project_root = "C:\\Users\\CuongNM92\\Documents\\Projects\\SOC\\AISecurity\\Projects\\AgentBuilder"

[telegram]
bot_token_ref = "user:default"
allowed_chat_ids = [123456789]
polling_timeout_sec = 30
parse_mode = "Markdown"

[claude]
mode = "interactive_plus_controller"
default_permission_mode = "default"
session_strategy = "remember_last"
mcp_server_name = "claugram"

[notifications]
notify_post_edit = true
notify_post_bash = true
notify_read_tools = false
notify_batch_summary = true
notify_stop_summary = true

[approval]
permission_timeout_sec = 86400
stop_reply_timeout_sec = 3600
default_on_timeout = "deny"

[security]
deny_shell_patterns = [
  "rm -rf /",
  "format *",
  "del /s *",
  "git push *",
  "git push --force *",
  "curl * | *sh",
  "iwr * | iex"
]
sensitive_file_patterns = [
  ".env",
  ".env.*",
  "*credentials*",
  "*secret*",
  "id_rsa",
  "*.pem"
]

[controller]
enabled = true
headless_output_format = "stream-json"
max_turns = 20
auto_create_branch = true
branch_prefix = "claugram/"
```

---

## 8. MCP tools specification

### 8.1. `notify_user`

Một chiều, không chờ phản hồi.

Input:

```json
{
  "title": "Claude updated files",
  "message": "Edited 2 files and ran tests.",
  "level": "info",
  "session_id": "abc123",
  "project": "agent-builder",
  "metadata": {
    "changed_files": ["src/a.py", "tests/test_a.py"]
  }
}
```

Output:

```json
{
  "ok": true,
  "telegram_message_id": 1001
}
```

### 8.2. `ask_user_question`

Claude chủ động hỏi người dùng.

Input:

```json
{
  "question": "Anh muốn xử lý theo hướng A hay B?",
  "context": "Đang refactor module risk scoring.",
  "options": ["A", "B", "Khác"],
  "allow_free_text": true,
  "timeout_sec": 86400,
  "default": null
}
```

Output:

```json
{
  "answer": "B",
  "answered_by": 123456789,
  "answered_at": "2026-07-13T19:05:00+07:00",
  "raw_text": "B nhé, ưu tiên ít sửa nhất"
}
```

### 8.3. `request_permission`

Dùng cho hook hoặc Claude tự xin quyền.

Input:

```json
{
  "tool_name": "Bash",
  "tool_input": {
    "command": "git push origin feature/x"
  },
  "risk_level": "high",
  "reason": "This command publishes code to remote.",
  "options": ["allow_once", "deny"]
}
```

Output:

```json
{
  "decision": "deny",
  "message": "Không push qua Telegram. Chỉ sửa local."
}
```

### 8.4. `send_summary`

Gửi summary cuối phase.

Input:

```json
{
  "summary": "Đã sửa lỗi import và chạy test pass.",
  "changed_files": ["src/service.py"],
  "tests": [
    {"command": "pytest tests/test_service.py", "status": "pass"}
  ],
  "next_suggestion": "Có thể chạy full test."
}
```

---

## 9. Hook strategy

### 9.1. `PostToolUse`

Không gửi Telegram sau mọi tool. Chỉ gửi khi quan trọng.

Notify ngay:

```text
Write
Edit
MultiEdit
Bash test/build/lint
Bash failed
Git status/diff after meaningful change
```

Không notify từng lần:

```text
Read
Grep
Glob
LS
```

Lý do: `PostToolUse` chạy sau mỗi tool thành công; nếu gửi hết thì Telegram sẽ bị spam. Claude Code cũng có `PostToolBatch`, phù hợp để gom một batch tool song song trước model call tiếp theo.

### 9.2. `PermissionRequest`

Dùng cho Claude Code interactive session trong VSCode terminal.

Input có `tool_name`, `tool_input`, `permission_suggestions`. Hook có thể trả decision `allow` hoặc `deny`, kèm `updatedInput`, `updatedPermissions`, hoặc message khi deny.

Policy:

```text
Auto allow:
- Read, Grep, Glob, LS
- git status, git diff, git log
- pytest/npm test nếu không ghi file ngoài repo

Ask Telegram:
- Write/Edit vào file nhạy cảm
- git push
- install package
- network command
- delete nhiều file
- modify config/deploy/CI

Deny hard:
- format disk
- delete root/home recursively
- print/exfiltrate secrets
- curl|sh / iwr|iex
- write outside project root
```

### 9.3. `PreToolUse`

Dùng để chặn cứng command nguy hiểm trước khi permission dialog xuất hiện.

Trong non-interactive `claude -p`, `PreToolUse` còn quan trọng hơn vì nó có thể xử lý `AskUserQuestion` bằng cách trả `permissionDecision: "allow"` với `updatedInput`, hoặc trả `"defer"` để controller tạm dừng, hỏi user qua Telegram, rồi resume session. Claude Code docs mô tả flow `defer` cho custom UI/headless app: tool bị defer, process trả `tool_deferred`, app hỏi người dùng, sau đó chạy lại `claude -p --resume <session-id>`.

### 9.4. `Stop`

Dùng khi Claude vừa kết thúc response.

Flow:

```text
Claude done
  → Stop hook
  → gửi summary Telegram
  → chờ reply trong N phút
  → nếu reply: trả additionalContext để Claude tiếp tục
  → nếu /done hoặc timeout: cho Claude stop thật
```

`Stop` hook có thể cung cấp `additionalContext` để Claude tiếp tục, nhưng cần tránh loop; Claude Code có `stop_hook_active` để nhận biết hook đang tự kéo dài session, và sẽ override sau 8 lần block liên tiếp.

Policy:

```text
Nếu stop_hook_active = false:
  gửi summary + chờ reply

Nếu stop_hook_active = true:
  chỉ chờ nếu còn dưới max_continue_rounds

Nếu user reply:
  return additionalContext

Nếu user gửi /done:
  allow stop

Nếu timeout:
  allow stop
```

---

## 10. Controller strategy

Controller là phần chạy ngoài Claude.

Nó cần để xử lý case:

```text
Claude đã stop
User nhắn Telegram prompt mới
Controller resume Claude Code
```

Lệnh Telegram:

```text
/start
/help
/projects
/use <project>
/ask <prompt>
/code <prompt>
/continue <prompt>
/status
/diff
/test
/stop
/done
/approve
/deny
```

### 10.1. Session management

SQLite tables:

```sql
projects(
  id text primary key,
  name text,
  root_path text,
  created_at text
)

sessions(
  id text primary key,
  project_id text,
  claude_session_id text,
  last_transcript_path text,
  last_activity_at text,
  status text
)

pending_questions(
  id text primary key,
  project_id text,
  session_id text,
  telegram_message_id integer,
  question text,
  status text,
  created_at text,
  expires_at text
)

pending_permissions(
  id text primary key,
  project_id text,
  session_id text,
  telegram_message_id integer,
  tool_name text,
  tool_input_json text,
  status text,
  created_at text,
  expires_at text
)

audit_events(
  id text primary key,
  project_id text,
  session_id text,
  event_type text,
  payload_json text,
  created_at text
)
```

### 10.2. Running Claude

Interactive VSCode mode:

```bash
claude
```

Headless controller mode:

```bash
claude -p "<prompt>" --output-format stream-json --verbose
```

Resume mode:

```bash
claude -r "<session-id>" "<prompt>"
```

or depending on CLI version and selected strategy:

```bash
claude -c -p "<prompt>"
```

Claude Code CLI docs define `claude -p` as query via SDK then exit, `claude -c` as continue most recent conversation in the current directory, and `claude -r "<session>"` as resume by session ID/name.

### 10.3. Output streaming

Controller should parse `stream-json` if available and send Telegram only meaningful chunks:

```text
- started
- thinking/working indicator, rate-limited
- tool use summary
- errors
- final result
- changed files
- test result
```

Không gửi từng token.

---

## 11. `CLAUDE.md` managed block

`claugram init` sẽ thêm block có marker rõ ràng để update/uninstall an toàn.

```md
<!-- CLaugram:BEGIN -->

## Claugram Telegram human-in-the-loop

You can communicate with the user through the `claugram` MCP server.

Use `mcp__claugram__ask_user_question` when:
- A decision affects product behavior, architecture, data deletion, deployment, credentials, or irreversible changes.
- Requirements are ambiguous and continuing would likely produce the wrong implementation.
- You need user input and the user may not be watching the local terminal.

Use `mcp__claugram__notify_user` when:
- You complete a meaningful milestone.
- You modify files.
- A test, build, or lint command finishes.
- You are blocked or need attention.

Do not ask after every small step.
Do not ask for confirmation for safe read-only exploration.
Prefer concise Telegram messages.
Before stopping after meaningful work, send a short summary through Telegram.

Risky actions require explicit approval:
- git push, deploy, release, publish
- deleting files or directories
- modifying credentials, secrets, `.env`, CI/CD, production config
- installing packages or running network scripts
- writing outside the current project root

If Telegram approval is denied, explain the denial and choose a safer local-only alternative.

<!-- CLaugram:END -->
```

---

## 12. Claude settings hook patch

`claugram init` nên patch `.claude/settings.local.json` thay vì overwrite.

Ví dụ target:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "claugram hook post-tool-use",
            "timeout": 30
          }
        ]
      }
    ],
    "PermissionRequest": [
      {
        "matcher": "Bash|Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "claugram hook permission-request",
            "timeout": 86400
          }
        ]
      }
    ],
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "claugram hook notification",
            "timeout": 30
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "claugram hook stop",
            "timeout": 3600
          }
        ]
      }
    ]
  }
}
```

Dùng `command` hook làm mặc định vì dễ đọc toàn bộ JSON stdin, dễ debug, không phụ thuộc variable substitution phức tạp. Sau này có thể đổi một số event sang `mcp_tool`.

---

## 13. Telegram UX

### 13.1. Notification format

```text
🤖 Claude / agent-builder

✅ Edited files
- src/service.py
- tests/test_service.py

Tests:
✅ pytest tests/test_service.py

Reply to continue, or send /done.
```

### 13.2. Permission format

```text
⚠️ Permission required

Project: agent-builder
Tool: Bash
Command:
git push origin feature/risk-score

Risk: high
Reason: Publishes code to remote.

[Allow once] [Deny]
```

### 13.3. Question format

```text
❓ Claude asks

Đang có 2 hướng sửa:
A. Sửa ít, giữ interface cũ
B. Refactor rõ hơn nhưng đụng nhiều file

Chọn A/B hoặc reply tự do.

[A] [B] [Khác]
```

---

## 14. Security requirements

### 14.1. Authentication

Bắt buộc:

```text
- Whitelist Telegram chat_id.
- Không nhận lệnh từ group nếu chưa bật explicit.
- Không log bot token.
- Token lưu user-level, không lưu project repo.
```

### 14.2. Shell safety

Không có command Telegram dạng:

```text
/cmd <anything>
```

Chỉ có command cấp cao:

```text
/code <task>
/ask <question>
/test
/diff
/status
```

Claude mới là bên quyết định tool, còn hook policy kiểm soát quyền.

### 14.3. Secret redaction

Redact trước khi gửi Telegram:

```text
- API keys
- Bearer tokens
- SSH private key
- LANGFUSE_SECRET_KEY
- password
- .env contents
```

### 14.4. Git safety

Mặc định:

```text
- Không auto push.
- Không auto deploy.
- Có thể auto create branch local.
- Gửi diff summary trước khi người dùng approve bước nguy hiểm.
```

### 14.5. Filesystem safety

Mặc định chỉ cho project root.

Nếu cần thêm directory:

```toml
[security]
allowed_roots = [
  "C:\\Users\\CuongNM92\\Documents\\Projects"
]
```

---

## 15. Onboarding flow chi tiết

Khi chạy:

```bash
claugram init
```

CLI hiển thị từng bước:

```text
Claugram setup for current project

Project root:
C:\Users\CuongNM92\Documents\Projects\...\AgentBuilder

Step 1/9: Check Claude Code
- claude found: C:\Users\...\claude.exe
- version: ...
- auth: OK

Step 2/9: Check Git
- repo: OK
- branch: dev

Step 3/9: Configure Telegram bot
Paste bot token, or set TELEGRAM_BOT_TOKEN.
Token: ********

Step 4/9: Resolve chat ID
Send /start to your bot, then press Enter.
Detected chat_id: 123456789
Use this chat? [Y/n]

Step 5/9: Save secrets
Saved to user config.

Step 6/9: Write project config
Created .claugram/config.toml

Step 7/9: Configure Claude MCP
Created .claugram/mcp.claugram.json

Step 8/9: Patch Claude settings
Patched .claude/settings.local.json

Step 9/9: Patch CLAUDE.md
Inserted CLaugram managed block.

Send test message now? [Y/n]
```

Sau setup:

```text
✅ Claugram ready.

Try:
  claugram bot --project .
  claude --mcp-config .claugram/mcp.claugram.json

Telegram:
  /use agent-builder
  /code giải thích repo này
```

---

## 16. Cài service/daemon

### 16.1. Windows

Option:

```bash
claugram init --install-service
```

Triển khai MVP bằng Windows Task Scheduler:

```text
Task name: Claugram AgentBuilder
Trigger: At logon
Action: claugram controller --project <path>
Working directory: <project>
```

### 16.2. Linux

Tạo systemd user service:

```ini
[Unit]
Description=Claugram controller for %i

[Service]
ExecStart=claugram controller --project %h/projects/%i
Restart=always

[Install]
WantedBy=default.target
```

---

## 17. Roadmap triển khai

### Phase 0 — Skeleton

Deliverables:

```text
- pyproject.toml
- Typer CLI
- config models
- platform paths
- basic logging
- claugram doctor
```

### Phase 1 — Telegram client

Deliverables:

```text
- send_message
- get_updates polling
- allowed_chat_ids
- inline buttons
- reply correlation
```

### Phase 2 — MCP server

Deliverables:

```text
- notify_user
- ask_user_question
- send_summary
- request_permission
```

### Phase 3 — Hooks

Deliverables:

```text
- post-tool-use hook
- permission-request hook
- notification hook
- stop hook with reply continuation
- redaction
- audit log
```

### Phase 4 — Init/onboarding

Deliverables:

```text
- claugram init wizard
- patch CLAUDE.md
- patch settings.local.json
- write MCP config
- test notification
```

### Phase 5 — Controller

Deliverables:

```text
- Telegram /code
- Telegram /continue
- session store
- run claude -p
- resume session
- stream-json parser
- diff/test summary
```

### Phase 6 — Hardening

Deliverables:

```text
- command classifier
- deny/ask/allow policy
- secret redaction
- Windows Task Scheduler installer
- systemd user installer
- uninstall
```

---

## 18. MVP acceptance criteria

MVP pass khi làm được các flow sau.

### Flow 1: Claude notify

```text
User starts Claude Code in project.
Claude edits a file.
PostToolUse hook sends Telegram notification.
```

### Flow 2: Claude asks user

```text
Claude calls mcp__claugram__ask_user_question.
Telegram receives question.
User replies.
Claude receives answer and continues.
```

### Flow 3: Permission approve

```text
Claude requests Bash git push.
PermissionRequest hook sends Telegram approval.
User denies.
Claude receives deny message and does not push.
```

### Flow 4: Stop continue

```text
Claude finishes.
Stop hook sends summary.
User replies “chạy thêm test X”.
Stop hook returns additionalContext.
Claude continues same turn.
```

### Flow 5: Controller resume

```text
Claude has stopped.
User sends /code fix lỗi import.
Controller runs Claude Code in project.
Telegram receives final summary.
```

---

## 19. Design decision summary

| Decision                 | Choice                                                               |
| ------------------------ | -------------------------------------------------------------------- |
| Main install unit        | Python package `claugram`                                            |
| CLI                      | `claugram`                                                           |
| Telegram receive mode    | Long polling by default                                              |
| Public inbound port      | Not required                                                         |
| Claude asks user         | MCP tool                                                             |
| Claude notifications     | Hooks + MCP notify                                                   |
| Permission               | `PermissionRequest` for interactive, `PreToolUse/defer` for headless |
| Continue after stop      | `Stop` hook with reply timeout                                       |
| Continue after full stop | Controller calls Claude resume                                       |
| Secrets                  | User-level config                                                    |
| Project config           | `.claugram/config.toml`                                              |
| Claude rules             | Managed block in `CLAUDE.md`                                         |
| Safety default           | No push/deploy/delete/secrets without approval                       |

---

## 20. Key implementation notes

1. `Stop hook` không được chờ vô hạn. Timeout hợp lý là 15–60 phút. Controller mới là process nên chạy vô hạn.
2. Không ép Claude gọi `ask_user_question` cuối mọi message. Dùng Stop hook để hỏi “reply để tiếp tục”, và controller để resume khi đã stop.
3. `PostToolUse` phải rate-limit, không gửi mọi `Read/Grep/Glob`.
4. `PermissionRequest` là đúng cho interactive session; với `claude -p` headless, thiết kế controller nên hỗ trợ `PreToolUse` + `defer` để hỏi người dùng qua Telegram.
5. Tất cả output gửi Telegram phải redact secret.
6. Không bao giờ expose `/cmd`.
7. Mọi thay đổi project config phải có marker để uninstall/update an toàn.
8. `claugram doctor` là bắt buộc để debug nhanh.
