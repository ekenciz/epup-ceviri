Updated both documents for the new project name and repository:

* Project name: **epup-ceviri**
* Repository: **[https://github.com/ekenciz/epup-ceviri](https://github.com/ekenciz/epup-ceviri)**
* Original project credit: **[https://github.com/zakcali/translate-epub](https://github.com/zakcali/translate-epub)**

# epup-ceviri

**epup-ceviri** is a desktop and command-line application for translating EPUB books with local or cloud-based AI models.

It preserves the EPUB/XHTML structure while translating only human-readable text. The project includes provider abstraction, XHTML-aware chunking, automatic glossary generation, terminology consistency, adaptive recovery, a PySide6 graphical interface, resume support, and EPUB integrity validation.

Repository:

[https://github.com/ekenciz/epup-ceviri](https://github.com/ekenciz/epup-ceviri)

---

## Based on the Original `translate-epub` Project

This project was developed and significantly expanded based on the original **`translate-epub`** project created by **zakcali**.

Original repository:

[https://github.com/zakcali/translate-epub](https://github.com/zakcali/translate-epub)

The original project provided the foundation and core idea of extracting an EPUB, translating its contents with an AI model, and packaging it back into an EPUB file.

**epup-ceviri** extends that foundation with a modular architecture and many additional features, including:

* Multiple AI providers
* Local Ollama support
* Direct OpenAI, DeepSeek, Gemini, and OpenRouter support
* PySide6 desktop GUI
* XHTML-aware text extraction
* Token-aware chunking
* Automatic glossary generation
* Manual glossary editing
* Terminology enforcement
* Adaptive translation recovery
* Resume support
* Parallel processing
* EPUB integrity validation

Please also review and respect the license terms of the original project before redistributing modified versions.

---

# Features

## Multiple AI Providers

The translation engine is separated from individual AI providers.

Supported providers include:

* OpenAI
* DeepSeek
* Google Gemini
* OpenRouter
* Ollama

This makes it possible to switch between cloud APIs and completely local AI models without changing the translation engine.

---

## Local Translation with Ollama

Ollama can be used to translate books entirely on your own computer.

Example models may include:

```text
qwen3:8b
qwen3:14b
gemma3
llama
```

Available models depend on your local Ollama installation.

No API key is required when using Ollama.

---

# PySide6 Desktop Interface

`epup-ceviri` includes a PySide6 graphical user interface.

From the GUI you can:

* Select an EPUB file
* Select an AI provider
* Select or enter a model
* Refresh available Ollama models
* Enter an API key
* Configure a custom API base URL
* Select the target language
* Configure parallel workers
* Configure chunk token size
* Configure maximum output tokens
* Configure temperature
* Configure retries and timeout
* Run Book Analysis
* Generate an automatic glossary
* Edit glossary entries
* Import and export glossary JSON files
* Start translation
* Cancel a running job
* Monitor progress
* View recovery and error logs

Start the graphical interface with:

```bash
python gui_app.py
```

---

# XHTML-Aware Translation

The complete XHTML document is not sent directly to the AI model.

Instead, the application extracts only translatable text nodes.

```text
EPUB
 ↓
XHTML Parser
 ↓
Translatable Text Nodes
 ↓
Segments
 ↓
Chunks
 ↓
AI Translation
 ↓
Translated Segments
 ↓
Original XHTML DOM
 ↓
Translated EPUB
```

This prevents the AI model from modifying important EPUB structures such as:

```text
id
class
href
src
XHTML elements
CSS
image paths
navigation links
```

Content inside elements such as the following is excluded from translation by default:

```text
script
style
code
pre
svg
math
```

---

# Chunk-Based Translation

Long chapters are split into smaller translation requests.

Chunking takes approximate token size into account and also limits the number of structured segments sent in a single request.

For example:

```text
83 segments
 ↓
41 + 42
 ↓
smaller translation requests
```

This makes structured output significantly more reliable, especially with local models.

---

# Adaptive Translation Recovery

AI models do not always return perfect structured output.

`epup-ceviri` includes an adaptive recovery system for issues such as:

* Invalid JSON
* Truncated JSON
* Multiple JSON objects
* Missing segment IDs
* Invented segment IDs
* Empty translations
* Missing `translations` wrapper
* Empty model responses
* Output token truncation

Instead of failing the entire chapter, problematic chunks are automatically reduced.

```text
48 segments
 ↓
24 + 24
 ↓
12 + 12
 ↓
...
```

If structured JSON still fails for a single text segment, the application can fall back to plain-text translation.

```text
Single segment
 ↓
Plain-text translation
 ↓
Segment ID restored by the application
```

This prevents a single malformed model response from causing the entire book translation to fail.

---

# Glossary System

A glossary can be used to maintain terminology consistency throughout a book.

Example:

```json
{
  "version": 1,
  "entries": [
    {
      "source": "The Watcher",
      "target": "Gözcü",
      "category": "title",
      "note": "Recurring character title",
      "confidence": 1.0,
      "case_sensitive": false,
      "whole_word": true
    }
  ]
}
```

Only glossary entries relevant to the current translation chunk are sent to the model.

For example, if a chunk contains:

```text
The Watcher entered Winterfell.
```

only matching glossary entries may be included:

```text
The Watcher => Gözcü
Winterfell => Kışyarı
```

The rest of the glossary is omitted from that request.

This reduces token usage and gives relevant terminology stronger prompt priority.

---

# Automatic Glossary Generation — Book Analysis

Before translation, the application can analyze the EPUB and ask the selected AI model to identify important terminology.

Book Analysis can identify entries such as:

* Characters
* Places
* Organizations
* Titles
* Historical terms
* Technical terms
* Repeated concepts
* Special objects
* Species
* Book-specific expressions

Example generated entry:

```json
{
  "source": "Declaration of Independence",
  "target": "Bağımsızlık Bildirgesi",
  "category": "term",
  "confidence": 0.93
}
```

Generated glossary entries can be reviewed and edited in the GUI before translation starts.

If an automatically generated entry conflicts with a manually created glossary entry, the manual entry takes priority.

---

# Glossary Enforcement

Glossary entries can be treated as preferred or mandatory terminology.

For example:

```text
Global Warming => Küresel Isınma
China => Çin
Iraq => Irak
```

The translation system can retry when important glossary terminology is not respected.

Entries whose source and target are identical, such as:

```text
SAT => SAT
Pop => Pop
The Beatles => The Beatles
```

are treated as preservation instructions rather than strict translation checks, reducing unnecessary retries.

A valid translation is not discarded indefinitely because of one stubborn glossary mismatch.

---

# Resume Support

Completed files are recorded during translation.

Each EPUB uses its own workspace:

```text
.<book-name>.translate-epub-work/
```

If translation is interrupted, running the same book again can reuse completed work.

Example:

```text
Already completed: ch01.xhtml
Already completed: ch02.xhtml
```

Only incomplete or failed files need to be processed again.

---

# Parallel Processing

Multiple XHTML files can be processed in parallel.

The worker count can be configured in the GUI or command line.

For cloud providers, multiple workers may improve throughput.

For local Ollama models, starting with:

```text
Workers: 1
```

is recommended.

Higher values can be tested depending on available RAM, VRAM, CPU, and GPU capacity.

---

# EPUB Integrity Validation

After translation and packaging, the generated EPUB is automatically validated.

Checks include:

* ZIP integrity
* CRC errors
* `mimetype` existence
* `mimetype` ZIP ordering
* Uncompressed `mimetype`
* Correct `application/epub+zip` value
* `META-INF/container.xml`
* OPF/package document
* XML/XHTML parsing
* Manifest targets
* Spine references
* Internal `href` references
* Internal `src` references
* Fragment references
* Duplicate ZIP entries
* Invalid Windows path separators inside the EPUB archive

A successful result may look like:

```text
Packaging: book-translated.epub
Validating EPUB integrity...
EPUB VALID
Integrity validation passed
Done: book-translated.epub
```

If critical validation errors are found, the output EPUB and translation workspace are preserved for inspection.

---

# Project Structure

```text
epup-ceviri/
│
├── gui_app.py
├── translate_epub.py
├── requirements.txt
├── README.md
├── INSTALL.md
│
├── gui/
│   ├── __init__.py
│   └── main_window.py
│
├── core/
│   ├── xhtml.py
│   ├── chunker.py
│   ├── glossary.py
│   ├── book_analysis.py
│   └── epub_validator.py
│
├── models/
│   └── config.py
│
├── providers/
│   ├── base.py
│   ├── factory.py
│   └── openai_compatible.py
│
├── services/
│   └── job_runner.py
│
└── tests/
```

---

# Quick Start

Clone the repository:

```bash
git clone https://github.com/ekenciz/epup-ceviri.git
cd epup-ceviri
```

Create a virtual environment.

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Start the GUI:

```bash
python gui_app.py
```

For detailed setup instructions, see:

```text
INSTALL.md
```

---

# Ollama Quick Start

Install Ollama and download a model:

```bash
ollama pull qwen3:8b
```

Check installed models:

```bash
ollama list
```

Start `epup-ceviri`:

```bash
python gui_app.py
```

Then select:

```text
Provider: Ollama
```

and use:

```text
Refresh Models
```

to retrieve locally installed models.

A reasonable starting configuration is:

```text
Workers:            1
Chunk tokens:       2000–3000
Max output tokens:  8000–12000
Temperature:        0.1–0.2
```

---

# API Providers

Cloud providers can use API keys entered directly in the GUI or environment variables.

Supported environment variable names include:

```text
OPENAI_API_KEY
DEEPSEEK_API_KEY
GEMINI_API_KEY
OPENROUTER_API_KEY
```

API keys entered in the application are not written into EPUB or glossary files.

---

# Command-Line Usage

The GUI is optional.

Example using Ollama:

```bash
python translate_epub.py book.epub \
  --provider ollama \
  --model qwen3:8b \
  --target Turkish \
  --workers 1 \
  --chunk-tokens 2500
```

Book Analysis only:

```bash
python translate_epub.py book.epub \
  --provider ollama \
  --model qwen3:8b \
  --target Turkish \
  --analyze-book
```

Automatic glossary generation followed by translation:

```bash
python translate_epub.py book.epub \
  --provider ollama \
  --model qwen3:8b \
  --target Turkish \
  --auto-glossary
```

---

# Requirements

Typical dependencies include:

```text
Python 3.11+
PySide6
openai
lxml
```

See `requirements.txt` for the exact dependency list.

---

# Testing

Run the test suite with:

```bash
pytest
```

Contributions should ideally preserve existing provider, XHTML, glossary, recovery, Book Analysis, and EPUB validation tests.

---

# Important Notes

* AI-generated translations should be reviewed when translation accuracy is important.
* Automatic glossary results should ideally be reviewed before translating a complete book.
* Cloud AI providers may charge for API usage.
* Local model performance depends heavily on model size and available hardware.
* DRM removal is not part of this project.
* Only process books and documents you have the legal right to use and translate.

---

# Credits

`epup-ceviri` was developed on top of the original project:

**zakcali / translate-epub**

[https://github.com/zakcali/translate-epub](https://github.com/zakcali/translate-epub)

Thanks to the original author for the foundation and initial project concept.

The extended version available here is maintained as:

**ekenciz / epup-ceviri**

[https://github.com/ekenciz/epup-ceviri](https://github.com/ekenciz/epup-ceviri)

---

# Contributing

Bug reports, compatibility fixes, additional AI providers, EPUB improvements, translation-quality improvements, and UI enhancements are welcome.

Typical contribution workflow:

```bash
git clone https://github.com/ekenciz/epup-ceviri.git
cd epup-ceviri
```

Create a branch:

```bash
git checkout -b feature/my-improvement
```

Run tests before submitting a pull request:

```bash
pytest
```

---

# License

This project is derived from:

[https://github.com/zakcali/translate-epub](https://github.com/zakcali/translate-epub)

Before publishing or redistributing this repository, verify the license of the original project and ensure that this repository's license and attribution comply with its requirements.

# epup-ceviri — Installation Guide

This guide explains how to install and run **epup-ceviri** on Windows, Linux, and macOS.

Project repository:

[https://github.com/ekenciz/epup-ceviri](https://github.com/ekenciz/epup-ceviri)

This project was developed and expanded based on the original project:

[https://github.com/zakcali/translate-epub](https://github.com/zakcali/translate-epub)

---

# 1. Requirements

Recommended environment:

```text
Python 3.11 or newer
pip
Git
```

For local AI translation, you will also need:

```text
Ollama
```

Ollama is optional when using cloud providers such as OpenAI, DeepSeek, Google Gemini, or OpenRouter.

---

# 2. Clone the Repository

Open a terminal and run:

```bash
git clone https://github.com/ekenciz/epup-ceviri.git
cd epup-ceviri
```

Alternatively, download the repository from GitHub using:

```text
Code → Download ZIP
```

and extract the ZIP file.

---

# 3. Check Python

Run:

```bash
python --version
```

On Windows you can also use:

```powershell
py --version
```

You should see a supported Python version, for example:

```text
Python 3.12.x
```

---

# 4. Create a Virtual Environment

Using a virtual environment is recommended.

## Windows PowerShell

Create it:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.venv\Scripts\Activate.ps1
```

If PowerShell blocks script execution, you may temporarily allow scripts for the current terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then activate again:

```powershell
.venv\Scripts\Activate.ps1
```

## Windows Command Prompt

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

## Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

A successfully activated environment usually displays:

```text
(.venv)
```

at the beginning of the terminal prompt.

---

# 5. Install Dependencies

Upgrade pip:

```bash
python -m pip install --upgrade pip
```

Install the project dependencies:

```bash
python -m pip install -r requirements.txt
```

The application typically uses packages including:

```text
PySide6
openai
lxml
```

---

# 6. Start the Graphical Interface

From the project directory:

```bash
python gui_app.py
```

On Windows PowerShell:

```powershell
python gui_app.py
```

The **epup-ceviri** desktop window should open.

---

# 7. Install Ollama for Local Translation

Skip this section if you only plan to use cloud providers.

After installing Ollama, verify it with:

```bash
ollama --version
```

Download a model, for example:

```bash
ollama pull qwen3:8b
```

List available local models:

```bash
ollama list
```

If necessary, start the Ollama service:

```bash
ollama serve
```

The default Ollama server is typically available at:

```text
http://localhost:11434
```

---

# 8. Configure Ollama in epup-ceviri

Start the GUI:

```bash
python gui_app.py
```

Select:

```text
Provider: Ollama
```

Click:

```text
Refresh Models
```

Your locally installed models should appear in the model selector.

Select a model such as:

```text
qwen3:8b
```

Recommended initial settings:

```text
Workers:            1
Chunk tokens:       2000
Max output tokens:  8000–12000
Temperature:        0.1–0.2
Retries:            3
```

Larger values may work with more capable local models and stronger hardware.

---

# 9. Configure OpenAI

You can enter the API key directly in the GUI.

Alternatively, define an environment variable.

Windows PowerShell:

```powershell
$env:OPENAI_API_KEY="YOUR_API_KEY"
python gui_app.py
```

Linux/macOS:

```bash
export OPENAI_API_KEY="YOUR_API_KEY"
python gui_app.py
```

Then select:

```text
Provider: OpenAI
```

inside the application.

---

# 10. Configure DeepSeek

Windows PowerShell:

```powershell
$env:DEEPSEEK_API_KEY="YOUR_API_KEY"
python gui_app.py
```

Linux/macOS:

```bash
export DEEPSEEK_API_KEY="YOUR_API_KEY"
python gui_app.py
```

Inside the GUI select:

```text
Provider: DeepSeek
```

and choose or enter the desired DeepSeek model.

---

# 11. Configure Google Gemini

Windows PowerShell:

```powershell
$env:GEMINI_API_KEY="YOUR_API_KEY"
python gui_app.py
```

Linux/macOS:

```bash
export GEMINI_API_KEY="YOUR_API_KEY"
python gui_app.py
```

Then select the Google provider and an appropriate Gemini model.

---

# 12. Configure OpenRouter

Windows PowerShell:

```powershell
$env:OPENROUTER_API_KEY="YOUR_API_KEY"
python gui_app.py
```

Linux/macOS:

```bash
export OPENROUTER_API_KEY="YOUR_API_KEY"
python gui_app.py
```

Then select:

```text
Provider: OpenRouter
```

inside the GUI.

---

# 13. Translate Your First EPUB

Start:

```bash
python gui_app.py
```

Then:

1. Select an `.epub` file.
2. Select the target language.
3. Select the AI provider.
4. Select or enter the model.
5. Configure worker count.
6. Configure chunk token size.
7. Configure maximum output tokens.
8. Optionally load or generate a glossary.
9. Click **Start Translation**.

Progress and recovery information will appear in the log panel.

---

# 14. Generate a Glossary with Book Analysis

Select an EPUB and configure your AI provider.

Click:

```text
Analyze Book
```

The selected AI model will scan book text and suggest terminology.

Example:

```text
Declaration of Independence → Bağımsızlık Bildirgesi
Global Warming             → Küresel Isınma
Conservative Party         → Muhafazakâr Parti
```

Review the entries before starting translation.

You can modify or remove incorrect suggestions directly from the glossary editor.

---

# 15. Import and Export Glossaries

Glossaries can be saved as JSON.

Use:

```text
Export JSON
```

to save the current glossary.

Use:

```text
Import JSON
```

to load an existing glossary.

Example:

```json
{
  "version": 1,
  "entries": [
    {
      "source": "Global Warming",
      "target": "Küresel Isınma",
      "category": "term",
      "confidence": 1.0,
      "case_sensitive": false,
      "whole_word": true
    }
  ]
}
```

---

# 16. Resume an Interrupted Translation

During translation, completed files are stored in a book-specific workspace.

Example:

```text
.A.Land.for.the.Free.translate-epub-work/
```

If the process is interrupted, run the same EPUB again.

Previously completed files may be skipped:

```text
Already completed: ch01.xhtml
Already completed: ch02.xhtml
```

Only incomplete or failed files will need to be translated again.

Do not delete the workspace if you want to resume the previous job.

---

# 17. Output EPUB

A successfully translated book is normally created next to the source file.

For example:

```text
A.Land.for.the.Free.epub
```

becomes:

```text
A.Land.for.the.Free-translated.epub
```

---

# 18. EPUB Integrity Validation

After packaging, `epup-ceviri` validates the resulting EPUB.

A successful validation may look like:

```text
Packaging: A.Land.for.the.Free-translated.epub
Validating EPUB integrity...
EPUB VALID
Integrity validation passed
Done: A.Land.for.the.Free-translated.epub
```

Validation checks include EPUB archive structure, XHTML/XML parsing, manifest and spine consistency, and local resource references.

If critical validation errors occur, the generated EPUB and workspace are preserved for debugging.

---

# 19. Command-Line Usage

The graphical interface is optional.

Example with Ollama:

```bash
python translate_epub.py book.epub \
  --provider ollama \
  --model qwen3:8b \
  --target Turkish \
  --workers 1 \
  --chunk-tokens 2000
```

Run Book Analysis only:

```bash
python translate_epub.py book.epub \
  --provider ollama \
  --model qwen3:8b \
  --target Turkish \
  --analyze-book
```

Automatically generate a glossary and then translate:

```bash
python translate_epub.py book.epub \
  --provider ollama \
  --model qwen3:8b \
  --target Turkish \
  --auto-glossary
```

---

# 20. Troubleshooting

## `ModuleNotFoundError: No module named 'PySide6'`

Run:

```bash
python -m pip install -r requirements.txt
```

or:

```bash
python -m pip install PySide6
```

---

## `ModuleNotFoundError: No module named 'lxml'`

Run:

```bash
python -m pip install lxml
```

---

## `ModuleNotFoundError: No module named 'openai'`

Run:

```bash
python -m pip install openai
```

---

## Ollama Models Do Not Appear

Check:

```bash
ollama list
```

If the Ollama service is not running:

```bash
ollama serve
```

Make sure the Ollama base URL is configured correctly.

Typical value:

```text
http://localhost:11434
```

---

## Invalid JSON or Missing Segment IDs

`epup-ceviri` includes adaptive recovery for structured-output failures.

Large chunks are automatically split into smaller requests.

For example:

```text
24
 ↓
12 + 12
 ↓
6 + 6
```

If a single segment continues to fail with structured JSON, the application can fall back to plain-text translation.

For less capable local models, try:

```text
Workers:       1
Chunk tokens:  1500–2500
Temperature:   0.1
```

---

## Too Many Glossary Retries

Review the automatically generated glossary.

Avoid overly broad or ambiguous entries.

Terms such as:

```text
May
Right
Party
US
```

may match text in unintended contexts.

Very general terms are often better removed from strict glossary enforcement.

---

# 21. Update epup-ceviri

If you cloned the repository with Git:

```bash
git pull
```

Then update dependencies:

```bash
python -m pip install -r requirements.txt
```

---

# 22. Run Tests

From the project root:

```bash
pytest
```

This verifies the core parser, glossary, recovery, Book Analysis, provider, and EPUB validation behavior.

---

# 23. Original Project Credit

`epup-ceviri` is based on and extends:

**zakcali / translate-epub**

[https://github.com/zakcali/translate-epub](https://github.com/zakcali/translate-epub)

The current extended project is:

**ekenciz / epup-ceviri**

[https://github.com/ekenciz/epup-ceviri](https://github.com/ekenciz/epup-ceviri)

Please review the original project's license terms before publishing or redistributing derived versions.
