"""Wide and tall station logos must survive square frontend artwork tiles."""

import importlib.util
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

spec = importlib.util.spec_from_file_location(
    "tivimuse_artwork",
    Path(__file__).parents[1] / "custom_components/tivimuse/artwork.py",
)
artwork = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artwork)


class ArtworkTest(unittest.TestCase):
    def test_wide_and_tall_logos_fit_without_cropping_or_distortion(self):
        for size in [(900, 150), (150, 900), (400, 400)]:
            source = Image.new("RGBA", size, "red")
            raw = BytesIO()
            source.save(raw, format="PNG")
            data, content_type = artwork.fit_logo(raw.getvalue())
            result = Image.open(BytesIO(data))
            self.assertEqual(result.size, (512, 512))
            self.assertEqual(content_type, "image/png")
            left, top, right, bottom = result.getbbox()
            self.assertGreaterEqual(left, 16)
            self.assertGreaterEqual(top, 16)
            self.assertLessEqual(right, 496)
            self.assertLessEqual(bottom, 496)
            self.assertAlmostEqual((right - left) / (bottom - top), size[0] / size[1], places=2)

    def test_invalid_artwork_is_omitted(self):
        self.assertIsNone(artwork.fit_logo(b"not an image"))
