---
name: direct
description: |
  Bypass LLM processing for direct command execution. Use the ! prefix for
  one-off commands or toggle with // for a full direct-mode session. Useful
  when you know exactly what command to run.
active_when: always
---

# Direct Mode

Execute shell commands without LLM processing when you know exactly what to run.

## Two Ways to Use

### 1. Single Command Prefix: `!`
```
!ls -la              # Direct execution, back to NL mode
!git status          # Quick check, no LLM overhead
!docker ps           # Immediate result
```

### 2. Toggle Mode: `//` or `/llm`
```
//                   # Toggle LLM off -> direct mode
$ ls -la             # Prompt changes to $, commands run directly
$ pwd
//                   # Toggle LLM back on
nlsh:~$              # Back to natural language mode
```

## When to Use Direct Mode

- **Known commands**: You know the exact syntax
- **Quick checks**: `git status`, `ls`, `pwd`
- **Speed**: Skip LLM latency for simple commands
- **Precision**: Complex piped commands you've crafted
- **Scripting**: Running a series of known commands

## Prompt Indicator

| Mode | Prompt looks like |
|------|-------------------|
| NL mode | `nlsh:~/path$` |
| Direct mode | `$:~/path$` |
| Remote + NL | `nlsh[remote]:~$` |
| Remote + Direct | `$[remote]:~$` |

## Features Still Available in Direct Mode

- `cd` navigation works
- History is recorded
- Remote mode works (`--remote` flag)
- Password prompts handled interactively

## Tips

- Use `!` for occasional direct commands
- Use `//` when doing a batch of known commands
- LLM detection still works: if you type a command in NL mode, it asks if you want to run it directly
