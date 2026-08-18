# Automatic Glossary / Book Analysis

This version adds a provider-neutral Book Analysis stage that can generate a glossary before translation.

## What it does

1. Opens the EPUB without changing it.
2. Reads XHTML/HTML/NCX text through the same safe text-node parser used by translation.
3. Builds analysis chunks from the book text.
4. Sends each chunk to the selected AI provider with a terminology-analysis prompt.
5. Collects candidate characters, places, organizations, titles, fictional terms, objects, species, and other consistency-sensitive terminology.
6. Filters candidates by confidence, merges repeated suggestions, resolves conflicting targets, and limits the final glossary size.
7. Saves the result in the existing glossary JSON format.

Generated entries may also contain:

- `category`
- `confidence`
- `note`

These fields are optional and remain compatible with manually-created glossaries.

## Generate glossary only

```bash
python translate_epub.py book.epub \
  --provider ollama \
  --model qwen3:8b \
  --target Turkish \
  --analyze-book
```

Default output:

```text
book-glossary.json
```

Custom output:

```bash
python translate_epub.py book.epub \
  --provider ollama \
  --model qwen3:8b \
  --analyze-book \
  --analysis-output my-glossary.json
```

## Generate glossary and translate immediately

```bash
python translate_epub.py book.epub \
  --provider ollama \
  --model qwen3:8b \
  --target Turkish \
  --auto-glossary \
  --workers 1
```

The generated glossary is saved and then injected into translation chunks using the existing relevant-term matching system.

## Merge with an existing manual glossary

```bash
python translate_epub.py book.epub \
  --provider openai \
  --model gpt-5 \
  --glossary manual-glossary.json \
  --auto-glossary \
  --analysis-output combined-glossary.json
```

Manual glossary decisions win when the generated glossary proposes a different target for the same source term.

## Analysis tuning

```text
--analysis-chunk-tokens 6000
--analysis-max-tokens 4000
--analysis-max-terms 250
--analysis-min-confidence 0.65
--analysis-temperature 0.1
```

`--analysis-chunk-tokens` controls approximate input size per analysis request.

`--analysis-max-terms` limits the final generated glossary.

`--analysis-min-confidence` discards low-confidence model suggestions before the glossary is saved.

## Recommended workflow

For the future GUI, the intended workflow is:

```text
Select EPUB
    -> Analyze Book
    -> Review/Edit generated glossary
    -> Save glossary
    -> Start Translation
```

The backend now supports that flow without depending on CLI code.

## Truncated / invalid JSON recovery

Book Analysis now treats unterminated JSON responses as a likely output-limit problem.
It automatically retries with a smaller glossary-entry limit and more compact output
instructions. If the response is still invalid after the configured retries, only the
problematic analysis chunk is split into smaller chunks and retried recursively. This
prevents one dense chapter from aborting the entire book analysis.
