---
name: cache
description: |
  Semantic command caching for faster repeat requests. When you ask for something
  similar to a previous request, nlsh can skip the LLM and reuse the cached command.
  Uses embeddings to match similar requests.
active_when: CACHE_AVAILABLE
---

# Semantic Command Cache

Skip LLM processing for repeated or similar requests using semantic similarity.

## How It Works

1. **First request**: LLM generates command, result is cached with embeddings
2. **Similar request**: Embeddings are compared to find matches
3. **High match (99%+)**: Use cached command directly
4. **Medium match (85-99%)**: LLM validates if cache is appropriate
5. **Low match (<85%)**: Generate new command

## Cache Indicators

When you see these messages:
- `cached` - Using previously cached command (fast path)
- `(cached for future use)` - New command stored in cache

## Cache Location

- Local cache: `~/.nlsh/cache/commands.db`
- Remote cache: Stored on server by command UUID

## Tips

- Similar phrasing = faster responses
- Use consistent terminology for common tasks
- Cache survives session restarts
- First run of a new command type will be slower

## When Cache Skips

Cache won't match when:
- Request is significantly different semantically
- Context has changed (different directory, files)
- You explicitly want a fresh response

## Example Flow

```
> list python files          # First time: LLM generates, cached
> show me python files       # Similar: cache hit, instant
> find all .py files here    # Similar enough: validates, then uses cache
> delete python files        # Different intent: new LLM call
```
