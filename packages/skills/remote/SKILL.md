---
name: remote
description: |
  Guidance for nlsh remote mode (--remote flag). Use when commands execute on
  a remote server via SSH tunnel. Teaches: (1) Commands run on REMOTE not local,
  (2) Use upload_file for local-to-remote file transfers (not scp/rsync),
  (3) Use download_file for remote-to-local transfers, (4) Local env vars like
  NLSH_REMOTE_HOST are unavailable on remote.
---

# Remote Mode Operations

In remote mode, shell commands execute on the REMOTE server, not locally.

## File Transfer Rules

| Transfer Direction | Tool to Use | Example |
|-------------------|-------------|---------|
| LOCAL -> REMOTE | `upload_file` | `upload_file("~/.ssh/key.pub", "~/.ssh/authorized_keys")` |
| REMOTE -> LOCAL | `download_file` | `download_file("/var/log/app.log", "./app.log")` |
| REMOTE -> REMOTE | `run_shell_command` | `run_shell_command("cp ~/a.txt ~/b.txt")` |

## Common Mistakes

**Wrong** - Running scp inside remote shell:
```
run_shell_command("scp ~/.nlsh/keys/mcp.key user@remote:~/")
# Fails: ~/.nlsh/keys/ exists on LOCAL, not on the remote where this runs
```

**Right** - Use upload_file:
```
upload_file("~/.nlsh/keys/mcp.key", "~/mcp.key")
```

## Path Context

- Paths like `~/.nlsh/`, `~/.ssh/` in user requests typically refer to LOCAL
- When user says "copy X to the server", X is LOCAL
- When user says "download X from the server", X is REMOTE
- `run_shell_command("pwd")` shows REMOTE cwd, not local

## Environment Variables

LOCAL-only variables (not available on remote):
- `NLSH_REMOTE_HOST`
- `NLSH_REMOTE_USER`
- `NLSH_SHARED_SECRET`
- `NLSH_REMOTE_PORT`

Query remote environment with: `run_shell_command("env")`
