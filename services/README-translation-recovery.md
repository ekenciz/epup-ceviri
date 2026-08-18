# Adaptive Translation Recovery

Translation requests now recover automatically from malformed/truncated JSON and missing segment IDs.

## Behavior

For each translation chunk:

1. The normal request is sent.
2. On a structural response failure, a second request is sent with temperature 0 and stricter JSON-only instructions.
3. If the response is still malformed, missing IDs, inventing IDs, or contains empty translations, the chunk is split into smaller requests.
4. Splitting continues recursively (up to a safety depth) until the model can return complete JSON.
5. If a chunk contains only one long text segment, that text is temporarily split and the translated halves are rejoined under the original segment ID.

Typical GUI/terminal messages:

```text
ch04.xhtml: chunk 1 attempt 1/3 failed: Model returned invalid JSON...
ch04.xhtml: chunk 1 attempt 2/3 failed: Model returned invalid JSON...
ch04.xhtml: chunk 1 response is structurally invalid; splitting 58 segment(s) into 2 smaller request(s)...
```

This recovery applies to:

- malformed / truncated JSON
- omitted segment IDs
- invented segment IDs
- empty/non-string translations
- missing `translations` JSON object

Network/provider errors and glossary-compliance failures still use the normal retry behavior rather than being treated as a JSON-size problem.

For local Ollama models, starting with 1500-2500 input chunk tokens can still reduce latency and recovery requests, but adaptive splitting makes larger configured chunks much safer.
