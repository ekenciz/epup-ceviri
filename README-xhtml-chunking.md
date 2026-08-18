# XHTML parsing + chunking layer

Bu sürüm provider abstraction ve config layer üzerine XHTML/XML text-node parsing ve chunking ekler.

## Yeni akış

1. EPUB açılır.
2. `.xhtml`, `.html` ve `.ncx` dosyaları XML parser ile okunur.
3. `script`, `style`, `code`, `pre`, `svg` ve `math` altındaki içerikler çeviri dışında bırakılır.
4. Çevrilebilir text/tail düğümleri stabil segment ID'leri ile çıkarılır.
5. Segmentler yaklaşık token bütçesine göre chunk'lara ayrılır.
6. Modele XHTML yerine JSON segmentleri gönderilir.
7. Modelin döndürdüğü segment ID'leri doğrulanır.
8. Çeviriler orijinal DOM düğümlerine geri yerleştirilir.
9. XML/XHTML yeniden serialize edilip EPUB içine yazılır.

Bu yapı modelin `id`, `href`, `class`, `src` gibi markup/attribute alanlarını değiştirmesini önler; çünkü bu alanlar modele hiç gönderilmez.

> Not: lxml yeniden serialize ederken XML declaration tırnak biçimi veya bazı eşdeğer biçimsel ayrıntıları normalize edebilir. DOM yapısı ve attribute değerleri korunur; byte-for-byte dosya eşitliği hedeflenmez.

## Kurulum

```bash
pip install -r requirements.txt
```

veya:

```bash
uv pip install -r requirements.txt
```

Yeni bağımlılık: `lxml>=5.0.0`.

## Kullanım

Ollama örneği:

```bash
python translate_epub.py book.epub \
  --provider ollama \
  --model qwen3:8b \
  --workers 1 \
  --chunk-tokens 4000 \
  --max-tokens 12000
```

DeepSeek örneği:

```bash
python translate_epub.py book.epub \
  --provider deepseek \
  --model deepseek-v4-flash \
  --chunk-tokens 4000
```

## Token ayarları

- `--chunk-tokens`: bir AI isteğine gönderilecek yaklaşık maksimum input token bütçesi.
- `--max-tokens`: provider'ın tek chunk için üretebileceği maksimum output token sayısı.

Tokenizer modeller arasında farklı olduğu için `--chunk-tokens` şimdilik sağlayıcıdan bağımsız, konservatif bir tahmin kullanır. İleride provider/model-specific tokenizer eklenebilir.

## Glossary için hazırlık

Her chunk artık şu tür bir yapı taşır:

```json
{
  "segments": [
    {"id": "s000001", "text": "The Watcher entered the room."},
    {"id": "s000002", "text": "He closed the door."}
  ]
}
```

Bir sonraki glossary katmanı chunk içindeki metinlerde eşleşen terimleri bulup yalnızca ilgili glossary maddelerini prompt'a ekleyebilir.
