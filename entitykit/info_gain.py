#!/usr/bin/env python3
"""
info_gain.py — bilgi kazancı / kopya tespiti (bge-m3)

Taslağın her cümlesini rakip korpusa karşı ölçer: novelty = 1 - max cosine.
Asıl çıktı near-verbatim kopya uyarısı. Detay ve sınırlar için README ve
SKILL.md.

  entitykit gain taslak.md --rival-urls "https://a.com,https://b.com"
  entitykit gain taslak.md --rival-files "rakipler/*.txt"
"""
import argparse, os, re, sys
from .entity_salience import (EMB_MODEL, SENT_RE, fetch_url, load_emb,
                             load_sources as load_rivals)

MIN_WORDS = 5       # bu kelime sayısından kısa cümleleri atla (gürültü)
MAX_WORDS = 60      # bundan uzun "cümle"yi kırp (tablo/kaynakça satırı = OOM riski)
MAX_RIVAL_SENTS = 1500   # rakip korpus tavanı (bellek + hız)
ENC_BATCH = 16
SHINGLE_N = 4            # sözcüksel örtüşme n-gram uzunluğu
# LEX_EXACT, LEX_HIGH, SEM_NEAR ölçülmemiş varsayımdır (references/findings.md'de
# doğrulanmadı).
LEX_EXACT = 0.95         # bu örtüşmenin üstü = birebir eşleşme
LEX_HIGH = 0.50          # bu örtüşmenin üstü = yüksek sözcüksel benzerlik
SEM_NEAR = 0.15          # novelty bu eşiğin altı = anlamsal yakınlık (kopya DEĞİL)

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

def label(name):
    """Rapor için kısa kaynak adı: dosyada taban ad, URL'de tam adres."""
    return os.path.basename(name) if os.path.exists(name) else name

def exclude_self(rivals, draft_url=None, draft_file=None):
    """Taslağın kendisini rakiplerden çıkar. Dosya adı değil, aynı dosya mı diye
    bakılır: farklı klasörde aynı adlı rakip korunur."""
    def same(n):
        if draft_url:
            return n.rstrip("/") == draft_url.rstrip("/")
        return os.path.exists(n) and os.path.samefile(n, draft_file)
    return [(n, t) for n, t in rivals if not same(n)]

