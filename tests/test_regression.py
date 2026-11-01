#!/usr/bin/env python3
"""
Regresyon testleri — model/indirme GEREKTİRMEZ (saf fonksiyonlar, stdlib).

  python -m unittest discover -s tests

Kapsanan hatalar:
  * karakter içerme ile eşleşme ("Van" ↔ "vanilya")
  * cümleyi metinde tekrar arayarak bulma (GLiNER offset'i yerine)
  * chunk'ı cümleleri boşlukla birleştirerek kurma (offset kayması)
  * özel isimde token-içerme ile birleştirme ("Ankara" ↔ "Ankara Üniversitesi")
  * varlık sayılmayan ama metinde GEÇEN kelimeyi "EKSİK" göstermek
"""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from entitykit import cli, entity_salience as es, info_gain, tr_lemma

LEMMA = tr_lemma.available()


class ChunkOffsets(unittest.TestCase):
    """chunk_spans ham metinden dilimlemeli; base + p['start'] gerçek konum olmalı."""

    TEXT = ("Kapadokya'da mağara otelleri var.\n\n"
            "Göreme merkezdedir.\n\n"
            "Van ise bambaşka bir şehirdir.\n\n"
            "Vanilya dondurma da severim.")

    def test_chunk_raw_slice(self):
        for chunk, base in es.chunk_spans(self.TEXT, max_words=50):
            self.assertEqual(chunk, self.TEXT[base:base + len(chunk)])

    def test_offset_points_at_surface(self):
        # birden çok pencerede de offset doğru: her cümle kendi penceresinde
        for chunk, base in es.chunk_spans(self.TEXT, max_words=4):
            local = chunk.find("Van")
            if local >= 0:
                self.assertEqual(self.TEXT[base + local:base + local + 3], "Van")


class SentenceAttachment(unittest.TestCase):
    """Varlık, offset'inin düştüğü cümleye bağlanmalı; substring aramasıyla değil."""

    TEXT = "Van ise bambaşka bir şehirdir. Vanilya dondurma da severim."

    def setUp(self):
        self.sents = es.split_sentences(self.TEXT)
        self.ents = {"van": {"surface": "Van", "count": 1,
                             "offsets": [self.TEXT.index("Van")]}}

    def test_van_not_attached_to_vanilya(self):
        es.attach_sentences(self.ents, self.TEXT, self.sents)
        sents = self.ents["van"]["sents"]
        self.assertEqual(len(sents), 1)
        self.assertIn("şehirdir", sents[0])
        self.assertNotIn("Vanilya", sents[0])

    def test_multiple_occurrences_are_distinct_sentences(self):
        t = "Göreme güzeldir. Ürgüp de öyle. Göreme yine güzeldir."
        ents = {"goreme": {"surface": "Göreme", "count": 2,
                           "offsets": [t.index("Göreme"), t.rindex("Göreme")]}}
        es.attach_sentences(ents, t, es.split_sentences(t))
        self.assertEqual(len(ents["goreme"]["sents"]), 2)
        self.assertTrue(all("Ürgüp" not in s for s in ents["goreme"]["sents"]))


class RawTextCheck(unittest.TestCase):
    """'metinde geçiyor mu' kontrolü kelime sınırlı olmalı."""

    def test_van_is_not_in_vanilya(self):
        tokset, joined = es.lemma_tokens("Vanilya dondurma da severim.", LEMMA)
        self.assertFalse(es.in_raw_text("van", tokset, joined))

    def test_word_is_found(self):
        tokset, joined = es.lemma_tokens("Van ise bambaşka bir şehirdir.", LEMMA)
        self.assertTrue(es.in_raw_text("van", tokset, joined))

    def test_multiword_needs_adjacency(self):
        tokset, joined = es.lemma_tokens("mağara otel konforlu.", LEMMA)
        self.assertTrue(es.in_raw_text("magara otel", tokset, joined))
        tokset, joined = es.lemma_tokens("otel mağara değildir.", LEMMA)
        self.assertFalse(es.in_raw_text("magara otel", tokset, joined))

    @unittest.skipUnless(LEMMA, "zeyrek yok — lemmatizasyon kapalı")
    def test_inflected_form_is_found(self):
        tokset, joined = es.lemma_tokens("Otelde kahvaltının tadı iyiydi.", True)
        self.assertTrue(es.in_raw_text("otel", tokset, joined))
        # anahtar daima ent_key/norm çıktısıdır (norm "ı"yı korur, "ğ"yi sadeleştirir)
        self.assertTrue(es.in_raw_text(es.ent_key("kahvaltının", True), tokset, joined))
        self.assertTrue(es.in_raw_text("kahvaltı", tokset, joined))


