import unittest
import os
import os.path as osp
import tempfile
import json
import shutil

from READER.core.scanner import (
    scan_translated_directory,
    is_image_file,
    find_manga_in_dir,
    save_manga_verification_status,
)


class TestReaderCore(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_is_image_file(self):
        self.assertTrue(is_image_file("page01.webp"))
        self.assertTrue(is_image_file("001.JPG"))
        self.assertTrue(is_image_file("test.png"))
        self.assertFalse(is_image_file("data.json"))
        self.assertFalse(is_image_file("readme.txt"))

    def test_scanner(self):
        # Create mock structure: TRANSLATED/Author A/Manga 1/
        manga1_dir = osp.join(self.tmp_dir, "Author A", "Manga 1")
        os.makedirs(manga1_dir)

        # Add image files
        with open(osp.join(manga1_dir, "001.webp"), "w") as f:
            f.write("mock_img_1")
        with open(osp.join(manga1_dir, "002.webp"), "w") as f:
            f.write("mock_img_2")

        # Add project JSON
        json_data = {
            "directory": manga1_dir,
            "pages": {
                "001.webp": [
                    {
                        "xyxy": [50, 50, 200, 200],
                        "text": ["Hello"],
                        "translation": "Translated Hello",
                    }
                ],
                "002.webp": []
            }
        }
        json_path = osp.join(manga1_dir, "imgtrans_Manga 1.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f)

        items = scan_translated_directory(self.tmp_dir)
        self.assertEqual(len(items), 1)

        manga = items[0]
        self.assertEqual(manga.title, "Manga 1")
        self.assertEqual(manga.author, "Author A")
        self.assertEqual(manga.page_count, 2)
        self.assertTrue(manga.has_translation)
        self.assertEqual(manga.json_path, json_path)

    def test_scanner_nested_series(self):
        # Create nested structure: TRANSLATED/Shigeatsu/Life Support 2/Chapter 1/
        chap1_dir = osp.join(self.tmp_dir, "Shigeatsu", "Life Support 2", "Chapter 1")
        os.makedirs(chap1_dir)
        with open(osp.join(chap1_dir, "001.jpg"), "w") as f:
            f.write("mock_img")

        items = scan_translated_directory(self.tmp_dir)
        self.assertEqual(len(items), 1)
        manga = items[0]
        self.assertEqual(manga.author, "Shigeatsu")
        self.assertEqual(manga.title, "Life Support 2 - Chapter 1")

    def test_save_verification_status(self):
        manga_dir = osp.join(self.tmp_dir, "Author B", "Manga 2")
        os.makedirs(manga_dir)
        with open(osp.join(manga_dir, "001.jpg"), "w") as f:
            f.write("mock_img")

        json_path = osp.join(manga_dir, "imgtrans_Manga 2.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"pages": {}}, f)

        items = scan_translated_directory(self.tmp_dir)
        manga = [it for it in items if it.title == "Manga 2"][0]
        self.assertEqual(manga.verification_status, "unverified")

        # Set to verified
        success = save_manga_verification_status(manga, "verified")
        self.assertTrue(success)
        self.assertEqual(manga.verification_status, "verified")

        # Verify persisted
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("verification_status"), "verified")


if __name__ == '__main__':
    unittest.main()
