"""Hook handlers invoked by Claude Code via `claugram hook <name>`."""

from . import (
    post_tool_use,
    post_tool_batch,
    permission_request,
    notification,
    stop,
    user_prompt_submit,
)

# maps the CLI sub-name to its main() entrypoint
HANDLERS = {
    "post-tool-use": post_tool_use.main,
    "post-tool-batch": post_tool_batch.main,
    "permission-request": permission_request.main,
    "notification": notification.main,
    "stop": stop.main,
    "user-prompt-submit": user_prompt_submit.main,
}

__all__ = ["HANDLERS"]