class KeyMatch(unittest.TestCase):
    """Aday ↔ mevcut varlık eşleşmesi token-set düzeyinde olmalı."""

    def test_no_substring_match(self):
        self.assertIsNone(es.key_match("van", {"vanilya", "dondurma"}))

    def test_token_subset_match(self):
        self.assertEqual(es.key_match("otel", {"magara otel"}), "magara otel")

    def test_exact_match(self):
        self.assertEqual(es.key_match("otel", {"otel", "magara otel"}), "otel")


class ShouldMerge(unittest.TestCase):
    """Özel isimler token-içermeyle birleşmemeli; --enrich kavramları birleştirebilir."""

    def _tok(self, s):
        return set(s.split())

    def test_proper_noun_not_merged_by_containment(self):
        self.assertFalse(es.should_merge(self._tok("ankara"),
                                         self._tok("ankara universitesi"),
                                         "yer", "kuruluş", 0.80, 0.93))
        self.assertFalse(es.should_merge(self._tok("goreme"),
                                         self._tok("goreme belediyesi"),
                                         "yer", "yer", 0.88, 0.93))

    def test_concept_merged_by_containment(self):
        self.assertTrue(es.should_merge(self._tok("otel"),
                                        self._tok("magara otel"),
                                        "kavram", "kavram", 0.60, 0.93))

    def test_disjoint_tokens_not_merged(self):
        self.assertFalse(es.should_merge(self._tok("van"), self._tok("vanilya"),
                                         "yer", "kavram", 0.70, 0.93))

    def test_embedding_merge_only_non_proper_same_label(self):
        self.assertTrue(es.should_merge(self._tok("kahvalti"), self._tok("sabah yemegi"),
                                        "kavram", "kavram", 0.95, 0.93))
        # iki ayrı yer adı embedding'de çok yakın olsa da birleşmemeli
        self.assertFalse(es.should_merge(self._tok("urgup"), self._tok("uchisar"),
                                         "yer", "yer", 0.95, 0.93))



class SplitUnits(unittest.TestCase):
    """Uzun cümlenin kuyruğu ATILMAMALI; ne atlandığı sayılmalı."""

    def setUp(self):
        self.ig = info_gain

    def test_long_sentence_is_split_not_truncated(self):
        words = [f"kelime{i}" for i in range(150)]
        units, stats = self.ig.split_units(" ".join(words) + ".")
        self.assertEqual(stats["long_split"], 1)
        self.assertGreater(len(units), 1)
        # hiçbir kelime kaybolmamalı
        got = " ".join(units).replace(".", "").split()
        self.assertEqual(len(got), 150)
        self.assertEqual(got[-1], "kelime149")

    def test_short_units_counted_not_silent(self):
        units, stats = self.ig.split_units("Kısa.\nBu cümle yeterince uzun sayılır tam.")
        self.assertEqual(stats["short_skipped"], 1)
        self.assertEqual(len(units), 1)


class BalancedSample(unittest.TestCase):
    """Korpus tavanı kaynaklar arasında dengeli dolmalı."""

    def setUp(self):
        self.ig = info_gain

    def test_cap_is_shared_between_sources(self):
        per_doc = [("a", [f"a{i}" for i in range(100)]), ("b", [f"b{i}" for i in range(100)])]
        out = self.ig.balanced_sample(per_doc, 10)
        self.assertEqual(len(out), 10)
        owners = [o for _, o in out]
        self.assertEqual(owners.count("a"), 5)
        self.assertEqual(owners.count("b"), 5)

    def test_short_source_does_not_block(self):
        per_doc = [("a", ["a1"]), ("b", [f"b{i}" for i in range(5)])]
        out = self.ig.balanced_sample(per_doc, 100)
        self.assertEqual(len(out), 6)


