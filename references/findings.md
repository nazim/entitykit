# entitykit — doğrulama bulguları

Aşağıdaki sonuçlar repodaki `examples/` dosyalarında alındı (4 kısa Türkçe sayfa,
konu Kapadokya). Model ve sürüm: GLiNER `urchade/gliner_multiv2.1`, bge-m3,
gliner 0.2.27, transformers 5.6.2. Wikidata sonuçları çalıştırıldığı andaki API
cevabıdır.

## info_gain.py — kendi sayfalarına karşı kopya tespiti

`otel.md`, diğer üç sayfaya karşı:

```
python scripts/info_gain.py --file examples/otel.md --rival-files "examples/*.md"
```

- KAPSAM satırı: 4 kaynağın 3'ü rakip olarak ölçüldü, 1'i taslağın kendisi olduğu için
  çıkarıldı. Taslak 10 birim, rakip korpus 21 birim; atlanan kısa parça taslakta 1,
  rakipte 2; bölünen uzun cümle yok.
- `otel.md` ile `urgup.md` aynı cümleyi taşıyor ("Bölgede gezmek için en rahat yol
  araç kiralamaktır…"). Rapor bunu **BİREBİR EŞLEŞME** başlığı altında lex=1.00,
  sem=1.00 ile gösterdi ve kaynağını `urgup.md` verdi.
- Aynı konuyu farklı kelimelerle anlatan cümleler (örn. "Göreme balon kalkışlarına
  yakındır…" ≈ `urgup.md`'nin konaklama cümlesi) sözcüksel örtüşmesi 0.00 olduğu için
  kopya sayılmadı — yalnız "en tekrarlı" listesinde novelty 0.27 ile göründü.
- Ortalama anlamsal farklılık 0.351. Aynı konudaki sayfalar birbirine yakın olduğu için
  bu sayı hedef değil; asıl çıktı sözcüksel kopya uyarısı.

## topical_graph.py — kapsama boşluğu

```
python scripts/topical_graph.py --files "examples/*.md" --target examples/otel.md
```

- Sütun varlıklar (PageRank): Göreme (4 dokümanda), Nevşehir (3), Kapadokya (3),
  Ürgüp (2), Uçhisar (2).
- `otel.md`'de "Nevşehir" hiç geçmiyor, diğer üç sayfada geçiyor. Rapor bunu tek
  kapsama boşluğu olarak buldu (df=3, pr=0.1375).
- Sentetik kontrol: korpusta "Van" (df=2), hedef metinde yalnız "Vanilya" geçiyorsa
  boşluk `✗ Van df=2` olarak çıkıyor. Düzeltme öncesi karakter içermesi yüzünden
  ("van" ⊂ "vanilya") bu boşluk "belirgin boşluk yok" diye GİZLENİYORDU.

## entity_salience.py — varsayılan label'lar ve recall

```
python scripts/entity_salience.py --file examples/otel.md --query "kapadokya otel"
```

- Varsayılan label setiyle yalnız 4 yer adı çıktı: Kapadokya (100.0), Göreme (95.2),
  Ürgüp (35.2), Uçhisar (34.6).
- "otel" metinde geçtiği halde varlık sayılmadı. Kapsama raporu bunu **`○ metinde
  geçiyor, varlık tanınmadı`** durumunda gösteriyor — "EKSİK" demiyor, yani ekleme
  kararı yanlış tetiklenmiyor. `--threshold` 0.45 → 0.3 → 0.2 sonucu değiştirmedi.
- `--second-pass` ile "otel" label olarak eklenince ikinci geçişte "mağara oteldir"
  (tür: otel) salience 49.0 ile çıktı.
- `--preset konaklama` ile aynı sorgu `✓ otel salience 58` verdi; "ulaşımı",
  "havalimanı transferi", "toplu taşıma" da yakalandı (8 varlık).
- Sonuç: recall'ın kökü label setidir, eşik değil.

## tr_lemma.py — çekim eki

Doğrudan `lemmatize_phrase` ile:

| Girdi | Lemma |
|---|---|
| Otele, otelde, Otelin, oteli, otelleri | otel |
| kahvaltının | kahvaltı |
| mağara oteldir | mağara otel |
| Kapadokya, Göreme, Ürgüp, Uçhisar, Nevşehir | değişmedi |

Bu örnek metinde GLiNER çekimli "otel" formlarını ayrı varlık olarak çıkarmadığı için
lemma açık/kapalı entity listesi aynı çıktı. Lemmanın etkisi Wikidata aramasında
görünüyor.

## Wikidata bağlama — çekimli form vs lemma

`wikidata_link` ile tek tek sorgu (Türkçe arama):

| Arama terimi | Sonuç |
|---|---|
| Otele | Q7110091 — village in Cameroon |
| otel | Q27686 — konaklama yeri |
| kahvaltının | eşleşme yok |
| kahvaltı | Q80973 — first meal of the day |
| Ürgüp | Q335010 — Nevşehir'in ilçesi |
| Uçhisar | Q1575197 — Nevşehir'e bağlı belde |

Çekimli formla arama yanlış düğüme gidiyor ya da boş dönüyor; bu yüzden `--link`
arama terimini lemma'dan üretir.

## Wikidata rate limit

Art arda birkaç `--link` çalıştırmasından sonra Wikidata HTTP 429 (Too Many
Requests) döndü. Rapor bu durumda hata göstermez; ilgili varlıklar QID'siz görünür.
Bir dakikalık beklemeden sonra aynı sorgular normal cevap verdi.

## Regresyon testleri

```
python -m unittest discover -s tests
```

25 test, model/indirme gerektirmiyor. Yukarıdaki düzeltmelerin her biri bir testle
korunuyor: karakter içerme eşleşmesi, offset'ten cümle ataması, chunk offset kayması,
özel isim birleştirmesi, uzun cümlenin kuyruğunun atılması, korpus tavanının
dengesiz dolması, parafrazın kopya sayılması, boilerplate ayıklama.
