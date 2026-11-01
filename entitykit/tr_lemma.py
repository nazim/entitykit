"""
tr_lemma.py — Türkçe lemmatizasyon yardımcı (engine: zeyrek / Zemberek)

entitykit'in çekim-eki sorununu çözer: "Otele/otelde/oteli/otelin" → "otel",
özel isimleri (Kapadokya, Göreme) bozMADAN. entity KEY'i ve Wikidata arama terimi
bununla üretilir; GÖSTERİLEN yüzey orijinal kalır.

Tek nokta: zeyrek init yavaş + gürültülü; singleton + log susturma + cache ile sarılı.
zeyrek yoksa kibarca norm'a düşer (degrade, çökmez).
"""
import io, logging, os, re
from contextlib import redirect_stdout

# zeyrek'in DEBUG gürültüsünü ("APPENDING RESULT…") sustur
for _n in ("zeyrek", "zeyrek.morphology", "zeyrek.attributes",
           "zeyrek.rulebasedanalyzer", "trnltk"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)

_WORD = re.compile(r"\w+", re.UNICODE)
_analyzer = None
_failed = False
_cache = {}

def _ensure_punkt():
    """zeyrek, lemmatize sırasında NLTK punkt_tab verisini ister; yoksa bir kez indir."""
    import nltk
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        if not nltk.download("punkt_tab", quiet=True):
            raise

def _get():
    global _analyzer, _failed
    if _analyzer is None and not _failed:
        try:
            import zeyrek
            _ensure_punkt()
            with redirect_stdout(io.StringIO()):
                _analyzer = zeyrek.MorphAnalyzer()
        except Exception:
            _failed = True
    return _analyzer

def available():
    return _get() is not None

def lemma_word(w):
    if w in _cache:
        return _cache[w]
    a = _get()
    lem = w
    if a is not None:
        try:
            with redirect_stdout(io.StringIO()):
                res = a.lemmatize(w)
            if res and res[0][1]:
                lem = res[0][1][0]
        except Exception:
            lem = w
    _cache[w] = lem
    return lem

def lemmatize_phrase(text):
    """Çok kelimeli yüzeyi kelime kelime lemma'la, boşlukla birleştir."""
    toks = _WORD.findall(text)
    if not toks:
        return text
    return " ".join(lemma_word(t) for t in toks)
