# hello-project (claugram sample)

A tiny throwaway project used to verify claugram end-to-end **without a real
Telegram bot**. The verification harness (`samples/verify_live.py`) copies this
directory to a temp working dir, runs `claugram init --transport fake`, then
drives real Claude Code sessions through the controller and hooks while a
`FakeTransport` stands in for Telegram.

Nothing here talks to the network except the `claude` CLI itself.
