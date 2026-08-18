# DeepSeek empty-response recovery

This patch hardens DeepSeek V4 usage for structured Book Analysis and translation.

## What changed

- DeepSeek V4 requests explicitly disable thinking mode for structured translation/analysis work.
- JSON-oriented prompts use DeepSeek JSON Output (`response_format={"type":"json_object"}`).
- If DeepSeek returns empty JSON-mode content, the provider retries once without `response_format`, while keeping thinking disabled and the prompt's JSON-only requirement.
- Book Analysis treats empty provider responses as recoverable, reducing requested glossary candidates and retrying; if needed, its existing chunk splitting can take over.
- Translation recovery also classifies empty responses / `finish_reason=length` as structural failures eligible for adaptive splitting.

## Recommended DeepSeek settings

- Model: `deepseek-v4-flash`
- Book Analysis max output: 4000-8000
- Analysis chunk tokens: 4000-6000
- Translation chunk tokens: 2000-3000 to start

The provider reports `finish_reason` in empty-response errors when available, which makes future diagnostics easier.
