# entitykit — doğrulama bulguları

Bu dosya, komutların `examples/` klasöründeki dört Türkçe gezi sayfasında verdiği
sonuçları listeler. Sonuçları şu sürümlerle aldık: GLiNER
`urchade/gliner_multiv2.1`, `BAAI/bge-m3`, gliner 0.2.27, transformers 5.6.2. Wikidata
sonuçları, sorgu anındaki API cevabıdır.

## İçindekiler

- [gain: kopya tespiti](#gain-kopya-tespiti)
- [graph: kapsama boşluğu](#graph-kapsama-boşluğu)
- [salience: varlık türleri ve eşik](#salience-varlık-türleri-ve-eşik)
- [tr_lemma: çekim ekleri](#tr_lemma-çekim-ekleri)
- [Wikidata: çekimli biçim ve kök](#wikidata-çekimli-biçim-ve-kök)
- [Wikidata hız sınırı](#wikidata-hız-sınırı)
- [Regresyon testleri](#regresyon-testleri)

## gain: kopya tespiti

```bash
entitykit gain examples/otel.md --rival-files "examples/*.md"
```

- KAPSAM satırı: Araç 4 kaynaktan 3'ünü rakip olarak ölçtü. Dördüncüsü taslağın
  kendisi olduğu için onu çıkardı. Taslakta 16, rakiplerde 39 birim var. Araç 5
  kelimeden kısa parçaları (çoğu başlık) atladı: taslakta 3, rakiplerde 9.
- `otel.md` ile `urgup.md` aynı cümleyi taşıyor: "Bölgede gezmek için en rahat yol
  araç kiralamaktır…". Rapor bu cümleyi **BİREBİR EŞLEŞME** altında gösterdi
  (lex=1.00, sem=1.00) ve kaynağını `urgup.md` olarak verdi.
- Aynı konuyu farklı kelimelerle anlatan cümleleri kopya saymadı. Örnek: "Göreme
  balon kalkışlarına yakındır…" cümlesi `urgup.md`'deki konaklama cümlesine yakın,
  ama sözcüksel örtüşmesi 0.00. Bu cümle yalnız "en tekrarlı" listesinde, novelty
  0.27 ile göründü.
- Ortalama anlamsal farklılık 0.376 çıktı. Aynı konudaki sayfalar birbirine yakındır.
  Bu yüzden bu sayı bir hedef değildir. Asıl çıktı, sözcüksel kopya uyarısıdır.

## graph: kapsama boşluğu

```bash
entitykit graph "examples/*.md" --target examples/otel.md
```

- Sütun varlıklar (PageRank sırasıyla): Göreme (4 sayfada), Nevşehir (3), Kapadokya
  (3), Uçhisar (3), Ürgüp (2).
- "Nevşehir" diğer üç sayfada geçiyor, `otel.md`'de hiç geçmiyor. Rapor bunu tek
  kapsama boşluğu olarak buldu (df=3, pr=0.1292).
- Yapay kontrol: Sayfa grubunda "Van" iki sayfada geçsin, hedef metinde yalnız
  "Vanilya" geçsin. Rapor boşluğu `✗ Van df=2` olarak gösteriyor. Eski sürüm harf
  dizisine bakıyordu ("van", "vanilya"nın içinde geçer) ve bu boşluğu gizliyordu.

## salience: varlık türleri ve eşik

```bash
entitykit salience examples/otel.md --query "kapadokya otel"
```

| Ayar | Bulunan varlık | "otel" durumu |
|---|---|---|
| Varsayılan türler, eşik 0.45 | 4 yer adı: Kapadokya (100.0), Göreme (96.1), Ürgüp (36.4), Uçhisar (36.1) | `○ tanınmadı` |
| Eşik 0.3 | 5 varlık; "Mağara otel" yer olarak eklendi (35.3) | `△ zayıf` (salience 35) |
| Eşik 0.2 | 6 varlık; "havalimanı transferi" de eklendi | `△ zayıf` (salience 35) |
| `--second-pass` | İkinci geçişte "mağara oteldir" otel türüyle çıktı (91.8) | — |
| `--preset konaklama` | 9 varlık; "mağara oteldir", "ulaşımı", "havalimanı transferi", "toplu taşıma" dahil | `✓ var` (salience 97) |

- Varsayılan türlerle "otel" metinde geçiyor, ama varlık sayılmıyor. Rapor bunu
  "eksik" olarak değil, `○ metinde geçiyor, varlık tanınmadı` olarak gösteriyor. Bu
  yüzden metne gereksiz ekleme yapma kararı doğmuyor.
- Eşiği düşürmek "otel"i zayıf bir varlık olarak buluyor. Doğru tür setini seçmek
  ise onu merkezi bir varlık olarak buluyor.
- Sonuç: Bu örnekte en güçlü etki tür setinden geliyor. Eşik de sonucu değiştiriyor,
  ama daha az.

## tr_lemma: çekim ekleri

`lemmatize_phrase` ile doğrudan:

| Girdi | Kök |
|---|---|
| Otele, otelde, Otelin, oteli, otelleri | otel |
| kahvaltının | kahvaltı |
| mağara oteldir | mağara otel |
| Kapadokya, Göreme, Ürgüp, Uçhisar, Nevşehir | değişmedi |

## Wikidata: çekimli biçim ve kök

`wikidata_link` ile tek tek, Türkçe arama:

| Arama terimi | Sonuç |
|---|---|
| Otele | Q7110091 — village in Cameroon |
| otel | Q27686 — konaklama yeri |
| kahvaltının | eşleşme yok |
| kahvaltı | Q80973 — first meal of the day usually eaten in the morning |
| Ürgüp | Q335010 — Nevşehir'in ilçesi |
| Uçhisar | Q1575197 — Nevşehir ilinin Merkez ilçesine bağlı bir belde |

Çekimli biçimle arama yanlış kayda gidiyor ya da boş dönüyor. Bu yüzden `--link`
arama terimini kökten üretir.

## Wikidata hız sınırı

Art arda birkaç `--link` çalıştırmasından sonra Wikidata HTTP 429 (Too Many
Requests) döndürdü. Rapor bu durumda hata göstermez, ilgili varlıklar QID'siz
görünür. Bir dakika bekledikten sonra aynı sorgular normal cevap verdi. Bu gözlem
ilk sürümün testinden gelir. Bu sürümde yeniden ölçmedik.

## Regresyon testleri

```bash
python -m unittest discover -s tests
```

37 test var ve hiçbiri model indirmiyor. Her test, düzeltilmiş bir hatanın geri
gelmesini engeller:

- harf dizisiyle eşleşme ("van" ↔ "vanilya")
- cümle atamasının konumdan yapılması
- metin parçalarında konum kayması
- özel adların birleşmemesi ("Ankara" ↔ "Ankara Üniversitesi")
- `--enrich` sonrası sorgu eşleşmesi
- uzun cümlenin sonunun atılmaması
- rakip örneklemenin kaynaklar arasında dengeli olması
- parafrazın kopya sayılmaması ve 5 kelimelik kopyanın raporda görünmesi
- taslağın rakiplerden aynı dosya kontrolüyle çıkarılması
- UTF-8 olmayan rakip dosyasının okunması
- URL listesi ve glob açma
- komut satırında girdinin doğru seçeneğe çevrilmesi
- menü, üst ve alt bilginin ayıklanması
