# translate-epub — Provider + config abstraction

Bu sürümde AI provider katmanı ve uygulama ayarları ana çeviri motorundan ayrılmıştır.

Desteklenen provider'lar:

- OpenRouter
- OpenAI
- DeepSeek
- Google Gemini (OpenAI compatibility endpoint)
- Ollama (local OpenAI compatibility endpoint)

## Yapı

```text
translate-epub/
├── translate_epub.py
├── requirements.txt
├── models/
│   ├── __init__.py
│   └── config.py
└── providers/
    ├── __init__.py
    ├── base.py
    ├── factory.py
    └── openai_compatible.py
```

## Config katmanı

`models/config.py` iki ana model içerir:

- `ProviderConfig`: provider adı, model, API key environment variable, base URL ve timeout.
- `TranslationConfig`: EPUB yolu, hedef dil, worker sayısı, max output tokens, temperature, retry sayısı ve `ProviderConfig`.

CLI yalnızca argümanları okur ve bunları `TranslationConfig` nesnesine dönüştürür. Çeviri motoru bundan sonra ayarları `argparse.Namespace` üzerinden değil config modeli üzerinden kullanır. Bu yapı daha sonra GUI'nin aynı config modelini doğrudan oluşturmasına izin verir.

Örnek programatik kullanım:

```python
from pathlib import Path
from models import ProviderConfig, TranslationConfig

config = TranslationConfig(
    input_epub=Path("book.epub"),
    target_language="Turkish",
    workers=2,
    max_tokens=8192,
    temperature=0.2,
    retries=3,
    provider=ProviderConfig(
        name="ollama",
        model="qwen3:8b",
        base_url="http://localhost:11434/v1/",
        timeout=300,
    ),
)
```

## API key environment variables

- OpenRouter: `OPENROUTER_API_KEY`
- OpenAI: `OPENAI_API_KEY`
- DeepSeek: `DEEPSEEK_API_KEY`
- Google Gemini: `GEMINI_API_KEY`
- Ollama: API key gerekmez

## Kurulum

```bash
pip install -r requirements.txt
```

veya uv ile:

```bash
uv pip install -r requirements.txt
```

## Örnekler

```bash
python translate_epub.py book.epub --provider openrouter --model deepseek/deepseek-v4-flash
python translate_epub.py book.epub --provider openai --model gpt-5
python translate_epub.py book.epub --provider deepseek --model deepseek-v4-flash
python translate_epub.py book.epub --provider google --model gemini-3.6-flash
python translate_epub.py book.epub --provider ollama --model llama3.2 --workers 1 --max-tokens 8192
```

Provider'ın sunduğu modelleri listelemek için:

```bash
python translate_epub.py --provider ollama --list-models
python translate_epub.py --provider google --list-models
```

Remote/custom Ollama örneği:

```bash
python translate_epub.py book.epub --provider ollama --base-url http://192.168.1.50:11434/v1/ --model llama3.2
```
