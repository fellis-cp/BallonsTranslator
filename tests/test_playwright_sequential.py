import unittest
import json
import threading
import time
from ballontranslator.modules.translators.trans_playwrigt import (
    TranslationTask,
    TransGemini,
    _extract_json_block,
    _parse_or_repair_json,
    _extract_translations_from_data,
    _calculate_timeout,
    _sleep_with_stop,
    _build_results,
    DeepLBrowserWorker,
)

class TestPlaywrightSequential(unittest.TestCase):

    def test_concate_text_is_false(self):
        """Ensure concate_text is False so BaseTranslator passes raw block lists."""
        t = TransGemini(lang_source="English", lang_target="Bahasa Indonesia", raise_unsupported_lang=False)
        self.assertFalse(t.concate_text)

    def test_translation_task_mode(self):
        task_default = TranslationTask(["Hello"], "Indonesian", "", "English")
        self.assertEqual(task_default.mode, "Batch")

        task_seq = TranslationTask(["Hello"], "Indonesian", "", "English", mode="Sequential")
        self.assertEqual(task_seq.mode, "Sequential")

    def test_trans_gemini_mode_param(self):
        t = TransGemini(lang_source="English", lang_target="Bahasa Indonesia", raise_unsupported_lang=False)
        self.assertEqual(t.mode, "Batch")
        self.assertIn("mode", t.params)
        self.assertEqual(t.params["mode"]["options"], ["Batch", "Sequential"])

        t.updateParam("mode", "Sequential")
        self.assertEqual(t.mode, "Sequential")

    def test_single_item_json_parsing(self):
        item_id = 1
        token = "ID_1_abcd"
        raw_json = json.dumps({
            "batch_id": token,
            "translations": [{"id": item_id, "translation": "Halo Dunia"}]
        })
        extracted = _extract_json_block(raw_json)
        res = _parse_or_repair_json(extracted, instance_id=1)
        self.assertIsNotNone(res)
        self.assertEqual(res["translations"][0]["id"], 1)
        self.assertEqual(res["translations"][0]["translation"], "Halo Dunia")

    def test_key_as_id_contract_parsing(self):
        """Align with BallonsTranslator LLM contract: {"1": "Halo Dunia", "2": "Baris Dua"}."""
        raw_json = json.dumps({
            "1": "Halo Dunia",
            "2": "Baris Dua"
        })
        extracted = _extract_json_block(raw_json)
        res = _parse_or_repair_json(extracted, instance_id=1)
        self.assertIsNotNone(res)
        translations = res["translations"]
        self.assertEqual(len(translations), 2)
        self.assertEqual(translations[0], {"id": 1, "translation": "Halo Dunia"})
        self.assertEqual(translations[1], {"id": 2, "translation": "Baris Dua"})

    def test_extract_translations_formats(self):
        # Format 1: dict with key as ID {"translations": {"1": "A", "2": "B"}}
        t1 = _extract_translations_from_data({"translations": {"1": "A", "2": "B"}})
        self.assertEqual(t1["translations"], [{"id": 1, "translation": "A"}, {"id": 2, "translation": "B"}])

        # Format 2: single dict {"translation": "Single"}
        t2 = _extract_translations_from_data({"translation": "Single"})
        self.assertEqual(t2["translations"], [{"id": 1, "translation": "Single"}])

        # Format 3: plain list of strings ["A", "B"]
        t3 = _extract_translations_from_data(["A", "B"])
        self.assertEqual(t3["translations"], [{"id": 1, "translation": "A"}, {"id": 2, "translation": "B"}])

        # Format 4: list of dicts [{"id": 1, "translation": "A"}]
        t4 = _extract_translations_from_data([{"id": 1, "translation": "A"}])
        self.assertEqual(t4["translations"], [{"id": 1, "translation": "A"}])

    def test_sequential_build_results(self):
        # Direct list without ## (standard concate_text=False behavior)
        src_list_direct = ["First line", "Second line", "Third line"]
        translations_direct = [
            {"id": 1, "translation": "Baris Pertama"},
            {"id": 2, "translation": "Baris Kedua"},
            {"id": 3, "translation": "Baris Ketiga"}
        ]
        res_direct = _build_results(src_list_direct, translations_direct)
        self.assertEqual(res_direct, ["Baris Pertama", "Baris Kedua", "Baris Ketiga"])

        # Backward compatibility: text containing ##
        src_list_split = ["First line ## Second line", "Third line"]
        translations_split = [
            {"id": 1, "translation": "Baris Pertama"},
            {"id": 2, "translation": "Baris Kedua"},
            {"id": 3, "translation": "Baris Ketiga"}
        ]
        res_split = _build_results(src_list_split, translations_split)
        self.assertEqual(res_split, [
            "Baris Pertama ## Baris Kedua",
            "Baris Ketiga"
        ])

    def test_stop_event_handling(self):
        t = TransGemini(lang_source="English", lang_target="Bahasa Indonesia", raise_unsupported_lang=False)
        stop_event = threading.Event()
        t.set_stop_event(stop_event)
        self.assertEqual(t.stop_event, stop_event)

        # _sleep_with_stop should return immediately when stopped
        stop_event.set()
        start = time.time()
        interrupted = _sleep_with_stop(5.0, stop_event)
        elapsed = time.time() - start
        self.assertTrue(interrupted)
        self.assertLess(elapsed, 0.5)

    def test_calculate_timeout(self):
        # Base timeout scales dynamically with item count and character count
        t_batch_1 = _calculate_timeout(["Hello"], base_timeout=60, mode="Batch")
        t_batch_long = _calculate_timeout(["A" * 2000], base_timeout=60, mode="Batch")
        self.assertGreater(t_batch_long, t_batch_1)

        t_seq_1 = _calculate_timeout(["Hello"], base_timeout=60, mode="Sequential")
        t_seq_5 = _calculate_timeout(["Hello"] * 5, base_timeout=60, mode="Sequential")
        self.assertGreater(t_seq_5, t_seq_1)
        self.assertGreaterEqual(t_seq_5, 60)

    def test_deepl_lang_mapping(self):
        self.assertEqual(DeepLBrowserWorker._map_lang_code("日本語"), "ja")
        self.assertEqual(DeepLBrowserWorker._map_lang_code("English"), "en")
        self.assertEqual(DeepLBrowserWorker._map_lang_code("简体中文"), "zh")
        self.assertEqual(DeepLBrowserWorker._map_lang_code("繁體中文"), "zh")
        self.assertEqual(DeepLBrowserWorker._map_lang_code("Bahasa Indonesia"), "id")
        self.assertEqual(DeepLBrowserWorker._map_lang_code("auto"), "auto")

if __name__ == '__main__':
    unittest.main()
