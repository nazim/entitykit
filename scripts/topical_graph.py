#!/usr/bin/env python3
"""
topical_graph.py — topical authority haritası (GLiNER + networkx)

İçerik kümesinin varlık eş-geçiş grafiğini kurar; PageRank ile konunun sütun
varlıklarını bulur. --target ile bir sayfanın kapsama boşluğu. Detay ve
sınırlar için README ve SKILL.md.

  python topical_graph.py --files "site/*.txt"
  python topical_graph.py --urls urls.txt --target taslak.txt
"""
import argparse, glob, html as _html, os, re, sys, unicodedata
import urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr_lemma   # Türkçe lemmatizasyon (çekim eki → kök); yoksa norm'a düşer
# kelime-sınırlı eşleşme yardımcıları tek yerde dursun (karakter içerme hatası
# entity_salience'ta düzeltildi; burada da aynısı kullanılır)
from entity_salience import (lemma_tokens, in_raw_text, key_match,
                             main_content, LABEL_PRESETS)

NER_MODEL = "urchade/gliner_multiv2.1"
NER_THRESH = 0.45
CHUNK_WORDS = 280
DEFAULT_LABELS = ["kişi", "kuruluş", "yer", "ürün", "hizmet", "marka",
                  "kavram", "etkinlik", "eser", "tarih", "meslek"]

def norm(s):
    s = s.replace("I", "ı").replace("İ", "i").lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s)
                if not unicodedata.combining(c))
    return s.strip()

SENT_RE = re.compile(r"(?<=[\.\!\?…])\s+|\n+")
def split_sentences(text):
    return [s.strip() for s in SENT_RE.split(text) if s.strip()] or [text.strip()]

def word_count(text):
    return len(re.findall(r"\w+", text, re.UNICODE))

