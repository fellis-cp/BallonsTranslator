import unittest
import os
import os.path as osp
import tempfile
import json
import shutil

from READER.core.scanner import scan_translated_directory, is_image_file, find_manga_in_dir
from READER.core.loader import load_manga_project, MangaPage, MangaProjectData


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
        self.assertEqual(manga.page_count, 2)
        self.assertTrue(manga.has_translation)
        self.assertEqual(manga.json_path, json_path)

    def test_loader(self):
        manga_dir = osp.join(self.tmp_dir, "TestVolume")
        os.makedirs(manga_dir)

        img_path = osp.join(manga_dir, "001.png")
        with open(img_path, "w") as f:
            f.write("mock_img")

        json_data = {
            "directory": manga_dir,
            "pages": {
                "001.png": [
                    {
                        "xyxy": [10, 20, 100, 80],
                        "text": ["Konichiwa"],
                        "translation": "Hello World",
                        "_bounding_rect": [10, 20, 90, 60],
                    }
                ]
            }
        }
        json_path = osp.join(manga_dir, "imgtrans_TestVolume.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f)

        proj_data = load_manga_project(manga_dir, json_path=json_path)
        self.assertEqual(proj_data.title, "TestVolume")
        self.assertEqual(proj_data.page_count, 1)

        page = proj_data.get_page(0)
        self.assertIsNotNone(page)
        self.assertEqual(page.page_name, "001.png")
        self.assertEqual(len(page.blocks), 1)

    def test_save(self):
        manga_dir = osp.join(self.tmp_dir, "SaveVolume")
        os.makedirs(manga_dir)
        with open(osp.join(manga_dir, "001.png"), "w") as f:
            f.write("mock_img")

        proj_data = load_manga_project(manga_dir)
        proj_data.pages[0].blocks.append({
            "xyxy": [0, 0, 10, 10],
            "text": ["Test"],
            "translation": "Updated Translation"
        })

        success = proj_data.save()
        self.assertTrue(success)
        self.assertTrue(osp.exists(proj_data.json_path))

        # Reload and verify
        reloaded = load_manga_project(manga_dir, json_path=proj_data.json_path)
        self.assertEqual(len(reloaded.pages[0].blocks), 1)


if __name__ == '__main__':
    unittest.main()

