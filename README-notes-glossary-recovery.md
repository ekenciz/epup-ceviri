# Notes / Glossary Recovery Patch

This patch improves translation reliability for note-heavy XHTML files.

## Changes

- Translation requests are proactively split when a chunk contains more than 64 text segments.
- Back-to-back JSON objects are recovered and merged instead of failing with `Extra data`.
- Glossary compliance is checked against the specific source segments where the term occurs.
- A glossary miss triggers normal retries, but after the final retry an otherwise valid translation is accepted with a warning instead of failing the entire XHTML file.
- Structural JSON failures continue to use adaptive recursive chunk splitting.

## Expected log examples

```
↳ 51_Notes.xhtml: chunk 1 has 212 segments; pre-splitting before request (recovery depth 1).
⚠️ 51_Notes.xhtml: accepting valid translation after glossary retries: Glossary terms were not respected: Conservative Party => Muhafazakâr Parti
```

The glossary is still injected as mandatory terminology in the prompt. The final fallback only prevents a single stubborn term from discarding a complete translated file.
