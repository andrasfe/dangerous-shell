---
name: scripting
description: |
  Multi-line shell script generation and execution. Use when the user's request
  requires multiple sequential commands, loops, conditionals, error handling,
  or atomic all-or-nothing execution. Use run_shell_script tool instead of
  run_shell_command when tasks involve 3+ steps or shared state between commands.
---

# Shell Script Generation Guidelines

## When to Use Scripts vs Single Commands

**Use `run_shell_script` when:**
- Task requires 3+ sequential commands
- Commands share state (variables, directory context)
- Error handling is needed across steps
- Loops or conditionals are required
- User explicitly asks for "a script" or "automation"
- Operation should be atomic (all-or-nothing)

**Use `run_shell_command` when:**
- Single operation
- Quick one-liner
- No error handling needed
- Interactive feedback expected after each step

## Script Structure Requirements

Every generated script MUST follow this structure:

```bash
#!/usr/bin/env bash
set -euo pipefail  # Exit on error, undefined vars, pipe failures
trap 'echo "Error on line $LINENO"; exit 1' ERR

# === Script: {{name}} ===
# Description: {{explanation}}

# --- Configuration ---
VAR="${VAR:-default_value}"

# --- Functions ---
log() { echo "[$(date +'%H:%M:%S')] $*"; }
error() { echo "[ERROR] $*" >&2; }

# --- Main ---
log "[Step 1/N] Description..."
# commands here

log "[Step 2/N] Description..."
# more commands

log "✓ Complete"
```

## Required Patterns

### Error Handling
```bash
set -euo pipefail
trap 'echo "Error on line $LINENO"; exit 1' ERR
```

### Progress Logging
Use step markers for progress tracking:
```bash
log "[Step 1/3] Installing dependencies..."
log "[Step 2/3] Building project..."
log "[Step 3/3] Running tests..."
```

### Safe Variable Defaults
```bash
TARGET_DIR="${TARGET_DIR:-./deploy}"
BACKUP_COUNT="${BACKUP_COUNT:-5}"
```

### Existence Checks
```bash
command -v docker >/dev/null 2>&1 || { error "docker required"; exit 1; }
[[ -d "$DIR" ]] || { error "Directory not found: $DIR"; exit 1; }
```

### Cleanup on Error
```bash
cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT
```

## Common Patterns

### File Processing Loop
```bash
for file in *.log; do
    [[ -f "$file" ]] || continue
    log "Processing: $file"
    process_file "$file"
done
```

### Backup Before Modify
```bash
BACKUP="$FILE.backup.$(date +%Y%m%d)"
cp "$FILE" "$BACKUP"
# ... modify file
```

### Safe Delete with Confirmation
```bash
if [[ -d "$DIR" ]]; then
    log "Removing: $DIR"
    rm -rf "$DIR"
fi
```

## Risk Level Guidelines

When generating scripts, assess risk level:

- **safe**: Read operations, file creation, package installations
- **moderate**: File modifications, network operations, config changes
- **dangerous**: Deletions, system modifications, sudo operations

## Example: Deployment Script

User: "Deploy my Node.js app to production"

```bash
#!/usr/bin/env bash
set -euo pipefail
trap 'echo "Error on line $LINENO"; exit 1' ERR

# === Script: deploy-nodejs ===
# Description: Deploy Node.js application to production

# --- Configuration ---
APP_DIR="${APP_DIR:-./app}"
DEPLOY_DIR="${DEPLOY_DIR:-/var/www/app}"
BACKUP_DIR="${BACKUP_DIR:-/var/www/backups}"

# --- Functions ---
log() { echo "[$(date +'%H:%M:%S')] $*"; }
error() { echo "[ERROR] $*" >&2; }

# --- Main ---
log "[Step 1/4] Creating backup..."
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
cp -r "$DEPLOY_DIR" "$BACKUP_DIR/app_$TIMESTAMP"

log "[Step 2/4] Installing dependencies..."
cd "$APP_DIR"
npm ci --production

log "[Step 3/4] Building application..."
npm run build

log "[Step 4/4] Deploying to production..."
rsync -av --delete dist/ "$DEPLOY_DIR/"

log "✓ Deployment complete"
```

## Important Notes

1. Always quote variables: `"$VAR"` not `$VAR`
2. Use `[[` for tests, not `[`
3. Prefer `$(command)` over backticks
4. Check command existence before using
5. Clean up temporary files
6. Log progress for user visibility
