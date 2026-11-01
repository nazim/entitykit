#!/usr/bin/env python3
"""
topical_graph.py — topical authority haritası (GLiNER + networkx)

İçerik kümesinin varlık eş-geçiş grafiğini kurar; PageRank ile konunun sütun
varlıklarını bulur. --target ile bir sayfanın kapsama boşluğu. Detay ve
sınırlar için README ve SKILL.md.

  entitykit graph "site/*.txt"
  entitykit graph --urls urls.txt --target taslak.txt
"""
import argparse, os, sys
from . import tr_lemma   # Türkçe lemmatizasyon (çekim eki → kök); yoksa norm'a düşer
# ortak yardımcılar tek yerde: entity_salience
from .entity_salience import (DEFAULT_LABELS, LABEL_PRESETS, NER_MODEL,
                             NER_THRESH, chunk_spans, ent_key, fetch_url,
                             in_raw_text, key_match, lemma_tokens, load_ner,
                             load_sources)

def doc_entities(ner, text, labels, threshold, use_lemma=True):
    """Bir dokümandaki tekil varlıkları (lemma-key -> en sık yüzey) döndür."""
    found, freq = {}, {}
    for chunk, _ in chunk_spans(text):
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
    print(" entitykit — konu otoritesi haritası  (GLiNER + networkx, vekil ölçüm)")
    print("=" * 74)
    print(f" doküman : {ndocs}   varlık (düğüm): {G.number_of_nodes()}   "
          f"bağ (kenar): {G.number_of_edges()}")
    print("-" * 74)
    print(" SÜTUN VARLIKLAR (PageRank'e göre; konu bunların etrafında kurulu)")
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
        print(f" KAPSAMA BOŞLUĞU — '{target_name}' sayfasında eksik sütun varlıklar")
        print(" (en az 2 sayfada geçen, hedefte geçmeyen varlıklar: içerik ya da bağlantı fırsatı)")
        if not gaps:
            print("   (boşluk yok)")
        for n, d, p in gaps[:top]:
            print(f"   ✗ {canon.get(n,n)[:34]:<34} df={d} pr={p:.4f}")
        if raw_only:
            print(" ○ Metinde geçiyor ama varlık sayılmadı. Boşluk değil; tür setini genişlet.")
            for n, d, p in raw_only[:top]:
                print(f"   ○ {canon.get(n,n)[:34]:<34} df={d} pr={p:.4f}")
        print("-" * 74)
    print(" NOT: PageRank vekil bir ölçümdür; gerçek konu otoritesini göstermez.")
    print("      Konunun varlık iskeletini gösterir. Script yalnız ölçer; içerik ya")
    print("      da bağlantı eklemek ayrı ve onaylı bir adımdır.")
    print("=" * 74)

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="entitykit graph",
        description="Sayfa grubunun varlık ağını kurar; --target ile hedef "
                    "sayfada eksik sütun varlıkları gösterir.")
    ap.add_argument("--urls", default=None, help="virgüllü URL listesi ya da satır başına bir URL içeren dosya")
    ap.add_argument("--files", default=None, help="sayfa dosyaları: glob, virgülle ya da boşlukla ayrılmış")
    ap.add_argument("--target", default=None,
                    help="eksikleri aranacak sayfa (dosya yolu ya da URL)")
    ap.add_argument("--labels", default=None)
    ap.add_argument("--preset", default=None, choices=sorted(LABEL_PRESETS),
                    help="hazır tür seti (--labels verilirse onun yerine geçer)")
    ap.add_argument("--threshold", type=float, default=NER_THRESH)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--no-lemma", action="store_true",
                    help="Türkçe kök bulmayı kapat")
    ap.add_argument("--ner-model", default=NER_MODEL)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args(argv)
    if not (args.urls or args.files):
        sys.exit("HATA: --urls ya da --files ver.")
    labels = ([l.strip() for l in args.labels.split(",")] if args.labels
              else LABEL_PRESETS[args.preset] if args.preset
              else DEFAULT_LABELS)
    use_lemma = not args.no_lemma
    if use_lemma and not tr_lemma.available():
        print("  (uyarı: zeyrek ya da NLTK verisi yok; kök bulma kapalı)", file=sys.stderr)
        use_lemma = False

    docs, _ = load_sources(args.urls, args.files)
    if len(docs) < 2:
        print("UYARI: anlamlı bir ağ için en az 2 sayfa gerekir.", file=sys.stderr)
    ner = load_ner(args.ner_model, args.device)
    per_doc = [doc_entities(ner, txt, labels, args.threshold, use_lemma)
               for _, txt in docs]
    G, df, canon = build_graph(per_doc)

    target_ents, target_name, ttext = None, "", ""
    if args.target:
        if os.path.isfile(args.target):
            with open(args.target, encoding="utf-8", errors="replace") as f:
                ttext = f.read()
            target_name = os.path.basename(args.target)
        else:
            ttext, target_name = fetch_url(args.target), args.target
        target_ents = doc_entities(ner, ttext, labels, args.threshold, use_lemma)

    if not G.number_of_nodes():
        print("Varlık bulunamadı."); return
    report(G, df, canon, len(docs), target_ents, target_name, ttext, args.top,
           use_lemma)

if __name__ == "__main__":
    main()
