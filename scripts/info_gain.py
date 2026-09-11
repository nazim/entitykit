#!/usr/bin/env python3
"""
info_gain.py — bilgi kazancı / kopya tespiti (bge-m3)

Taslağın her cümlesini rakip korpusa karşı ölçer: novelty = 1 - max cosine.
Asıl çıktı near-verbatim kopya uyarısı. Detay ve sınırlar için README ve
SKILL.md.

  python info_gain.py --file taslak.md --rival-urls "https://a.com,https://b.com"
  python info_gain.py --file taslak.md --rival-files "rakipler/*.txt"
"""
import argparse, glob, os, re, sys
import urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from entity_salience import main_content   # boilerplate ayıklama tek yerde

EMB_MODEL = "BAAI/bge-m3"
MIN_WORDS = 5       # bu kelime sayısından kısa cümleleri atla (gürültü)
MAX_WORDS = 60      # bundan uzun "cümle"yi kırp (tablo/kaynakça satırı = OOM riski)
MAX_RIVAL_SENTS = 1500   # rakip korpus tavanı (bellek + hız)
ENC_BATCH = 16
SHINGLE_N = 4            # sözcüksel örtüşme n-gram uzunluğu
LEX_EXACT = 0.95         # bu örtüşmenin üstü = birebir eşleşme
LEX_HIGH = 0.50          # bu örtüşmenin üstü = yüksek sözcüksel benzerlik
SEM_NEAR = 0.15          # novelty bu eşiğin altı = anlamsal yakınlık (kopya DEĞİL)

SENT_RE = re.compile(r"(?<=[\.\!\?…])\s+|\n+")
def split_units(text):
    """Ölçüm birimlerine böl ve NE ATLADIĞINI say.

    Eskiden MAX_WORDS'ten uzun cümlenin kuyruğu w[:MAX_WORDS] ile ÇÖPE gidiyordu
    (o metin hiç ölçülmemiş oluyordu). Artık uzun cümle parçalara BÖLÜNÜR.
    Dönüş: (units, stats) — stats rapora basılır.
    """
    units, short, long_split = [], 0, 0
    for s in SENT_RE.split(text):
        w = s.split()
        if not w:
            continue
        if len(w) < MIN_WORDS:
            short += 1
            continue
        if len(w) <= MAX_WORDS:
            units.append(" ".join(w))
            continue
        long_split += 1
        for i in range(0, len(w), MAX_WORDS):
            part = " ".join(w[i:i + MAX_WORDS])
            if len(w[i:i + MAX_WORDS]) >= MIN_WORDS or not units:
                units.append(part)
            else:
                units[-1] += " " + part      # son kırıntıyı öncekine ekle
    return units, {"short_skipped": short, "long_split": long_split}

def split_sentences(text):
    return split_units(text)[0]

# ---- Sözcüksel katman (anlamsal benzerlikten AYRI) --------------------------
def norm_lex(s):
    """Sözcüksel karşılaştırma için normalize: TR küçük harf, yalnız kelimeler."""
    s = s.replace("I", "ı").replace("İ", "i").lower()
    return " ".join(re.findall(r"\w+", s, re.UNICODE))

def shingles(s, n=SHINGLE_N):
    w = norm_lex(s).split()
    if len(w) < n:
        return {" ".join(w)} if w else set()
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}

def lexical_best(draft_units, rival_units):
    """Her taslak birimi için en yüksek SÖZCÜKSEL örtüşmeyi bul (containment:
    ortak shingle / taslağın shingle sayısı). Shingle ters-indeksiyle O(shingle).

    Neden ayrı: bge-m3 cosine'i parafraza da 0.85+ verir; "kopya" iddiası
    sözcüksel kanıt ister. Dönüş: [(oran, rakip_index|None), ...]
    """
    index = {}
    for j, s in enumerate(rival_units):
        for g in shingles(s):
            index.setdefault(g, set()).add(j)
    out = []
    for s in draft_units:
        sh = shingles(s)
        if not sh:
            out.append((0.0, None)); continue
        hits = {}
        for g in sh:
            for j in index.get(g, ()):
                hits[j] = hits.get(j, 0) + 1
        if not hits:
            out.append((0.0, None)); continue
        j, c = max(hits.items(), key=lambda kv: kv[1])
        out.append((c / len(sh), j))
    return out

def balanced_sample(per_doc, cap):
    """Korpus tavanını kaynaklar arasında DENGELİ doldur (round-robin).
    Eskiden r_sents[:cap] ilk dokümanlara tüm kotayı yedirebiliyordu."""
    out, i = [], 0
    while len(out) < cap:
        added = False
        for name, sents in per_doc:
            if i < len(sents):
                out.append((sents[i], name)); added = True
                if len(out) >= cap:
                    break
        if not added:
            break
        i += 1
    return out

