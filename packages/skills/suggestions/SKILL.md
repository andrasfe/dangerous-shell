---
name: suggestions
description: |
  Smart follow-up command suggestions after successful execution. Based on
  command output and context, nlsh may suggest a logical next step. Supports
  edit and feedback modes for refinement.
active_when: always
---

# Follow-up Suggestions

After a command succeeds, nlsh may suggest a logical next step.

## When Suggestions Appear

Suggestions are offered when:
- Command output indicates a clear next step
- The action is related to your original goal
- The suggested command is safe and non-destructive

## Suggestion Prompt Options

| Key | Action |
|-----|--------|
| `y` | Run the suggested command |
| `n` | Decline, return to prompt |
| `e` | Edit the suggestion before running |
| `f` | Provide feedback for a different suggestion |

## Example Flows

**Build -> Run**
```
> build the project
[Build succeeds]
Suggested next: ./target/release/myapp
Reason: Build completed, run the binary
```

**Clone -> Install**
```
> clone this repo
[Clone succeeds]
Suggested next: cd repo && npm install
Reason: Package.json found, install dependencies
```

**Git status -> Commit**
```
> check git status
[Shows modified files]
Suggested next: git add -A && git commit -m "..."
Reason: Changes ready to commit
```

## Suggestion Limits

- Only one follow-up per command (no infinite chains)
- User can always decline with 'n'
- Dangerous commands are not suggested
- Each suggestion requires confirmation

## Tips

- Declining a suggestion returns you to the prompt cleanly
- Edit mode lets you tweak the suggestion
- Feedback mode gets a completely new suggestion
