---
name: entitykit
description: Measures entities in Turkish web content with GLiNER, bge-m3, networkx and Wikidata — entity salience and query coverage, information gain and copy detection against rival or own pages, and topical authority gaps across a page set. Read-only; it reports and never rewrites. Use when the user asks for entity, salience, information gain, originality versus competitors, topical authority, coverage gap or Wikidata linking analysis, or says "entity analizi", "varlık analizi", "içerik analizi", "salience ölç", "bilgi kazancı", "rakibe karşı özgünlük", "kapsama açığı", "knowledge graph bağla" or "entitykit".
---

# entitykit

`entitykit` komutunun üç alt komutu bir metni ölçer ve rapor verir. Komutlar metni
değiştirmez. Metni değiştirmek ayrı bir adımdır ve kullanıcının onayını ister.

## Hangi komut?

| Kullanıcının sorusu | Komut |
|---|---|
| Metin hangi varlıklar etrafında dönüyor? Sorgudaki varlıklar metinde var mı? | `entitykit salience` |
| Taslak rakiplerin ya da kendi sayfalarının üstüne ne katıyor? Kopya cümle var mı? | `entitykit gain` |
| Bir sayfa grubu hangi varlıklara dayanıyor? Hedef sayfada ne eksik? | `entitykit graph` |

## İş akışı

Bu listeyi cevabına kopyala ve adım adım işaretle:

```
- [ ] 1. Girdiyi belirle: --file ya da --url; rakipler ya da sayfa grubu
- [ ] 2. Komutu çalıştır
- [ ] 3. KAPSAM satırını ve atlanan kaynakları kontrol et
- [ ] 4. Sonucu raporla: ölçülen değer + sınır
- [ ] 5. Değişiklik öner; uygulamadan önce onay al
```

**Adım 1.** `entitykit --version` ile komutun kurulu olduğunu doğrula. Kurulu
değilse kur: `uv tool install git+https://github.com/nazim/entitykit`. Modeller
önbellekteyse ağ isteğini önlemek için `HF_HUB_OFFLINE=1` ver.

**Adım 2.** Komutu çalıştır, kaynak kodunu okuma. İlk argüman girdidir: dosya yolu ya
da `http(s)://` adresi.

```bash
# Varlıklar ve sorgu kapsaması
entitykit salience icerik.md --query "<sorgu>"
entitykit salience "https://site.com/sayfa" --query "<sorgu>" --link

# Bilgi kazancı ve kopya
entitykit gain taslak.md --rival-files "rakipler/*.md"
entitykit gain taslak.md --rival-urls "https://a.com,https://b.com"

# Sayfa grubu ve hedefteki eksikler
entitykit graph "site/*.md" --target taslak.md
```

Bir seçenekten emin değilsen `entitykit <komut> --help` çalıştır.

**Adım 3.** `gain` raporunun ilk satırı KAPSAM'dır. Okunamayan kaynak varsa
bunu kullanıcıya söyle. Eksik bir analizi tam analiz gibi sunma.

**Adım 4.** Kapsama durumlarını şöyle yorumla:

| Durum | Anlamı | Önerin |
|---|---|---|
| `✓ var` | Varlık bulundu, salience yeterli. | Değişiklik önerme. |
| `△ zayıf` | Varlık bulundu, metinde kenarda. | Konuya aitse öne çıkarmayı öner. |
| `○ tanınmadı` | Kelime metinde geçiyor, varlık sayılmadı. | Metne ekleme önerme. `--preset` ya da `--labels` ile yeniden ölç. |
| `✗ eksik` | Kelime metinde yok. | Konuya gerçekten aitse eklemeyi öner. |

`○` görürsen önce bu döngüyü uygula:

1. Konuya uygun preset ile yeniden çalıştır: `--preset konaklama|urun|haber|teknoloji|genel`.
2. Preset yoksa türleri kendin ver: `--labels "konaklama tesisi,ulaşım"`.
3. Hâlâ `○` ise `--second-pass` ile ölç.
4. Ancak bundan sonra `✗` ile `○` arasında karar ver.

**Adım 5.** Kullanıcı onay vermeden metne varlık ekleme, cümle silme ya da iç
bağlantı koyma. Önerin küçük olsun: anlamı bozan bir varlık ekleme, salience'ı
artırmaz, metni bozar.

## Raporlama kuralları

- Bütün ölçümler vekildir. Salience, Google NLP salience değildir. Novelty, gerçek
  bilgi kazancı değildir. PageRank, gerçek konu otoritesi değildir. Raporda bunu
  söyle.
- Skorlar görelidir. 0–100 ölçeği, aynı koşunun en güçlü varlığına göredir. İki
  koşuyu ya da iki sayfayı karşılaştırarak konuş. Tek bir skoru geçti/kaldı diye
  okuma.
- `gain` raporundaki ortalama anlamsal farklılık bir hedef değildir. Aynı konudaki
  sayfalar birbirine yakındır. Kopya iddiasını yalnız sözcüksel kanıta dayandır:
  birebir ya da yüksek sözcüksel eşleşme.
- Ağırlıklar (`SAL_W`), birleştirme eşiği (`MERGE_SIM`), zayıf sınırı (`WEAK_SAL`,
  40) ve `LEX_*` eşikleri ölçülmemiş varsayımlardır. Bunları kesin sınır gibi sunma.
- `--second-pass` tablosu ayrı bir koşudur. Skorlarını ilk tabloyla karşılaştırma.

## Seçenekler

| Seçenek | Komut | Ne zaman |
|---|---|---|
| `--preset <ad>` / `--labels "a,b"` | salience, graph | Varsayılan türler kavramı kaçırınca. `--labels`, `--preset`'in yerine geçer. |
| `--enrich` | salience | Aynı kavram parçalı çıkınca ("otel", "mağara otel"). Özel adlar birleşmez. |
| `--link` | salience | Wikidata QID gerekince. Arama terimi kökten üretilir. |
| `--no-lemma` | salience, graph | Kök bulmanın yanlış birleştirdiği durumlarda. |
| `--threshold <0-1>` | salience, graph | Varsayılan 0.45. Düşürmek daha çok ama daha zayıf varlık bulur. |

## Bilinen sınırlar

- GLiNER sıfır örnekle çalışır. Bulduğu varlıklar, verilen türlere bağlıdır.
- `--url`, `nav`, `header`, `footer`, `aside` ve `form` bloklarını atar. `<main>` ya
  da `<article>` varsa yalnız onu okur. `<div class="sidebar">` gibi blokları
  temizlemez.
- Çok sayıda `--link` sorgusunda Wikidata HTTP 429 döndürür. Bu durumda QID'ler boş
  görünür. Kullanıcıya bir süre bekleyip yeniden çalıştırmasını söyle.

## Kaynaklar

- Örnek sonuçlar ve ölçülmüş davranış: [references/findings.md](references/findings.md)
- Kurulum ve seçeneklerin tamamı: [README.md](README.md)

## Testler

Kodu değiştirdikten sonra repo kökünde çalıştır:

```bash
.venv/bin/python -m unittest discover -s tests
```

Testler model indirmez. Bir test başarısız olursa hatayı düzelt ve yeniden çalıştır.