def fetch_url(url, timeout=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (entitykit/0.1 content-analysis research)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        enc = r.headers.get_content_charset() or "utf-8"
    return raw.decode(enc, errors="replace")

def load_rivals(urls_arg, files_arg):
    docs, failed = [], []   # (name, text) / (name, hata) — kapsam özetine girer
    if urls_arg:
        # dosya yolu mu yoksa virgüllü liste mi?
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
                failed.append((u, str(e)))
                print(f"  (uyarı: çekilemedi {u}: {e})", file=sys.stderr)
    if files_arg:
        # virgül VEYA boşlukla ayrılmış birden çok glob/yol kabul et
        for part in re.split(r"[,\s]+", files_arg.strip()):
            if not part:
                continue
            for p in glob.glob(os.path.expanduser(part)):
                with open(p, encoding="utf-8") as f:
                    docs.append((os.path.basename(p), f.read()))
    return docs, failed

# ---- Model ------------------------------------------------------------------
def load_emb(name):
    from sentence_transformers import SentenceTransformer
    import warnings; warnings.filterwarnings("ignore")
    m = SentenceTransformer(name)
    m.max_seq_length = 256        # uzun dizi padding'iyle MPS OOM'u önle
    return m

def analyze(emb, draft, rivals, top, failed=(), n_requested=None,
            self_excluded=0):
    import numpy as np
    d_sents, d_stats = split_units(draft)
    if not d_sents:
        print("Taslakta ölçülecek cümle yok (hepsi çok kısa?)."); return
    per_doc, r_total, r_stats = [], 0, {"short_skipped": 0, "long_split": 0}
    for name, txt in rivals:
        units, st = split_units(txt)
        per_doc.append((name, units)); r_total += len(units)
        for k in r_stats:
            r_stats[k] += st[k]
    if not r_total:
        print("Rakip korpus boş — URL çekilemedi ya da dosya yok."); return
    sampled = balanced_sample(per_doc, MAX_RIVAL_SENTS)
    r_sents = [u for u, _ in sampled]
    r_owner = [n for _, n in sampled]
    capped = r_total > len(r_sents)

    dv = emb.encode(d_sents, normalize_embeddings=True, batch_size=ENC_BATCH)
    rv = emb.encode(r_sents, normalize_embeddings=True, batch_size=ENC_BATCH)
    sim = dv @ rv.T                      # (draft x rival) cosine
    best = sim.argmax(axis=1)
    maxsim = sim.max(axis=1)
    novelty = 1.0 - maxsim               # yüksek = özgün
    lex = lexical_best(d_sents, r_sents) # (oran, rakip index) — ANLAMDAN AYRI

    rows = []
    for i in range(len(d_sents)):
        lex_r, lex_j = lex[i]
        if lex_r >= LEX_EXACT:
            kind = "birebir"
        elif lex_r >= LEX_HIGH:
            kind = "sözcüksel"
        elif novelty[i] < SEM_NEAR:
            kind = "anlamsal"
        else:
            kind = "-"
        rows.append({"i": i, "sent": d_sents[i], "novelty": float(novelty[i]),
                     "near": r_sents[best[i]], "near_src": r_owner[best[i]],
                     "sim": float(maxsim[i]), "lex": lex_r, "kind": kind,
                     "lex_src": r_owner[lex_j] if lex_j is not None else "",
                     "lex_near": r_sents[lex_j] if lex_j is not None else ""})

    sem_diff = float(np.mean(novelty))
    print("=" * 74)
    print(" entitykit — bilgi kazancı raporu   (bge-m3 anlam + shingle sözcüksel)")
    print("=" * 74)
    # KAPSAM: eksik analizden üretilen rapor tam analiz gibi görünmesin
    n_src = len(rivals) + len(failed) if n_requested is None else n_requested
    print(f" KAPSAM  : {n_src} kaynağın {len(rivals)}'i rakip olarak ölçüldü"
          + (f", {len(failed)} alınamadı" if failed else "")
          + (f", {self_excluded} taslağın kendisi (çıkarıldı)" if self_excluded else "")
          + f". taslak {len(d_sents)} birim, rakip korpus {r_total} birim.")
    if capped:
        print(f"           korpus {r_total}→{len(r_sents)} birime kırpıldı "
              f"(kaynak başına DENGELİ örnekleme).")
    print(f"           bölünen uzun cümle: taslak {d_stats['long_split']} / rakip "
          f"{r_stats['long_split']}   atlanan kısa parça (<{MIN_WORDS} kelime): "
          f"taslak {d_stats['short_skipped']} / rakip {r_stats['short_skipped']}")
    for name, err in failed:
        print(f"           ✗ alınamadı: {name[:44]} — {err[:28]}")
    print("-" * 74)
    print(f" ORTALAMA anlamsal farklılık : {sem_diff:.3f}   (rakip korpusa göre;")
    print(f"   aynı konuda düşüktür, hedef DEĞİL. 'bilgi kazancı'nın VEKİLİ.)")
    print("-" * 74)
    # ASIL ÇIKTI: kopya iddiası SÖZCÜKSEL kanıta dayanır, anlamsal yakınlık ayrı
    from collections import Counter
    def block(kind, title, hint):
        sel = [r for r in rows if r["kind"] == kind and len(r["sent"].split()) >= 6]
        if not sel:
            return
        print(f" ⚠ {title}: {len(sel)} birim")
        src = Counter((r["lex_src"] or r["near_src"]) for r in sel)
        for nm, c in src.most_common():
            print(f"     {c:>2} birim ≈ {os.path.basename(nm)[:48]}")
        for r in sel[:top]:
            print(f"     lex={r['lex']:.2f} sem={1 - r['novelty']:.2f}  {r['sent'][:52]}")
        print(f"   → {hint}")
    block("birebir", "BİREBİR EŞLEŞME (aynı cümle)",
          "bu cümleler kopya; yeniden yaz ya da ortak bilgiyi tek kanonik sayfaya "
          "koyup LİNK ver.")
    block("sözcüksel", "YÜKSEK SÖZCÜKSEL BENZERLİK",
          "aynı kelime dizileri; kendi açınla yeniden kurgula.")
    block("anlamsal", "ANLAMSAL YAKINLIK (kopya DEĞİL)",
          "aynı şeyi farklı kelimelerle söylüyorsun — sorun olmak zorunda değil; "
          "fark katmıyorsa kes.")
    if not any(r["kind"] != "-" for r in rows):
        print(" ✓ birebir/sözcüksel kopya YOK — sayfa kendi açısını taşıyor.")
    print("-" * 74)
    print(f" EN ÖZGÜN {min(top,len(rows))} BİRİM (senin asıl katkın — koru/güçlendir)")
    for r in sorted(rows, key=lambda r: -r["novelty"])[:top]:
        print(f"  +{r['novelty']:.2f}  {r['sent'][:64]}")
    print("-" * 74)
    print(f" EN TEKRARLI {min(top,len(rows))} BİRİM (herkes zaten söylüyor)")
    for r in sorted(rows, key=lambda r: r["novelty"])[:top]:
        print(f"  {r['novelty']:.2f} (lex {r['lex']:.2f})  {r['sent'][:44]}")
        print(f"        ≈ [{r['near_src'][:22]}] {r['near'][:44]}")
    print("-" * 74)
    print(" NOT: anlamsal farklılık relatif/yönlüdür; 'özgün' = rakip korpusa")
    print("      semantik uzak, ille doğru/değerli değil. KOPYA iddiası yalnız")
    print("      sözcüksel kanıtla kurulur. READ-ONLY teşhis; cümle ekleme/çıkarma")
    print("      AYRI ve ONAYLI adımdır.")
    print("=" * 74)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None, help="taslak (md/txt)")
    ap.add_argument("--url", default=None, help="taslak canlı sayfa URL'si")
    ap.add_argument("--rival-urls", default=None,
                    help="virgüllü URL listesi VEYA satır-satır URL dosyası")
    ap.add_argument("--rival-files", default=None, help="glob: rakip metin dosyaları")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--emb-model", default=EMB_MODEL)
    args = ap.parse_args()
    if not (args.file or args.url):
        sys.exit("HATA: --file veya --url ver (taslak).")
    if not (args.rival_urls or args.rival_files):
        sys.exit("HATA: --rival-urls veya --rival-files ver.")

    if args.url:
        draft = main_content(fetch_url(args.url))
        draft_base = args.url
    else:
        with open(args.file, encoding="utf-8") as f:
            draft = f.read()
        draft_base = os.path.basename(args.file)
    rivals, failed = load_rivals(args.rival_urls, args.rival_files)
    n_requested = len(rivals) + len(failed)
    # taslağın kendisi rakip korpusa karışmışsa çıkar (kendi cümleleri novelty'yi 0'lar)
    n_loaded = len(rivals)
    rivals = [(n, t) for n, t in rivals if n != draft_base]
    emb = load_emb(args.emb_model)
    analyze(emb, draft, rivals, args.top, failed, n_requested,
            n_loaded - len(rivals))

if __name__ == "__main__":
    main()
