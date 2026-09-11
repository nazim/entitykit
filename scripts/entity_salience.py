#!/usr/bin/env python3
"""
entity_salience.py — varlık salience + kapsama açığı (GLiNER + bge-m3)

Varlıkları çıkarır, bge-m3 centroid merkeziliği + frekans + konumla salience
ölçer. --query ile kapsama açığı, --link ile Wikidata QID, --enrich ile
koreferent birleştirme. Detay ve sınırlar için README ve SKILL.md.

  python entity_salience.py --file icerik.md
  python entity_salience.py --file icerik.md --query "kapadokya otel" --link
"""
import argparse, bisect, json, math, os, re, sys, unicodedata
import urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr_lemma   # Türkçe lemmatizasyon (çekim eki → kök); yoksa norm'a düşer

EMB_MODEL   = "BAAI/bge-m3"
NER_MODEL   = "urchade/gliner_multiv2.1"   # çok-dilli, TR güçlü (model kartı: apache-2.0)
NER_THRESH  = 0.45
CHUNK_WORDS = 280                          # GLiNER token sınırı için pencere
# SEO/genel içerik için varsayılan TR label seti (zero-shot, --labels ile değişir)
DEFAULT_LABELS = ["kişi", "kuruluş", "yer", "ürün", "hizmet", "marka",
                  "kavram", "etkinlik", "eser", "tarih", "meslek"]
# Zero-shot recall label setine bağlı (bkz. references/findings.md: varsayılan
# setle "otel" hiç çıkmıyor). --preset hazır setleri verir, --labels eziyor.
LABEL_PRESETS = {
    "genel": DEFAULT_LABELS,
    "konaklama": ["yer", "konaklama tesisi", "oda tipi", "hizmet", "olanak",
                  "ulaşım", "fiyat", "marka", "kavram"],
    "urun": ["ürün", "marka", "ürün özelliği", "malzeme", "fiyat", "kategori",
             "kuruluş", "kavram"],
    "haber": ["kişi", "kuruluş", "yer", "etkinlik", "tarih", "meslek", "kavram"],
    "teknoloji": ["ürün", "kuruluş", "teknoloji", "programlama dili", "kütüphane",
                  "protokol", "kişi", "kavram"],
}

# ---- Türkçe-duyarlı normalizasyon ------------------------------------------
def norm(s):
    s = s.replace("I", "ı").replace("İ", "i").lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s)
                if not unicodedata.combining(c))
    return s.strip()

SENT_RE = re.compile(r"(?<=[\.\!\?…])\s+|\n+")
def split_sentences(text):
    out = [s.strip() for s in SENT_RE.split(text) if s.strip()]
    return out or [text.strip()]

def word_count(text):
    return len(re.findall(r"\w+", text, re.UNICODE))

# ---- Modeller ---------------------------------------------------------------
def load_ner(name, device):
    try:
        from gliner import GLiNER
    except ImportError:
        sys.exit("HATA: gliner yok. Kur: pip install -r requirements.txt")
    import warnings; warnings.filterwarnings("ignore")
    m = GLiNER.from_pretrained(name)
    try:
        m = m.to(device)
    except Exception:
        pass
    return m

def load_emb(name):
    from sentence_transformers import SentenceTransformer
    import warnings; warnings.filterwarnings("ignore")
    m = SentenceTransformer(name)
    m.max_seq_length = 256        # uzun dizi padding'iyle MPS OOM'u önle
    return m

# ---- Varlık çıkarımı: metni pencerele, offset düzelt ------------------------
def sentence_spans(text, sentences):
    """(start, end, sentence) — cümleleri ham metinde sırayla konumla."""
    out, cursor = [], 0
    for s in sentences:
        idx = text.find(s, cursor)
        if idx < 0:
            idx = cursor
        cursor = idx + len(s)
        out.append((idx, cursor, s))
    return out

def chunk_spans(text, max_words=CHUNK_WORDS):
    """Cümleleri ~max_words'lük pencerelere topla; pencereyi HAM metinden DİLİMLE
    ve (chunk_text, base_offset) ver. Cümleleri boşlukla yeniden birleştirmek
    ayırıcıları (\n\n) kısaltıp base + p["start"] offsetini kaydırıyordu."""
    spans = sentence_spans(text, split_sentences(text))
    chunks, start, end, words = [], None, None, 0
    for st, en, s in spans:
        wc = word_count(s)
        if start is not None and words + wc > max_words:
            chunks.append((text[start:end], start))
            start, words = None, 0
        if start is None:
            start = st
        end, words = en, words + wc
    if start is not None:
        chunks.append((text[start:end], start))
    return chunks

