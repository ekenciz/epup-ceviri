# Glossary layer

This version adds a reusable glossary model, JSON import/export, per-chunk term selection, and optional strict glossary enforcement.

## Glossary JSON

Use `glossary.example.json` as a starting point:

```json
{
  "version": 1,
  "entries": [
    {
      "source": "The Watcher",
      "target": "Gözcü",
      "note": "Character title",
      "case_sensitive": false,
      "whole_word": true
    }
  ]
}
```

Fields:
- `source`: source-language term.
- `target`: required/preferred translation.
- `note`: optional context for the model.
- `case_sensitive`: whether source matching respects case.
- `whole_word`: prevents partial matches such as `art` inside `earth`.

The code also accepts a plain JSON array of entries for convenience.

## CLI usage

```bash
python translate_epub.py book.epub \
  --provider ollama \
  --model qwen3:8b \
  --glossary glossary.json \
  --workers 1 \
  --chunk-tokens 4000
```

With a glossary, strict enforcement is enabled by default. Only entries actually found in a chunk are sent to the model.

To provide glossary terms as preferences without post-response enforcement:

```bash
python translate_epub.py book.epub \
  --provider ollama \
  --model qwen3:8b \
  --glossary glossary.json \
  --no-enforce-glossary
```

## Python API

```python
from core import Glossary, GlossaryEntry

# Create / export
terms = Glossary([
    GlossaryEntry("The Watcher", "Gözcü", note="Character title"),
    GlossaryEntry("Maester", "Üstat"),
])
terms.save_json("glossary.json")

# Import
terms = Glossary.load_json("glossary.json")

# Find entries relevant to one chunk
relevant = terms.relevant_entries([
    "The Watcher entered the hall.",
    "A Maester greeted him.",
])
```

## Enforcement behavior

When strict enforcement is active:
1. Matching glossary entries are appended to the system prompt for that chunk.
2. They are marked as mandatory terminology.
3. After the model returns valid segment JSON, the translated chunk is checked for the required target terms.
4. If a required target term is absent, that chunk is retried using the normal retry policy.

This is deliberately a terminology consistency check, not a semantic proof. For terms with multiple meanings, use the optional `note` field or disable strict enforcement.