# ---- IO ---------------------------------------------------------------------
def html_to_text(raw):
    raw = re.sub(r"(?is)<(script|style|noscript|template).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
    raw = re.sub(r"(?i)<(br|/p|/div|/h[1-6]|/li|/tr)\s*/?>", "\n", raw)
    txt = _html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", txt)).strip()

def fetch_url(url, timeout=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (entitykit/0.1 content-analysis research)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8",
                               errors="replace")

def load_docs(urls_arg, files_arg):
    docs = []
    if urls_arg:
        if os.path.isfile(urls_arg):
            urls = [l.strip() for l in open(urls_arg, encoding="utf-8")
                    if l.strip() and not l.startswith("#")]
        else:
            urls = [u.strip() for u in urls_arg.split(",") if u.strip()]
        for u in urls:
            try:
                docs.append((u, main_content(fetch_url(u))))
                print(f"  çekildi: {u}", file=sys.stderr)
            except Exception as e:
                print(f"  (uyarı: çekilemedi {u}: {e})", file=sys.stderr)
    if files_arg:
        for p in glob.glob(os.path.expanduser(files_arg)):
            with open(p, encoding="utf-8") as f:
                docs.append((os.path.basename(p), f.read()))
    return docs

# ---- GLiNER -----------------------------------------------------------------
def load_ner(name, device):
    from gliner import GLiNER
    import warnings; warnings.filterwarnings("ignore")
    m = GLiNER.from_pretrained(name)
    try: m = m.to(device)
    except Exception: pass
    return m

def chunk_spans(text, max_words=CHUNK_WORDS):
    sents, chunks, buf, words = split_sentences(text), [], [], 0
    for s in sents:
        wc = word_count(s)
        if words + wc > max_words and buf:
            chunks.append(" ".join(buf)); buf, words = [], 0
        buf.append(s); words += wc
    if buf: chunks.append(" ".join(buf))
    return chunks

def ent_key(surf, use_lemma):
    base = tr_lemma.lemmatize_phrase(surf) if use_lemma else surf
    return norm(base)

def doc_entities(ner, text, labels, threshold, use_lemma=True):
    """Bir dokümandaki tekil varlıkları (lemma-key -> en sık yüzey) döndür."""
    found, freq = {}, {}
    for chunk in chunk_spans(text):
        try:
            preds = ner.predict_entities(chunk, labels, threshold=threshold)
        except Exception:
            continue
        for p in preds:
            surf = p["text"].strip()
            k = ent_key(surf, use_lemma)
            if len(k) < 2:
                continue
            freq[(k, surf)] = freq.get((k, surf), 0) + 1
            # gösterilen yüzey = en sık geçen orijinal form
            if k not in found or freq[(k, surf)] > freq.get((k, found[k]), 0):
                found[k] = surf
    return found

# ---- Graf -------------------------------------------------------------------
def build_graph(per_doc):
    import networkx as nx
    from itertools import combinations
    G = nx.Graph()
    df = {}                         # document frequency
    canon = {}
    for ents in per_doc:
        keys = list(ents.keys())
        for k in keys:
            df[k] = df.get(k, 0) + 1
            canon[k] = ents[k]
        for a, b in combinations(sorted(set(keys)), 2):
            if G.has_edge(a, b):
                G[a][b]["w"] += 1
            else:
                G.add_edge(a, b, w=1)
    for k, c in canon.items():
        if k not in G:
            G.add_node(k)
        G.nodes[k]["df"] = df[k]
        G.nodes[k]["canon"] = c
    return G, df, canon

def report(G, df, canon, ndocs, target_ents, target_name, target_text, top,
           use_lemma=True):
    import networkx as nx
    pr = nx.pagerank(G, weight="w") if G.number_of_edges() else \
        {n: 1 / max(len(G), 1) for n in G}
    ranked = sorted(G.nodes, key=lambda n: -pr.get(n, 0))

    print("=" * 74)
    print(" entitykit — topical authority haritası  (GLiNER + networkx, VEKİL)")
    print("=" * 74)
    print(f" doküman : {ndocs}   varlık (düğüm): {G.number_of_nodes()}   "
          f"bağ (kenar): {G.number_of_edges()}")
    print("-" * 74)
    print(f" SÜTUN VARLIKLAR (PageRank otorite — konu bunların etrafında örülü)")
    print(f" {'rank':>5} {'df':>3} {'pr':>7}  varlık")
    for i, n in enumerate(ranked[:top], 1):
        print(f" {i:>5} {df.get(n,0):>3} {pr.get(n,0):.4f}  {canon.get(n,n)[:40]}")
    print("-" * 74)

    if target_ents is not None:
        tkeys = set(target_ents.keys())
        # TOKEN-set eşleşme ("otel" ⊆ {mağara,otel} => hedefte VAR) + ham metin
        # fallback'i kelime SINIRLI ve lemma'lı: "van" artık "vanilya"da bulunmaz,
        # "Göreme" "Göreme Belediyesi"ne yapışmaz.
        tokset, joined = lemma_tokens(target_text, use_lemma)
        gaps, raw_only = [], []
        for n in ranked:
            if df.get(n, 0) < 2:
                continue
            if key_match(n, tkeys):
                continue
            row = (n, df.get(n, 0), pr.get(n, 0))
            # üçüncü durum: kelime hedef metinde GEÇİYOR ama GLiNER varlık saymadı
            (raw_only if in_raw_text(n, tokset, joined) else gaps).append(row)
        print(f" KAPSAMA BOŞLUĞU — '{target_name}' sayfasında EKSİK otorite varlıklar")
        print(f" (korpusta ≥2 dokümanda geçen ama hedefte olmayanlar = içerik/link fırsatı)")
        if not gaps:
            print("   (belirgin boşluk yok — hedef korpus otoritesini iyi taşıyor)")
        for n, d, p in gaps[:top]:
            print(f"   ✗ {canon.get(n,n)[:34]:<34} df={d} pr={p:.4f}")
        if raw_only:
            print(" ○ metinde GEÇİYOR ama varlık tanınmadı (boşluk DEĞİL; label seti)")
            for n, d, p in raw_only[:top]:
                print(f"   ○ {canon.get(n,n)[:34]:<34} df={d} pr={p:.4f}")
        print("-" * 74)
    print(" NOT: PageRank otorite VEKİLİDİR — gerçek topical authority sıralaması")
    print("      değil; konunun varlık iskeletini gösterir. READ-ONLY teşhis;")
    print("      eksik varlık için içerik/link eklemek AYRI ve ONAYLI adımdır.")
    print("=" * 74)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", default=None, help="virgüllü URL VEYA satır-satır URL dosyası")
    ap.add_argument("--files", default=None, help="glob: yerel doküman dosyaları")
    ap.add_argument("--target", default=None,
                    help="kapsama boşluğu için hedef sayfa (dosya yolu VEYA URL)")
    ap.add_argument("--labels", default=None)
    ap.add_argument("--preset", default=None, choices=sorted(LABEL_PRESETS),
                    help="hazır label seti (--labels verilirse o ezer)")
    ap.add_argument("--threshold", type=float, default=NER_THRESH)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--no-lemma", action="store_true",
                    help="Türkçe lemmatizasyonu kapat (çekim eki birleştirmesi)")
    ap.add_argument("--ner-model", default=NER_MODEL)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()
    if not (args.urls or args.files):
        sys.exit("HATA: --urls veya --files ver.")
    labels = ([l.strip() for l in args.labels.split(",")] if args.labels
              else LABEL_PRESETS[args.preset] if args.preset
              else DEFAULT_LABELS)
    use_lemma = not args.no_lemma
    if use_lemma and not tr_lemma.available():
        print("  (uyarı: zeyrek yok, lemmatizasyon kapalı)", file=sys.stderr)
        use_lemma = False

    docs = load_docs(args.urls, args.files)
    if len(docs) < 2:
        print("UYARI: anlamlı graf için ≥2 doküman gerekir.", file=sys.stderr)
    ner = load_ner(args.ner_model, args.device)
    per_doc = [doc_entities(ner, txt, labels, args.threshold, use_lemma)
               for _, txt in docs]
    G, df, canon = build_graph(per_doc)

    target_ents, target_name, ttext = None, "", ""
    if args.target:
        if os.path.isfile(args.target):
            ttext = open(args.target, encoding="utf-8").read()
            target_name = os.path.basename(args.target)
        else:
            ttext = main_content(fetch_url(args.target)); target_name = args.target
        target_ents = doc_entities(ner, ttext, labels, args.threshold, use_lemma)

    if not G.number_of_nodes():
        print("Varlık bulunamadı."); return
    report(G, df, canon, len(docs), target_ents, target_name, ttext, args.top,
           use_lemma)

if __name__ == "__main__":
    main()