def ent_key(surf, use_lemma):
    """Birleştirme anahtarı: lemma'lı norm (Otele/otelde/oteli → 'otel')."""
    base = tr_lemma.lemmatize_phrase(surf) if use_lemma else surf
    return norm(base)

def extract_entities(ner, text, labels, threshold, use_lemma=True):
    """GLiNER ile varlıkları çıkar; lemma-key ile tekilleştir (çekim eki birleşir)."""
    ents = {}   # lemma-key -> dict
    for chunk, base in chunk_spans(text):
        try:
            preds = ner.predict_entities(chunk, labels, threshold=threshold)
        except Exception as e:
            print(f"  (uyarı: chunk atlandı: {e})", file=sys.stderr); continue
        for p in preds:
            surf = p["text"].strip()
            key = ent_key(surf, use_lemma)
            if len(key) < 2:
                continue
            e = ents.setdefault(key, {"surface": surf, "count": 0,
                                      "labels": {}, "score": 0.0,
                                      "first": base + p["start"], "sents": [],
                                      "offsets": [], "_surf": {}})
            e["count"] += 1
            e["offsets"].append(base + p["start"])   # cümle ataması offsetten
            e["labels"][p["label"]] = e["labels"].get(p["label"], 0) + 1
            e["score"] = max(e["score"], p["score"])
            e["first"] = min(e["first"], base + p["start"])
            e["_surf"][surf] = e["_surf"].get(surf, 0) + 1   # yüzey frekansı
    # gösterilen yüzey = en sık geçen orijinal form (çekimli "otelin" değil)
    for e in ents.values():
        e["surface"] = max(e["_surf"].items(), key=lambda kv: (kv[1], len(kv[0])))[0]
    return ents

def attach_sentences(ents, text, sentences):
    """Her varlığı, GLiNER offset'lerinin düştüğü cümlelere bağla. Metinde tekrar
    substring aramak "Van"ı "vanilya" cümlesine bağlıyordu; artık arama yok."""
    spans = sentence_spans(text, sentences)
    starts = [st for st, _, _ in spans]
    for e in ents.values():
        seen, sents = set(), []
        for off in e.get("offsets", []):
            i = bisect.bisect_right(starts, off) - 1
            s = spans[max(i, 0)][2] if spans else e["surface"]
            if s not in seen:
                seen.add(s); sents.append(s)
        e["sents"] = sents or [e["surface"]]   # düşmesin

# ---- Salience hesabı (bge-m3 centroid merkeziliği) --------------------------
def compute_salience(emb, ents, doc_len):
    import numpy as np
    # tüm cümle embedding'lerinden doc centroid
    all_sents = sorted({s for e in ents.values() for s in e["sents"]})
    if not all_sents:
        return
    vecs = emb.encode(all_sents, normalize_embeddings=True)
    by_sent = {s: v for s, v in zip(all_sents, vecs)}
    centroid = np.mean(vecs, axis=0)
    centroid = centroid / (np.linalg.norm(centroid) + 1e-9)

    raw_freq = [math.log1p(e["count"]) for e in ents.values()]
    fmax = max(raw_freq) or 1.0
    for e in ents.values():
        cv = np.mean([by_sent[s] for s in e["sents"]], axis=0)
        cv = cv / (np.linalg.norm(cv) + 1e-9)
        e["centrality"] = float(np.dot(cv, centroid))            # -1..1
        e["ctx_vec"]    = cv
        e["freq_score"] = math.log1p(e["count"]) / fmax          # 0..1
        e["pos_score"]  = 1.0 - (e["first"] / max(doc_len, 1))   # 0..1 (erken=yüksek)
    # centrality'yi 0..1'e min-max çek (relatif)
    cs = [e["centrality"] for e in ents.values()]
    lo, hi = min(cs), max(cs)
    rng = (hi - lo) or 1.0
    for e in ents.values():
        cn = (e["centrality"] - lo) / rng
        e["salience"] = 0.5 * cn + 0.3 * e["freq_score"] + 0.2 * e["pos_score"]
    # 0..100 okunurluk ölçeği
    sv = [e["salience"] for e in ents.values()]
    smax = max(sv) or 1.0
    for e in ents.values():
        e["salience100"] = round(100 * e["salience"] / smax, 1)

