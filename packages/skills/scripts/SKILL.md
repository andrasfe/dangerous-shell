---
name: scripts
description: |
  Shell script generation and execution. When a task requires multiple commands
  or complex logic, create a shell script instead of running commands one by one.
  Scripts are shown for review before execution and errors trigger automatic fixes.
active_when: always
---

# Shell Script Execution

For complex tasks, generate and execute shell scripts instead of individual commands.

## When to Use Scripts

Use `run_script` instead of `run_shell_command` when:
- Task requires multiple sequential commands
- Logic needs conditionals (if/then) or loops
- Error handling between steps is needed
- Task would benefit from variables or functions
- User explicitly asks for a script

## Script Tool Usage

```
run_script(
    script="#!/bin/bash\nset -e\necho 'Starting...'\n...",
    explanation="What this script accomplishes",
    script_name="optional_name.sh"
)
```

## Script Best Practices

1. **Always use shebang**: Start with `#!/bin/bash` or `#!/bin/sh`
2. **Use set -e**: Exit on first error for safety
3. **Add comments**: Explain complex sections
4. **Use variables**: For paths and repeated values
5. **Quote variables**: Use `"$VAR"` not `$VAR`

## Remote Mode Behavior

In remote mode:
- Script is uploaded to remote `/tmp/` directory
- Executed with appropriate permissions
- Errors are returned for analysis
- Script is cleaned up after execution

## Error Handling

When a script fails:
1. Full stderr is captured and displayed
2. LLM analyzes the failure point
3. Offers to generate a fixed version
4. User can approve, edit, or provide feedback

## Example Script Structure

```bash
#!/bin/bash
set -e  # Exit on error

# Configuration
BACKUP_DIR="/tmp/backup_$(date +%Y%m%d)"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Perform backup
echo "Backing up to $BACKUP_DIR..."
cp -r ~/important/* "$BACKUP_DIR/"

# Verify
ls -la "$BACKUP_DIR"
echo "Backup complete!"
```
