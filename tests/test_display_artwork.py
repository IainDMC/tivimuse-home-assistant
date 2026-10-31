"""Content classification and complete, uncropped movie artwork."""

import importlib.util
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

spec = importlib.util.spec_from_file_location(
    "display_artwork",
    Path(__file__).parents[1] / "custom_components/tivimuse/display_artwork.py",
)
artwork = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artwork)


class DisplayArtworkTest(unittest.TestCase):
    def test_channel_icon_size_canvas_and_background_controls(self):
        raw = BytesIO()
        Image.new("RGBA", (600, 200), "black").save(raw, "PNG")
        data, _ = artwork.style_logo(raw.getvalue(), 50, "16:9", "automatic")
        image = Image.open(BytesIO(data))
        self.assertEqual(image.size, (910, 512))
        self.assertEqual(image.getpixel((0, 0)), (255, 255, 255, 255))
        self.assertEqual(image.getpixel((455, 256)), (0, 0, 0, 255))

    def test_app_aliases_and_unknown_apps(self):
        for identity, expected in [
            ("app.opentv.debug", "tivimuse"),
            ("app.tivimuse", "tivimuse"),
            ("com.nuvio.app", "nuvio"),
            ("com.teamsmart.videomanager.tv", "smarttube"),
            ("com.liskovsoft.smarttubetv.beta", "smarttube"),
            ("launcher", None),
        ]:
            self.assertEqual(artwork.app_kind(identity), expected)

    def test_nuvio_movie_episode_and_trailer(self):
        for attrs, expected in [
            ({"media_content_type": "movie"}, "Movie"),
            ({"media_season": 0}, "Episode"),
            ({"media_artist": "S01:E03"}, "Episode"),
            ({"is_trailer": True, "media_content_type": "movie"}, "Trailer"),
            ({"media_artist": "2026"}, "Movie"),
            ({}, "Unknown"),
        ]:
            self.assertEqual(artwork.nuvio_type(attrs), expected)

    def test_source_artwork_is_not_resized_or_reframed(self):
        for size in [(200, 600), (600, 200)]:
            raw = BytesIO()
            Image.new("RGBA", size, (255, 0, 0, 100)).save(raw, "PNG")
            data, content_type = artwork.fit_poster(raw.getvalue(), False, 150)
            self.assertEqual(data, raw.getvalue())
            self.assertEqual(Image.open(BytesIO(data)).size, size)
            self.assertEqual(content_type, "image/png")
        self.assertEqual(artwork.fit_poster(b"broken image"), (None, None))

    def test_original_blurred_poster_geometry_and_darkening(self):
        raw = BytesIO()
        Image.new("RGB", (200, 600), "white").save(raw, "PNG")
        data, _ = artwork.fit_poster(raw.getvalue(), True, 150)
        image = Image.open(BytesIO(data))
        self.assertEqual(image.size, (960, 640))
        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.getpixel((480, 0)), (255, 255, 255))
        self.assertEqual(image.getpixel((480, 639)), (255, 255, 255))
        self.assertLess(image.getpixel((0, 320))[0], 220)