def majority_label(e):
    return max(e["labels"].items(), key=lambda kv: kv[1])[0] if e["labels"] else "?"

PROPER = {"yer", "kişi", "kuruluş", "marka", "eser"}   # özel isim: ayrı kalsın

def should_merge(tok_a, tok_b, label_a, label_b, sim, sim_thresh):
    """İki varlık aynı kanonik varlık mı? (saf karar — bağımlılıksız, testli)

    TOKEN-set içerme: "otel"⊆{mağara,otel} ✓ ama "otel"⊄{grand,hotel}.
    İçerme dalı da özel isimde KAPALI: "Ankara" ile "Ankara Üniversitesi",
    "Göreme" ile "Göreme Belediyesi" ayrı varlıklardır, birleşmemeli.
    """
    proper = label_a in PROPER or label_b in PROPER
    sub = tok_a <= tok_b or tok_b <= tok_a
    if sub and not proper:
        return True
    # embedding birleştirme YALNIZ özel-isim-olmayan, aynı tür, çok yüksek eşik
    return sim >= sim_thresh and label_a == label_b and not proper

# ---- Hibrit enrichment: bge-m3 ile koreferent varlıkları birleştir ----------
def merge_entities(emb, ents, sim_thresh=0.93):
    """Parçalanmış yüzeyleri (otel / mağara otel / butik otel) tek kanonik
    varlığa indir. Birleştirme ölçütü: substring içerme VEYA yüzey embedding cosine
    >= eşik. Union-Find. GLiNER recall parçalanmasını ve linking gürültüsünü azaltır.
    (Generatif Qwen tip/ilişki katmanı instruct model + ~6GB indirme ister — ayrı
    adım; bu merge mevcut bge-m3 ile çalışan, indirmesiz hibrit katmandır.)"""
    import numpy as np
    keys = list(ents.keys())
    if len(keys) < 2:
        return ents
    surfs = [ents[k]["surface"] for k in keys]
    V = emb.encode(surfs, normalize_embeddings=True, batch_size=16)
    parent = {k: k for k in keys}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        parent[find(a)] = find(b)
    tok = {k: set(re.findall(r"\w+", k)) for k in keys}    # kelime token kümeleri
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            ki, kj = keys[i], keys[j]
            if should_merge(tok[ki], tok[kj],
                            majority_label(ents[ki]), majority_label(ents[kj]),
                            float(np.dot(V[i], V[j])), sim_thresh):
                union(ki, kj)
    groups = {}
    for k in keys:
        groups.setdefault(find(k), []).append(k)
    merged = {}
    for root, members in groups.items():
        # kanonik = en yüksek frekanslı; eşitlikte en uzun yüzey
        canon = max(members, key=lambda k: (ents[k]["count"], len(ents[k]["surface"])))
        e = {"surface": ents[canon]["surface"], "count": 0, "labels": {},
             "score": 0.0, "first": min(ents[k]["first"] for k in members),
             "sents": []}
        seen = set()
        for k in members:
            m = ents[k]
            e["count"] += m["count"]
            for lab, c in m["labels"].items():
                e["labels"][lab] = e["labels"].get(lab, 0) + c
            e["score"] = max(e["score"], m["score"])
            for s in m["sents"]:
                if s not in seen:
                    seen.add(s); e["sents"].append(s)
        merged[norm(e["surface"])] = e
    return merged

# ---- Sorgu kapsama açığı ----------------------------------------------------
def lemma_tokens(text, use_lemma):
    """Ham metnin lemma'lı token dizisi: (token kümesi, boşluk-sarmalı dizi).
    Kelime SINIRLI eşleşme için — "van" artık "vanilya"da bulunmaz."""
    toks = [ent_key(t, use_lemma) for t in re.findall(r"\w+", text, re.UNICODE)]
    return set(toks), " " + " ".join(toks) + " "

