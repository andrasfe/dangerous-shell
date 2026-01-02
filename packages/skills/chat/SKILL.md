---
name: chat
description: |
  Conversational mode for questions and explanations without executing
  commands. Use the ? prefix to ask questions about your system, get
  explanations, or have a discussion.
active_when: always
---

# Chat Mode

Ask questions and have conversations without executing commands.

## How to Use

Prefix your message with `?`:
```
?what does the -R flag do in chmod?
?explain this error message
?how do I find large files?
?what's the difference between apt and apt-get?
```

## When to Use Chat Mode

- **Learning**: Ask about command syntax or flags
- **Debugging**: Get explanations of error messages
- **Planning**: Discuss approach before executing
- **Context**: Understand what a command or file does

## Example Questions

**Command explanations:**
```
?what does `find . -name "*.log" -mtime +7 -delete` do?
?explain the tar command flags
```

**System questions:**
```
?how much RAM does this system have?
?what services are running?
```

**Troubleshooting:**
```
?why might my SSH connection be timing out?
?what causes "permission denied" errors?
```

**Planning:**
```
?how should I structure a backup script?
?what's the best way to monitor disk usage?
```

## Chat vs Natural Language Mode

| Feature | Chat (`?`) | Natural Language |
|---------|------------|------------------|
| Executes commands | No | Yes |
| Answers questions | Yes | Yes (but may execute) |
| Conversation context | Yes | Yes |
| Safe for exploration | Very | Requires confirmation |

## Tips

- Chat maintains conversation context
- Responses are concise (CLI-friendly)
- Great for learning shell commands
- No confirmation prompts in chat mode
