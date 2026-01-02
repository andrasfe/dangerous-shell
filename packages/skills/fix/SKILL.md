---
name: fix
description: |
  Automatic error recovery and command fixing. When a command fails, nlsh
  analyzes the error output and suggests a corrected command. Supports
  feedback-driven refinement for iterative fixes.
active_when: always
---

# Error Recovery & Auto-Fix

When commands fail, nlsh can analyze the error and suggest fixes.

## How It Works

1. Command fails with non-zero exit code or error patterns
2. You're prompted: "Would you like me to try to fix this?"
3. LLM analyzes stderr and suggests corrected command
4. You can approve, edit, or provide feedback for another attempt

## Fix Prompt Options

| Key | Action |
|-----|--------|
| `y` | Run the suggested fix |
| `n` | Cancel, keep the failure |
| `e` | Edit the fix before running |
| `f` | Provide feedback for LLM to try again |

## Feedback Mode

When you choose `f`, describe what's wrong with the suggestion:
- "Use sudo instead"
- "Wrong directory, should be /opt/app"
- "Need to install the package first"

The LLM incorporates your feedback and suggests a new fix.

## Common Fix Patterns

| Error Type | Typical Fix |
|------------|-------------|
| Permission denied | Add sudo or fix permissions |
| Command not found | Install package or use full path |
| File not found | Correct path or create directory |
| Syntax error | Fix command syntax |
| Missing dependency | Install required package |

## Tips

- Error patterns in stderr are detected even with exit code 0
- Fixes are logged for history
- Multiple fix attempts allowed until success or cancel
- LLM has context of your original intent