def in_raw_text(key, tokset, joined):
    """Varlık olarak çıkmayan aday ham metinde geçiyor mu (kelime sınırlı, lemma'lı)."""
    parts = key.split()
    if not parts:
        return False
    return parts[0] in tokset if len(parts) == 1 else f" {key} " in joined

def key_match(k, present_keys):
    """Aday anahtarı mevcut varlıklarla TOKEN-set düzeyinde eşle (karakter içerme yok)."""
    if k in present_keys:
        return k
    kt = set(k.split())
    for pk in present_keys:
        pt = set(pk.split())
        if kt <= pt or pt <= kt:
            return pk
    return None

def coverage_gap(emb, ents, ner, query, labels, threshold, text="", use_lemma=True):
    import numpy as np
    qv = emb.encode(query, normalize_embeddings=True)
    # her varlığın sorguya yakınlığı
    for e in ents.values():
        e["q_rel"] = float(np.dot(e["ctx_vec"], qv))
    # sorgunun KENDİ varlıkları -> hangisi metinde zayıf/yok?
    q_ents = extract_entities(ner, query, labels, max(0.25, threshold - 0.2), use_lemma)
    cands = {k: qe["surface"] for k, qe in q_ents.items()}
    # FALLBACK: kısa sorgudan GLiNER varlık çıkaramazsa, sorgu içerik-token'larını
    # aday entity say (stopword'süz). Kapsama her zaman bir sinyal versin.
    if not cands:
        STOP = {"ne", "nasil", "icin", "ile", "mi", "mu", "ve", "bir", "bu"}
        for t in re.findall(r"\w+", query, re.UNICODE):
            nt = ent_key(t, use_lemma)
            if len(nt) > 2 and nt not in STOP:
                cands[nt] = t
    present = set(ents.keys())
    tokset, joined = lemma_tokens(text, use_lemma)
    gaps = []
    for k, surf in cands.items():
        hit = key_match(k, present)
        if hit:
            sal = ents[hit]["salience100"]
            gaps.append((surf, "zayıf" if sal < 40 else "var", sal))
        elif in_raw_text(k, tokset, joined):
            # üçüncü durum: kelime metinde GEÇİYOR ama GLiNER varlık saymadı
            # (zero-shot recall / label seti sorunu) — eklemeden önce label'ı gevşet
            gaps.append((surf, "ham", 0.0))
        else:
            gaps.append((surf, "EKSİK", 0.0))
    return gaps

