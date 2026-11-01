# Changelog

Sürümler [SemVer](https://semver.org/lang/tr/) izler.

## 0.2.0 — 2026-11-01

- cli: `entitykit` komutu; alt komutlar `salience`, `gain`, `graph`; ilk argüman girdi
- cli: `python -m entitykit`; `--version`
- entity_salience: GLiNER ile varlık çıkarma; bge-m3 merkezilik, frekans ve konumla salience
- entity_salience: `--query` kapsama durumları `✓ △ ○ ✗`
- entity_salience: `--link` Wikidata QID, `--enrich` birleştirme, `--second-pass`, `--preset`
- info_gain: bge-m3 ile cümle novelty; 4-gram shingle ile birebir ve sözcüksel kopya
- info_gain: KAPSAM satırı; taslağı rakiplerden `samefile` ile çıkarma
- topical_graph: varlık eş-geçiş ağı, PageRank sütun varlıklar, `--target` kapsama boşluğu
- topical_graph: birden çok glob ve kabukta açılmış dosya listesi
- tr_lemma: zeyrek ile Türkçe kök bulma; NLTK `punkt_tab` eksikse ilk çalıştırmada iner
- packaging: `pyproject.toml`; `uv tool install` ile kurulum; `protobuf` bağımlılığı
- examples: Kapadokya üzerine dört gezi sayfası
- ci: GitHub Actions ile unittest
- tests: 37 regresyon testi; model indirmez
