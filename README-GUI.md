# Translate EPUB - PySide6 GUI

## What the first GUI version includes

- EPUB file picker
- Provider selection: OpenRouter, OpenAI, DeepSeek, Google Gemini, Ollama
- Editable model selector and **Refresh models** action
- Direct API-key input (kept in memory; not written to disk by the app)
- API-key environment variable and base-URL overrides
- Target language
- Parallel file count
- Translation chunk-token and max-output-token controls
- Temperature, retry and timeout controls
- Book Analysis settings
- Manual **Analyze Book** action
- Optional **Generate/merge glossary before translation** flow
- Glossary table editor
- Glossary JSON import/export
- Glossary enforcement toggle
- Translation progress, analysis progress and log view
- Safe cancellation request
- Per-book resume workspace

## Install

Create/activate your Python environment and run:

```bash
python -m pip install -r requirements.txt
```

With uv:

```bash
uv pip install -r requirements.txt
```

## Start the GUI

```bash
python gui_app.py
```

Windows users can also double-click `run_gui.bat` after dependencies are installed.
Linux/macOS users can run `./run_gui.sh` after making it executable if necessary.

## Typical Ollama flow

1. Start Ollama.
2. Open the GUI.
3. Select **Ollama**.
4. Press **Refresh models**.
5. Pick a local model.
6. Select an EPUB.
7. Optionally press **Analyze Book** and review/edit the generated glossary.
8. Press **Start Translation**.

For a local model, start with one parallel file. Increase it only if your hardware/model setup benefits from concurrent requests.

## Glossary behavior

The glossary table is backed by the existing `Glossary`/`GlossaryEntry` model. JSON import/export uses the same format as the CLI. If **Enforce glossary terminology** is enabled, a translation chunk that does not include required target terms is rejected and retried.

When **Analyze Book** is used, generated terms are merged with the current table. Current/manual entries win over generated entries on conflicts.

## Cancellation and resume

Cancel requests are cooperative: the application waits for an in-flight provider request to finish, then stops before the next safe unit of work. Completed files remain in a per-book workspace such as:

```text
.my-book.translate-epub-work/
```

Running the same book again resumes completed files. The workspace is removed after a fully successful packaging step.

## Notes

- The GUI uses `QThread` workers so network/model work does not run on the Qt UI thread.
- API keys entered in the GUI are passed to the provider in memory. This GUI does not persist them to a settings file.
- The CLI (`translate_epub.py`) is still available.
