"""剪辑构成递归展开测试。"""

import unittest
from pathlib import Path

from mediaware.composition import CompositionError, expand
from mediaware.models import AssetRef
from mediaware.sources import load_catalog, load_composition

DATA = Path(__file__).resolve().parents[1] / "data"


class CompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(DATA / "catalog.csv")
        cls.rows = load_composition(DATA / "composition.csv")

    def test_flat_mix_expands_to_three_tracks(self):
        leaves = expand(AssetRef("F-44", "1"), self.rows, self.catalog)
        self.assertEqual(
            {(item.leaf.key(), item.part) for item in leaves},
            {("V-202@1", "picture"), ("A-410@1", "audio"), ("S-31@2", "caption")},
        )
        for item in leaves:
            self.assertEqual((item.root_in, item.root_out), (0, 80))
            self.assertEqual(item.length, 80)

    def test_surround_edition_uses_only_cited_subsegment(self):
        # A-117 原件 90 秒，只使用 10..90 这一段，权利也只能按这段查。
        leaves = expand(AssetRef("F-44", "3"), self.rows, self.catalog)
        audio = next(item for item in leaves if item.part == "audio")
        self.assertEqual(audio.leaf, AssetRef("A-117", "1"))
        self.assertEqual((audio.leaf_in, audio.leaf_out), (10, 90))
        self.assertEqual((audio.root_in, audio.root_out), (0, 80))

    def test_nested_programme_inherits_all_and_shifts_coordinates(self):
        leaves = expand(AssetRef("W-07", "1"), self.rows, self.catalog)
        by_part = {}
        for item in leaves:
            by_part.setdefault(item.part, []).append(item)
        # 前 20 秒只有画面 V-211；F-44 整体从成品第 20 秒接入。
        self.assertEqual([item.leaf.key() for item in by_part["picture"]],
                         ["V-211@1", "V-202@1"])
        nested_picture = next(
            item for item in by_part["picture"] if item.leaf.asset == "V-202"
        )
        self.assertEqual((nested_picture.root_in, nested_picture.root_out), (20, 100))
        self.assertEqual((nested_picture.leaf_in, nested_picture.leaf_out), (0, 80))
        # part=all 继承 F-44 内部各轨道，原件只在 F-44 段内出现。
        self.assertEqual({item.leaf.key() for item in by_part["audio"]}, {"A-410@1"})
        self.assertEqual({item.leaf.key() for item in by_part["caption"]}, {"S-31@2"})
        audio = by_part["audio"][0]
        self.assertEqual((audio.root_in, audio.root_out), (20, 100))

    def test_unknown_root_raises(self):
        with self.assertRaises(CompositionError):
            expand(AssetRef("NOPE", "9"), self.rows, self.catalog)


if __name__ == "__main__":
    unittest.main()
