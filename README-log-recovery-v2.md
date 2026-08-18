# Log-driven translation recovery v2

This patch is based on real translation logs with repeated omitted segment IDs,
missing `translations` wrappers, source==target glossary retries, and failures
that reached 1-2 segments.

Changes:

- Structured requests are proactively capped at 24 segments.
- Structural failures split immediately instead of resending the same malformed
  payload twice before splitting.
- A single remaining segment uses a plain-text translation fallback. The known
  segment ID is reattached locally, so the model no longer needs to reproduce
  JSON at the terminal recovery stage.
- Direct JSON maps such as `{ "s1": "..." }` are accepted when their keys are
  exactly expected segment IDs, even if the model omitted the `translations`
  wrapper.
- Source==target glossary entries such as `SAT => SAT`, `Pop => Pop`, and
  `The Beatles => The Beatles` remain strong preservation instructions in the
  prompt but no longer trigger costly exact-output compliance retries.

Run tests with:

    PYTHONPATH=. pytest -q

Current result: 22 passed.
