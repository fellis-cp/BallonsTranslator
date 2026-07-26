import unittest
import json
from ballontranslator.modules.translators.trans_playwrigt import (
    _extract_json_block,
    _normalize_translations,
    _enhanced_local_repair,
    _parse_or_repair_json,
    _build_results,
    RepairTask,
    JsonRepairWorker
)

class TestJsonRepair(unittest.TestCase):

    def test_valid_json(self):
        raw = '{"translations": [{"id": 1, "translation": "Hello world"}]}'
        res = _enhanced_local_repair(raw)
        self.assertIsNotNone(res)
        self.assertEqual(res['translations'][0]['translation'], 'Hello world')

    def test_trailing_comma(self):
        raw = '{"translations": [{"id": 1, "translation": "Hello world"},]}'
        res = _enhanced_local_repair(raw)
        self.assertIsNotNone(res)
        self.assertEqual(res['translations'][0]['translation'], 'Hello world')

    def test_truncated_entry(self):
        raw = '{"translations": [{"id": 1, "translation": "First"}, {"id": 2, "translation": "Truncated'
        res = _enhanced_local_repair(raw)
        self.assertIsNotNone(res)
        self.assertEqual(len(res['translations']), 1)
        self.assertEqual(res['translations'][0]['translation'], 'First')

    def test_unescaped_inner_quotes(self):
        raw = '{"translations": [{"id": 1, "translation": "She said "Hello" to me"}, {"id": 2, "translation": "Next"}]}'
        res = _enhanced_local_repair(raw)
        self.assertIsNotNone(res)
        self.assertEqual(len(res['translations']), 2)
        self.assertEqual(res['translations'][0]['translation'], 'She said "Hello" to me')

    def test_string_id_and_key_variations(self):
        raw = '{"translations": [{"id": "1", "text": "Item 1"}, {"id": "2", "translated": "Item 2"}]}'
        res = _parse_or_repair_json(raw, 1)
        self.assertIsNotNone(res)
        self.assertEqual(res['translations'][0]['id'], 1)
        self.assertEqual(res['translations'][0]['translation'], 'Item 1')
        self.assertEqual(res['translations'][1]['id'], 2)
        self.assertEqual(res['translations'][1]['translation'], 'Item 2')

    def test_json_array_extraction(self):
        raw = 'Here is the response: [{"id": 1, "translation": "Array item"}]'
        extracted = _extract_json_block(raw)
        self.assertEqual(extracted, '[{"id": 1, "translation": "Array item"}]')
        res = _parse_or_repair_json(extracted, 1)
        self.assertIsNotNone(res)
        self.assertEqual(res['translations'][0]['translation'], 'Array item')

    def test_build_results_string_ids_and_length_mismatch(self):
        src_list = ["Hello ## World", "Goodbye"]
        translations = [
            {"id": "1", "translation": "Halo"},
            {"id": "2", "translation": "Dunia"}
            # Item 3 ("Goodbye") omitted by LLM
        ]
        res = _build_results(src_list, translations)
        self.assertEqual(res, ["Halo ## Dunia", "Goodbye"])

    def test_build_results_positional_fallback(self):
        src_list = ["Line 1", "Line 2"]
        translations = [
            {"text": "Translated 1"},
            {"text": "Translated 2"}
        ]
        res = _build_results(src_list, translations)
        self.assertEqual(res, ["Translated 1", "Translated 2"])

    def test_repair_worker(self):
        worker = JsonRepairWorker(instance_id=99)
        task = RepairTask(
            raw_json='{"translations": [{"id": 1, "translation": "Rescued item"},]}',
            expected_count=1
        )
        res = worker.repair(task.raw_json, task.expected_count)
        self.assertIsNotNone(res)
        self.assertEqual(res['translations'][0]['translation'], 'Rescued item')

if __name__ == '__main__':
    unittest.main()

