---
name: entitykit
description: Use when analyzing content for ENTITIES and information coverage — entity
  salience, knowledge-graph linking, information gain vs competitors or your own
  pages, and topical authority mapping. Measured with GLiNER + bge-m3 + networkx +
  Wikidata. Triggers — "entity analizi", "varlık analizi", "içerik analizi", "salience
  ölç", "bilgi kazancı / information gain", "rakibe karşı özgünlük", "topical
  authority", "entity coverage / kapsama açığı", "knowledge graph bağla", "entitykit".
  Tuned for Turkish (default labels + lemmatizer).
---

# entitykit — varlık & içerik analizi (entity / IG / authority)

## Ne işe yarar

İçeriği **bilgiye/varlığa** göre ölçer: hangi varlıkları (entity) taşıyor, bunlar
metne ne kadar merkezi (salient), rakibin ya da kendi sayfalarının üstüne ne
katıyor (information gain) ve bir içerik kümesi konuyu hangi varlık iskeleti
etrafında örmüş (topical authority).

entitykit NE eksik/zayıf onu söyler; nasıl yazılacağı ayrı bir adımdır.

## Dört parça

| İhtiyaç | Script | Ne ölçer |
|---|---|---|
| Varlık salience + kapsama | `entity_salience.py` | GLiNER spans → bge-m3 centroid merkeziliği + frekans + konum; `--query` kapsama açığı; `--link` Wikidata QID; `--enrich` koreferent birleştirme |
| Bilgi kazancı | `info_gain.py` | taslak cümleleri vs rakip korpus (URL/dosya); novelty = 1 − rakibe max cosine; near-verbatim kopya uyarısı |
| Topical authority | `topical_graph.py` | içerik kümesinde entity eş-geçiş grafiği (networkx) + PageRank; `--target` kapsama boşluğu |
| TR lemmatizasyon | `tr_lemma.py` | zeyrek/Zemberek; entity key + Wikidata terimi için çekim eki → kök (paylaşılan helper) |

### Çalıştırma
Üçü de **`--file` (yerel) VEYA `--url` (canlı sayfa, HTML→metin çekilir)** alır.
İlk çalıştırmada modeller iner; sonra offline bayrakları eklenebilir.
```bash
PY=.venv/bin/python   # bkz. README kurulum

# 1) Varlık salience + kapsama + Wikidata + birleştirme
$PY scripts/entity_salience.py --file icerik.md --query "<sorgu>" --link --enrich
$PY scripts/entity_salience.py --url "https://site.com/sayfa" --query "<sorgu>" --link

# 2) Information gain — taslak vs rakip ya da kendi sayfaların
$PY scripts/info_gain.py --file taslak.md --rival-urls "https://a.com,https://b.com"
$PY scripts/info_gain.py --file taslak.md --rival-files "sayfalar/*.md"

# 3) Topical authority + kapsama boşluğu
$PY scripts/topical_graph.py --files "site/*.md" --target taslak.md
$PY scripts/topical_graph.py --urls "https://site.com/p1,https://site.com/p2" --target "https://site.com/p1"
```

## Disiplin

- **Script ÖLÇER, sen YAZARSIN.** Üçü de READ-ONLY teşhis; asla otomatik rewrite.
  Eksik entity eklemek / cümle çıkarmak / iç-link koymak AYRI, **minimal ve onaylı** adım.
- **Hepsi VEKİL ölçüm.** salience ≠ Google NLP salience; novelty ≠ gerçek IG;
  PageRank ≠ gerçek topical authority. Embedding-geometri temsilleri; yön verir,
  koordinat vermez. Yayında bunu söyle.
- **Skorlar RELATİF.** 0-100 sadece okunurluk; median'a ve A/B farkına göre konuş.
- **Anlamı bozma.** Salience/coverage yükselteceğim diye alakasız entity tıkıştırma.
  Eksik entity ancak GERÇEKTEN konuya aitse eklenir.
- **info_gain'de ortalama hedef değil.** Aynı konudaki sayfalar doğal olarak birbirine
  yakındır. Bakılacak asıl şey near-verbatim kopya cümle uyarısı.

## Türkçe lemmatizasyon (çekim eki çözümü)