def analyze(emb, draft, rivals, top, failed=(), n_requested=None,
            self_excluded=0):
    import numpy as np
    d_sents, d_stats = split_units(draft)
    if not d_sents:
        print(f"Taslakta ölçülecek cümle yok. Cümlelerin hepsi {MIN_WORDS} kelimeden "
              "kısa olabilir."); return
    per_doc, r_total, r_stats = [], 0, {"short_skipped": 0, "long_split": 0}
    for name, txt in rivals:
        units, st = split_units(txt)
        per_doc.append((name, units)); r_total += len(units)
        for k in r_stats:
            r_stats[k] += st[k]
    if not r_total:
        print("Rakip metin yok. URL'ler alınamadı ya da dosya bulunamadı."); return
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
    print(f" KAPSAM  : kaynak {n_src}, ölçülen rakip {len(rivals)}"
          + (f", alınamayan {len(failed)}" if failed else "")
          + (f", taslağın kendisi olduğu için çıkarılan {self_excluded}"
             if self_excluded else "")
          + f". Taslak {len(d_sents)} birim, rakipler {r_total} birim.")
    if capped:
        print(f"           Rakip metin {r_total} birimden {len(r_sents)} birime "
              f"indirildi (kaynaklar arasında dengeli).")
    print(f"           bölünen uzun cümle: taslak {d_stats['long_split']} / rakip "
          f"{r_stats['long_split']}   atlanan kısa parça (<{MIN_WORDS} kelime): "
          f"taslak {d_stats['short_skipped']} / rakip {r_stats['short_skipped']}")
    for name, err in failed:
        print(f"           ✗ alınamadı: {name[:44]} — {err[:28]}")
    print("-" * 74)
    print(f" ORTALAMA anlamsal farklılık : {sem_diff:.3f}   (rakiplere göre)")
    print("   Aynı konudaki sayfalarda düşük çıkar; hedef değildir. Bilgi")
    print("   kazancının vekilidir.")
    print("-" * 74)
    # ASIL ÇIKTI: kopya iddiası SÖZCÜKSEL kanıta dayanır, anlamsal yakınlık ayrı
    from collections import Counter
    def block(kind, title, hint):
        sel = [r for r in rows if r["kind"] == kind
               and len(r["sent"].split()) >= MIN_WORDS]
        if not sel:
            return
        print(f" ⚠ {title}: {len(sel)} birim")
        src = Counter((r["lex_src"] or r["near_src"]) for r in sel)
        for nm, c in src.most_common():
            print(f"     {c:>2} birim ≈ {label(nm)[:48]}")
        for r in sel[:top]:
            print(f"     lex={r['lex']:.2f} sem={1 - r['novelty']:.2f}  {r['sent'][:52]}")
        print(f"   → {hint}")
    block("birebir", "BİREBİR EŞLEŞME (aynı cümle)",
          "Bu cümleler kopya. Yeniden yaz ya da ortak bilgiyi tek bir sayfada "
          "tutup oraya bağlantı ver.")
    block("sözcüksel", "YÜKSEK SÖZCÜKSEL BENZERLİK",
          "Aynı kelime dizileri var. Cümleyi kendi açından yeniden kur.")
    block("anlamsal", "ANLAMSAL YAKINLIK (kopya değil)",
          "Aynı şeyi farklı kelimelerle söylüyorsun. Bu bir sorun olmak zorunda "
          "değil; yeni bir şey katmıyorsa çıkar.")
    if not any(r["kind"] in ("birebir", "sözcüksel") for r in rows):
        print(" ✓ Birebir ya da sözcüksel kopya yok.")
    print("-" * 74)
    print(f" EN ÖZGÜN {min(top,len(rows))} BİRİM (asıl katkın; koru ve güçlendir)")
    for r in sorted(rows, key=lambda r: -r["novelty"])[:top]:
        print(f"  +{r['novelty']:.2f}  {r['sent'][:64]}")
    print("-" * 74)
    print(f" EN TEKRARLI {min(top,len(rows))} BİRİM (rakipler de söylüyor)")
    for r in sorted(rows, key=lambda r: r["novelty"])[:top]:
        print(f"  {r['novelty']:.2f} (lex {r['lex']:.2f})  {r['sent'][:44]}")
        print(f"        ≈ [{label(r['near_src'])[:22]}] {r['near'][:44]}")
    print("-" * 74)
    print(" NOT: Anlamsal farklılık görelidir. 'Özgün', rakiplerden anlamca uzak")
    print("      demektir; doğru ya da değerli demek değildir. Kopya iddiası yalnız")
    print("      sözcüksel kanıta dayanır. Eşikler varsayımdır. Script yalnız ölçer;")
    print("      cümle eklemek ya da çıkarmak ayrı ve onaylı bir adımdır.")
    print("=" * 74)

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="entitykit gain",
        description="Taslağın cümlelerini rakip sayfalarla karşılaştırır; kopya "
                    "ve en özgün cümleleri gösterir.")
    ap.add_argument("--file", default=None, help="taslak dosyası (md/txt)")
    ap.add_argument("--url", default=None, help="taslağın canlı sayfa URL'si")
    ap.add_argument("--rival-urls", default=None,
                    help="virgüllü URL listesi ya da satır başına bir URL içeren dosya")
    ap.add_argument("--rival-files", default=None, help="rakip dosyalar: glob, virgülle ya da boşlukla ayrılmış")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--emb-model", default=EMB_MODEL)
    args = ap.parse_args(argv)
    if not (args.file or args.url):
        sys.exit("HATA: --file ya da --url ile taslağı ver.")
    if not (args.rival_urls or args.rival_files):
        sys.exit("HATA: --rival-urls ya da --rival-files ver.")

    if args.url:
        draft = fetch_url(args.url)
    else:
        with open(args.file, encoding="utf-8") as f:
            draft = f.read()
    rivals, failed = load_rivals(args.rival_urls, args.rival_files)
    n_requested = len(rivals) + len(failed)
    # taslağın kendisi rakip korpusa karışmışsa çıkar (kendi cümleleri novelty'yi 0'lar)
    n_loaded = len(rivals)
    rivals = exclude_self(rivals, args.url, args.file)
    emb = load_emb(args.emb_model)
    analyze(emb, draft, rivals, args.top, failed, n_requested,
            n_loaded - len(rivals))

if __name__ == "__main__":
    main()
