---
name: voice
description: |
  Voice input for natural language commands. Press 'v' to record audio,
  speak your request, then press Enter. Transcription is handled by Gemini.
  Requires sounddevice and numpy packages.
active_when: AUDIO_AVAILABLE
---

# Voice Input

Speak commands instead of typing. Ideal for complex requests or when hands are busy.

## How to Use

1. Type `v` and press Enter to start recording
2. Speak your command clearly
3. Press Enter to stop recording
4. Review the transcription and confirm

## Tips for Best Results

- Speak clearly and at a normal pace
- Use natural language ("show me all Python files" not "ls *.py")
- Pause briefly before speaking
- Minimize background noise
- Keep commands concise (under 15 seconds works best)

## Example Phrases

- "List all files modified today"
- "Find large files over 100 megabytes"
- "Show the last 50 lines of the error log"
- "Create a backup of the config directory"
- "What's using the most disk space?"

## Requirements

```bash
pip install sounddevice numpy
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No audio recorded | Check microphone permissions and device |
| "[unclear]" result | Speak louder or reduce background noise |
| Slow transcription | Network latency to Gemini API |
| Import error | Install: `pip install sounddevice numpy` |
