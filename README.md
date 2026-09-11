# entitykit

entitykit bir metindeki varlıkları (kişi, yer, kavram gibi) bulur ve ölçer, ama
metni değiştirmez.

Üç soruya cevap verir:

- **Bu metin hangi varlıklar etrafında dönüyor?** Hangisi merkezde, hangisi kenarda?
- **Bu metin başka sayfalarda olmayan ne söylüyor?** Hangi cümleler başka bir
  sayfanın neredeyse aynısı?
- **Bir grup sayfa hangi varlıklar üzerine kurulu?** Bir sayfada eksik kalan hangisi?

Türkçe metinler için ayarlı: varsayılan varlık türleri Türkçe ve çekim eklerini köke
indirir (Otele, otelde, otelin → otel).

## İçinde ne var

| Script | Ne yapar |
|---|---|
| `scripts/entity_salience.py` | varlıkları çıkarır ve metin içindeki ağırlıklarını sıralar; `--query` ile bir sorgudaki varlıkların metinde olup olmadığını, `--link` ile Wikidata karşılıklarını gösterir |
| `scripts/info_gain.py` | bir taslağın cümlelerini başka sayfalarla karşılaştırır; en özgün ve en tekrarlı cümleleri listeler, kopyayı üç düzeyde ayırır (birebir / sözcüksel / anlamsal) |
| `scripts/topical_graph.py` | bir grup sayfadaki varlıklardan bir ağ kurar; en merkezdeki varlıkları ve `--target` ile bir sayfada eksik olanları gösterir |
| `scripts/tr_lemma.py` | Türkçe kelimeleri köke indirir; diğer script'ler kullanır |

Kullanılan modeller: varlık bulma için GLiNER (`urchade/gliner_multiv2.1`), anlam
karşılaştırması için bge-m3. Wikidata sorgusu internet ister, anahtar istemez.

Tam iş akışı `SKILL.md` içinde. `references/findings.md` script'lerin örnek
dosyalarda verdiği sonuçları anlatıyor.

## Kurulum

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -c "import nltk; nltk.download('punkt_tab')"
```

Son satır gerekli, çünkü Türkçe kök bulma aracı bu veriyi ister. Modeller ilk
çalıştırmada iner.

## Deneme

`examples/` klasöründe Kapadokya üzerine dört kısa sayfa var. `otel.md` bilerek iki
kusurla yazıldı: bir cümlesi `urgup.md` ile aynı ve diğer sayfaların hepsinde geçen
"Nevşehir" bu sayfada hiç yok.

```bash
# otel.md'nin varlıkları
.venv/bin/python scripts/entity_salience.py --file examples/otel.md

# otel.md, diğer sayfalara göre ne katıyor?
.venv/bin/python scripts/info_gain.py \
  --file examples/otel.md --rival-files "examples/*.md"

# dört sayfanın varlık ağı; otel.md'de eksik olan ne?
.venv/bin/python scripts/topical_graph.py \
  --files "examples/*.md" --target examples/otel.md
```

`info_gain.py` ortak cümleyi `urgup.md`'nin kopyası olarak işaretler.
`topical_graph.py` ise "Nevşehir"i `otel.md`'nin eksiği olarak gösterir.

## Bilmen gerekenler

Skorlar görelidir. İki versiyonu ya da iki sayfayı karşılaştırmak için kullan,
geçti/kaldı notu gibi okuma.

Varlık bulma, hangi türleri aradığına bağlı. Varsayılan türler "otel" gibi genel
kavramları kaçırabilir; o zaman `--labels` ile tür ekle (örneğin "konaklama
tesisi") ya da hazır bir set seç: `--preset konaklama|urun|haber|teknoloji|genel`.

Kapsama raporu bu yüzden üç durumu ayırır: `✓/△` varlık olarak bulundu, `○` kelime
metinde geçiyor ama varlık sayılmadı (ekleme yapma, tür setini gevşet), `✗` metinde
de yok. `--second-pass` ○ adaylarını tür olarak ekleyip yeniden ölçer.

Karşılaştırmalarda kopya iddiası sözcüksel kanıta dayanır: `info_gain.py` birebir
eşleşmeyi ve ortak kelime dizilerini ayrı, salt anlam yakınlığını ayrı raporlar.
Raporun başındaki KAPSAM satırı kaç kaynağın okunduğunu, kaç birim ölçüldüğünü ve
neyin atlandığını söyler — eksik analiz tam analiz gibi görünmesin.

Sayfa çekerken (`--url`) menü, başlık ve alt bilgi atılır; `<main>`/`<article>` varsa
yalnız o okunur. Bu regex temelli bir ayıklama, `<div class="sidebar">` gibi blokları
temizlemez.

Çok sayıda `--link` sorgusundan sonra Wikidata bir süre cevap vermeyebilir. Bu
durumda bağlantılar boş görünür. Yine de sorun kalıcı değil: biraz bekleyip tekrar
çalıştır.

## Lisans

MIT