# ---- Wikidata linking (online, anahtarsız) ----------------------------------
def wikidata_link(term, lang="tr", timeout=8):
    q = urllib.parse.urlencode({"action": "wbsearchentities", "search": term,
                                "language": lang, "uselang": lang,
                                "format": "json", "limit": 1})
    url = "https://www.wikidata.org/w/api.php?" + q
    req = urllib.request.Request(url, headers={
        "User-Agent": "entitykit/0.1 (local content-analysis research)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        s = d.get("search", [])
        if s:
            return s[0]["id"], s[0].get("description", "")
    except Exception as e:
        return None, f"(link hatası: {e})"
    return None, ""

# ---- Rapor ------------------------------------------------------------------
def report(ents, query, gaps, linked, top):
    rows = sorted(ents.values(), key=lambda e: -e["salience100"])[:top]
    print("=" * 72)
    print(" entitykit — entity salience raporu  (GLiNER + bge-m3, VEKİL ölçüm)")
    print("=" * 72)
    print(f" varlık sayısı : {len(ents)} (tekil)    gösterilen: {len(rows)}")
    if query:
        print(f" sorgu         : {query}")
    print("-" * 72)
    hq = "  q_rel" if query else ""
    hl = "  QID" if linked else ""
    print(f" {'salience':>8} {'tür':<10} {'frq':>3} {'kon':>4}  varlık{hq}{hl}")
    for e in rows:
        line = (f" {e['salience100']:8.1f} {majority_label(e):<10} "
                f"{e['count']:>3} {e['pos_score']:4.2f}  {e['surface'][:30]}")
        if query:
            line += f"  {e.get('q_rel', 0):.3f}"
        if linked:
            qid, desc = linked.get(norm(e["surface"]), (None, ""))
            line += f"  {qid or '—'}"
        print(line)
    print("-" * 72)
    if query and gaps:
        print(" SORGU KAPSAMA AÇIĞI (sorgudaki varlıklar metinde ne durumda)")
        order = {"EKSİK": 0, "ham": 1, "zayıf": 2, "var": 3}
        mark = {"EKSİK": "✗", "ham": "○", "zayıf": "△", "var": "✓"}
        desc = {"EKSİK": "tespit edilemedi (metinde de yok)",
                "ham": "metinde geçiyor, varlık tanınmadı",
                "zayıf": "varlık, salience düşük",
                "var": "varlık, salience yeterli"}
        for surf, status, sal in sorted(gaps, key=lambda g: order.get(g[1], 4)):
            sal_s = f"salience {sal:.0f}" if status in ("var", "zayıf") else "—"
            print(f"   {mark[status]} {surf[:30]:<30} {desc[status]:<34} {sal_s}")
        if any(g[1] == "ham" for g in gaps):
            print("   ○ = EKLEMEDEN ÖNCE: kelime metinde var; --labels'ı gevşet/genişlet,")
            print("     GLiNER zero-shot recall'ı label setine bağlıdır.")
        print("-" * 72)
    if linked:
        print(" WIKIDATA bağlamı (ilk başvuru açıklamaları)")
        for e in rows:
            qid, desc = linked.get(norm(e["surface"]), (None, ""))
            if qid:
                print(f"   {qid:<11} {e['surface'][:24]:<24} {desc[:34]}")
        print("-" * 72)
    print(" NOT: salience relatiftir (0-100 sadece okunurluk). Bu bir VEKİL —")
    print("      Google NLP salience'ının embedding-geometri temsili. READ-ONLY;")
    print("      eksik entity eklemek/öne çekmek AYRI ve ONAYLI bir adımdır.")
    print("=" * 72)

def second_pass(ner, emb, text, sentences, labels, extra, threshold,
                use_lemma, enrich):
    """○ adaylarını LABEL olarak ekleyip yeniden çıkar: kelime metinde geçiyorsa
    salience'ını da öğren. Zero-shot label seti recall'ı belirlediği için bu,
    'eksik mi yoksa sadece tanınmadı mı' sorusunun ölçülmüş cevabıdır."""
    labels2 = list(dict.fromkeys(list(labels) + extra))
    print(f" İKİNCİ GEÇİŞ — eklenen label'lar: {', '.join(extra)}")
    ents2 = extract_entities(ner, text, labels2, threshold, use_lemma)
    if not ents2:
        print("   (ikinci geçişte de varlık çıkmadı)"); return
    attach_sentences(ents2, text, sentences)
    if enrich:
        ents2 = merge_entities(emb, ents2)
    compute_salience(emb, ents2, len(text))
    keys = {ent_key(x, use_lemma) for x in extra}
    rows = [e for k, e in ents2.items() if key_match(k, keys)]
    if not rows:
        print("   (eklenen label'larla da çıkmadı — gerçekten zayıf sinyal)"); return
    print(f" {'salience':>8} {'tür':<18} {'frq':>3}  varlık")
    for e in sorted(rows, key=lambda e: -e["salience100"]):
        print(f" {e['salience100']:8.1f} {majority_label(e):<18} "
              f"{e['count']:>3}  {e['surface'][:30]}")
    print(f" (bu tablo İKİNCİ geçişin skorları — yukarıdaki tabloyla aynı ölçekte")
    print(f"  DEĞİL; salience her koşuda o koşunun en yükseğine göre normalize)")
    print("-" * 72)

def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()

import html as _html
def html_to_text(raw):
    raw = re.sub(r"(?is)<(script|style|noscript|template).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
    raw = re.sub(r"(?i)<(br|/p|/div|/h[1-6]|/li|/tr)\s*/?>", "\n", raw)
    txt = _html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", txt)).strip()

BOILER_TAGS = ("script", "style", "noscript", "template", "nav", "header",
               "footer", "aside", "form", "svg", "iframe", "button", "select")

def main_content(raw):
    """Boilerplate'i at, varsa yalnız <main>/<article> gövdesini al.

    Neden: aynı sitenin iki sayfasını karşılaştırırken ortak menü/footer
    info_gain'de SAHTE near-verbatim kopya, topical_graph'ta sahte sütun varlık
    üretiyordu. SINIR: regex temelli; iç içe <div class="sidebar"> gibi blokları
    ayıklamaz — tam bir okunabilirlik (readability) çıkarımı DEĞİL.
    """
    for t in BOILER_TAGS:
        raw = re.sub(rf"(?is)<{t}\b.*?</{t}\s*>", " ", raw)
        raw = re.sub(rf"(?is)<{t}\b[^>]*/?>", " ", raw)
    m = re.search(r"(?is)<main\b[^>]*>(.*?)</main\s*>", raw)
    if m:
        raw = m.group(1)
    else:
        arts = re.findall(r"(?is)<article\b[^>]*>(.*?)</article\s*>", raw)
        if arts:
            raw = "\n\n".join(arts)
    return html_to_text(raw)

def fetch_raw(url, timeout=15, ua="Mozilla/5.0 (entitykit/0.1 content-analysis research)"):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8",
                               errors="replace")

def fetch_url(url, timeout=15):
    return main_content(fetch_raw(url, timeout))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None, help="yerel dosya (md/txt)")
    ap.add_argument("--url", default=None, help="canlı sayfa URL'si (HTML→metin çekilir)")
    ap.add_argument("--query", default=None, help="kapsama açığı için hedef sorgu")
    ap.add_argument("--labels", default=None, help="virgülle entity türleri")
    ap.add_argument("--preset", default=None, choices=sorted(LABEL_PRESETS),
                    help="hazır label seti (--labels verilirse o ezer)")
    ap.add_argument("--second-pass", action="store_true",
                    help="'metinde geçiyor ama varlık tanınmadı' (○) adaylarını "
                         "label olarak ekleyip ikinci geçiş yap")
    ap.add_argument("--link", action="store_true", help="Wikidata QID bağla (online)")
    ap.add_argument("--enrich", action="store_true",
                    help="bge-m3 ile koreferent varlıkları birleştir (parçalanma fix)")
    ap.add_argument("--no-lemma", action="store_true",
                    help="Türkçe lemmatizasyonu kapat (çekim eki birleştirmesi)")
    ap.add_argument("--threshold", type=float, default=NER_THRESH)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--ner-model", default=NER_MODEL)
    ap.add_argument("--emb-model", default=EMB_MODEL)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    labels = ([l.strip() for l in args.labels.split(",")] if args.labels
              else LABEL_PRESETS[args.preset] if args.preset
              else DEFAULT_LABELS)
    if not (args.file or args.url):
        sys.exit("HATA: --file veya --url ver.")
    use_lemma = not args.no_lemma
    if use_lemma and not tr_lemma.available():
        print("  (uyarı: zeyrek yok, lemmatizasyon kapalı — çekim eki birleşmez)",
              file=sys.stderr)
        use_lemma = False
    text = fetch_url(args.url) if args.url else read(args.file)
    sentences = split_sentences(text)

    ner = load_ner(args.ner_model, args.device)
    ents = extract_entities(ner, text, labels, args.threshold, use_lemma)
    if not ents:
        print("Varlık bulunamadı. --labels veya --threshold'u gevşet.")
        return
    attach_sentences(ents, text, sentences)

    emb = load_emb(args.emb_model)
    if args.enrich:
        before = len(ents)
        ents = merge_entities(emb, ents)
        print(f"  (enrich: {before}→{len(ents)} varlık birleştirildi)",
              file=sys.stderr)
    compute_salience(emb, ents, len(text))

    gaps = coverage_gap(emb, ents, ner, args.query, labels, args.threshold,
                        text, use_lemma) if args.query else None

    linked = {}
    if args.link:
        for e in sorted(ents.values(), key=lambda e: -e["salience100"])[:args.top]:
            # arama terimi = lemma'lı yüzey (çekimli formdan QID şaşmasını azaltır)
            term = tr_lemma.lemmatize_phrase(e["surface"]) if use_lemma else e["surface"]
            linked[norm(e["surface"])] = wikidata_link(term)

    report(ents, args.query, gaps, linked, args.top)

    if args.second_pass and gaps:
        extra = [surf for surf, st, _ in gaps if st == "ham"]
        if not extra:
            print(" (ikinci geçiş: ○ durumunda aday yok — atlandı)")
        else:
            second_pass(ner, emb, text, sentences, labels, extra,
                        args.threshold, use_lemma, args.enrich)

if __name__ == "__main__":
    main()
