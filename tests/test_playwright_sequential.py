import unittest
import json
from ballontranslator.modules.translators.trans_playwrigt import (
    TranslationTask,
    TransGemini,
    _extract_json_block,
    _parse_or_repair_json,
    _build_results
)

class TestPlaywrightSequential(unittest.TestCase):

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

    def test_sequential_build_results(self):
        src_list = ["First line ## Second line", "Third line"]
        collected_translations = [
            {"id": 1, "translation": "Baris Pertama"},
            {"id": 2, "translation": "Baris Kedua"},
            {"id": 3, "translation": "Baris Ketiga"}
        ]
        results = _build_results(src_list, collected_translations)
        self.assertEqual(results, [
            "Baris Pertama ## Baris Kedua",
            "Baris Ketiga"
        ])

if __name__ == '__main__':
    unittest.main()