class LexicalLayer(unittest.TestCase):
    """Kopya iddiası sözcüksel kanıt ister; parafraz sözcüksel olarak DÜŞÜK olmalı."""

    def setUp(self):
        self.ig = info_gain

    def test_identical_sentence_is_one(self):
        s = "Bölgede gezmek için en rahat yol araç kiralamaktır çünkü kasabalar uzak"
        (ratio, j), = self.ig.lexical_best([s], [s])
        self.assertEqual(j, 0)
        self.assertGreaterEqual(ratio, self.ig.LEX_EXACT)

    def test_paraphrase_is_low(self):
        a = "Bölgede gezmek için en rahat yol araç kiralamaktır"
        b = "Gezerken otomobil tutmak en konforlu seçenektir bence"
        (ratio, _), = self.ig.lexical_best([a], [b])
        self.assertLess(ratio, self.ig.LEX_HIGH)

    def test_punctuation_and_case_ignored(self):
        a = "Otele varmadan önce ulaşımı netleştirin, sonra rezervasyon yapın"
        b = "OTELE VARMADAN ÖNCE ULAŞIMI NETLEŞTİRİN; SONRA REZERVASYON YAPIN."
        (ratio, _), = self.ig.lexical_best([a], [b])
        self.assertGreaterEqual(ratio, self.ig.LEX_EXACT)


class MainContent(unittest.TestCase):
    """Boilerplate atılmalı; <main>/<article> varsa yalnız o alınmalı."""

    def test_nav_and_footer_stripped(self):
        html = ("<html><body><nav>Anasayfa Oteller İletişim</nav>"
                "<p>Mağara otelleri kayaya oyulmuştur.</p>"
                "<footer>Telif hakkı 2026 Tüm hakları saklıdır</footer></body></html>")
        txt = es.main_content(html)
        self.assertIn("Mağara otelleri", txt)
        self.assertNotIn("Anasayfa", txt)
        self.assertNotIn("Telif", txt)

    def test_main_preferred(self):
        html = ("<body><div>menü menü menü</div><main><p>Asıl içerik burada.</p></main>"
                "<div>alt bilgi</div></body>")
        txt = es.main_content(html)
        self.assertEqual(txt, "Asıl içerik burada.")

    def test_articles_joined_when_no_main(self):
        html = "<body><article>Birinci yazı.</article><article>İkinci yazı.</article></body>"
        txt = es.main_content(html)
        self.assertIn("Birinci yazı.", txt)
        self.assertIn("İkinci yazı.", txt)


try:
    import numpy as _np
except ImportError:
    _np = None


class _OneHotEmb:
    """Model yerine: her metne ayrı birim vektör (birleştirme yalnız token-set'le)."""

    def encode(self, xs, **kw):
        xs = [xs] if isinstance(xs, str) else xs
        return _np.eye(len(xs), max(len(xs), 2))


class _SameEmb:
    """Model yerine: her metne aynı vektör (cosine 1)."""

    def encode(self, xs, **kw):
        xs = [xs] if isinstance(xs, str) else xs
        return _np.ones((len(xs), 2)) / _np.sqrt(2)


@unittest.skipUnless(_np, "numpy yok")
class MergeKeepsLemmaKey(unittest.TestCase):
    """--enrich sonrası anahtar lemma'lı kalmalı; yoksa --query var olanı eksik sayar."""

    def _ent(self, surface, label):
        return {"surface": surface, "count": 1, "labels": {label: 1},
                "score": 0.9, "first": 0, "sents": [surface]}

    def test_query_still_matches_after_merge(self):
        ents = {"magara otel": self._ent("mağara oteldir", "konaklama tesisi"),
                "goreme": self._ent("Göreme", "yer")}
        merged = es.merge_entities(_OneHotEmb(), ents)
        self.assertEqual(set(merged), {"magara otel", "goreme"})
        self.assertEqual(es.key_match("otel", set(merged)), "magara otel")