`tr_lemma.py` (zeyrek/Zemberek) entity KEY'ini ve Wikidata arama terimini lemma'dan
üretir: **Otele/otelde/oteli/otelin → "otel"**, özel isimleri (Kapadokya, Göreme)
bozmadan. Gösterilen yüzey = en sık geçen orijinal form. **Default açık**
(entity_salience + topical_graph); `--no-lemma` ile kapatılır; zeyrek yoksa norm'a düşer.

Neden: Wikidata'da çekimli form yanlış düğüme gider. `Otele` → Q7110091 (Kamerun'da
bir köy), lemma `otel` → Q27686 (konaklama yeri). Ayrıntı: `references/findings.md`.

## Bilinen sınırlar

- **GLiNER zero-shot:** label setine duyarlı; recall boşluğu olur (kelime metinde olsa
  da entity sayılmayabilir). Varsayılan label'lar genel türler; niş kavramlar için
  `--labels` ver (örn. "konaklama tesisi").
- **`entity_salience --query` kapsama raporu üç durum ayırır:** `✓ var` / `△ zayıf`
  (varlık çıktı), `○ metinde geçiyor, varlık tanınmadı` (kelime ham metinde kelime
  sınırlı + lemma'lı eşleşiyor ama GLiNER varlık saymadı → `--labels` gevşet, ekleme
  yapma), `✗ tespit edilemedi` (metinde de yok). `topical_graph --target` aynı ayrımı yapar:
  `✗` gerçek boşluk, `○` hedefte geçiyor ama varlık tanınmadı (boşluk değil).
- **Wikidata rate limit:** çok sayıda `--link` sorgusunda Wikidata HTTP 429 döner;
  rapor bu varlıkları QID'siz ("—") gösterir. Bir süre bekleyip tekrar çalıştır.
- **Parçalanma:** aynı kavramın farklı yüzeyleri ayrı varlık çıkabilir; `--enrich`
  token-set + bge-m3 benzerliğiyle birleştirir. Özel isimler (yer/kişi/kuruluş/marka/
  eser) hiçbir dalda birleşmez: "Ankara" ile "Ankara Üniversitesi" ayrı kalır.

- **Boilerplate ayıklama regex temelli:** `--url` yolunda script/nav/header/footer/
  aside/form atılır, `<main>`/`<article>` varsa yalnız o okunur; `<div class="sidebar">`
  gibi bloklar kalır. Tam readability çıkarımı değil.
- **`info_gain` kopya iddiası sözcüksel kanıta dayanır:** birebir (shingle örtüşmesi
  ≥0.95) / yüksek sözcüksel (≥0.50) / salt anlamsal yakınlık (cosine ≥0.85 ama
  sözcüksel düşük) ayrı raporlanır — son grup kopya DEĞİL. Uzun cümle kırpılmaz,
  bölünür; rakip korpus tavanı kaynaklar arasında dengeli örneklenir; KAPSAM satırı
  okunan/alınamayan kaynağı ve atlanan birimi yazar.
- **`--preset`:** `genel|konaklama|urun|haber|teknoloji` hazır label setleri
  (`entity_salience` ve `topical_graph`). `--labels` verilirse preset'i ezer.
- **`--second-pass`:** `○` adaylarını label olarak ekleyip ikinci geçişte ölçer;
  skorlar o koşuya göre normalize olduğu için birinci tabloyla aynı ölçekte değildir.

## Regresyon testleri

`python -m unittest discover -s tests` — model/indirme gerektirmez (saf fonksiyonlar).
Kapsam: karakter içerme eşleşmesi, offset'ten cümle ataması, chunk offset kayması,
özel isim birleştirmesi, "metinde var ama varlık değil" durumu. zeyrek kurulu değilse
lemma testi atlanır.

## Kurulum

`requirements.txt` ile venv kur. **gliner `transformers<5.7.0` ister**; bu sınır
requirements'ta sabit. zeyrek ilk çalıştırmada NLTK `punkt_tab` verisi ister:
`python -c "import nltk; nltk.download('punkt_tab')"`. Modeller (bge-m3,
gliner_multiv2.1) Hugging Face cache'ine iner. Wikidata API anahtarsız, online.