class ExcludeSelf(unittest.TestCase):
    """Taslak, rakiplerden dosya adıyla değil aynı dosya olup olmadığıyla çıkarılmalı."""

    def setUp(self):
        import tempfile
        self.ig = info_gain
        self.tmp = tempfile.TemporaryDirectory()
        self.a = os.path.join(self.tmp.name, "a", "otel.md")
        self.b = os.path.join(self.tmp.name, "b", "otel.md")
        for p in (self.a, self.b):
            os.makedirs(os.path.dirname(p))
            open(p, "w").close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_basename_other_dir_kept(self):
        out = self.ig.exclude_self([(self.a, ""), (self.b, "")], None, self.a)
        self.assertEqual([n for n, _ in out], [self.b])

    def test_url_trailing_slash(self):
        rivals = [("https://a.com/x/", ""), ("https://b.com/x", "")]
        out = self.ig.exclude_self(rivals, "https://a.com/x", None)
        self.assertEqual([n for n, _ in out], ["https://b.com/x"])


class NonUtf8Rival(unittest.TestCase):
    """UTF-8 olmayan rakip dosyası script'i çökertmemeli."""

    def test_load_rivals_does_not_raise(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "eski.txt")
            with open(p, "wb") as f:
                f.write(b"Kapadokya caf\xe9 \xff\xfe metni.")
            docs, failed = info_gain.load_rivals(None, p)
        self.assertEqual(len(docs), 1)
        self.assertIn("Kapadokya", docs[0][1])


@unittest.skipUnless(_np, "numpy yok")
class ShortCopyReported(unittest.TestCase):
    """MIN_WORDS uzunluğundaki birebir kopya raporda görünmeli, sessiz kalmamalı."""

    def test_five_word_copy_in_report(self):
        import io
        from contextlib import redirect_stdout
        s = "Göreme balon kalkışlarına çok yakındır."
        self.assertEqual(len(s.split()), info_gain.MIN_WORDS)
        buf = io.StringIO()
        with redirect_stdout(buf):
            info_gain.analyze(_SameEmb(), s, [("r.md", s)], 5)
        self.assertIn("BİREBİR EŞLEŞME", buf.getvalue())


class SourceHelpers(unittest.TestCase):
    """URL listesi ve glob açma, info_gain ile topical_graph'ta aynı davranmalı."""

    def test_url_list_inline_and_file(self):
        import tempfile
        self.assertEqual(es.read_url_list("https://a.com, https://b.com,"),
                         ["https://a.com", "https://b.com"])
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "urls.txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write("# yorum\nhttps://a.com\n\nhttps://b.com\n")
            self.assertEqual(es.read_url_list(p), ["https://a.com", "https://b.com"])

    def test_expand_globs_comma_and_space(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for n in ("a.md", "b.md", "c.txt"):
                open(os.path.join(d, n), "w").close()
            got = es.expand_globs(f"{d}/*.md, {d}/c.txt")
        self.assertEqual(sorted(os.path.basename(p) for p in got),
                         ["a.md", "b.md", "c.txt"])


class CliTranslate(unittest.TestCase):
    """İlk konumsal argüman girdi seçeneğine çevrilmeli; diğerleri olduğu gibi geçmeli."""

    def test_file_and_url(self):
        self.assertEqual(cli.translate("salience", ["a.md", "--query", "q"]),
                         ["--file", "a.md", "--query", "q"])
        self.assertEqual(cli.translate("gain", ["https://a.com/x", "--top", "3"]),
                         ["--url", "https://a.com/x", "--top", "3"])

    def test_explicit_flags_untouched(self):
        args = ["--file", "a.md", "--rival-files", "r/*.md"]
        self.assertEqual(cli.translate("gain", args), args)

    def test_graph_joins_shell_expanded_globs(self):
        self.assertEqual(cli.translate("graph", ["a.md", "b.md", "--target", "a.md"]),
                         ["--files", "a.md b.md", "--target", "a.md"])
        self.assertEqual(cli.translate("graph", ["https://a.com", "https://b.com"]),
                         ["--urls", "https://a.com,https://b.com"])

    def test_salience_takes_one_input(self):
        self.assertEqual(cli.translate("salience", ["a.md", "b.md"]),
                         ["--file", "a.md", "b.md"])

    def test_unknown_command_exit_code(self):
        import io
        from contextlib import redirect_stderr
        with redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["nope"]), 2)


if __name__ == "__main__":
    unittest.main()
