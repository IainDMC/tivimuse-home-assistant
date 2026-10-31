"""Optional movie/show artwork for Nuvio and SmartTube; never used for live TV."""

from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher
from io import BytesIO

import aiohttp
from PIL import Image, ImageOps, ImageStat


class PosterURL(str):
    """A poster URL retaining the original movie/show classification."""

    def __new__(cls, value, media_type):
        instance = super().__new__(cls, value)
        instance.media_type = media_type
        return instance


def app_kind(value):
    marker = str(value or "").casefold()
    if "tivimuse" in marker or marker == "app.opentv.debug":
        return "tivimuse"
    if "nuvio" in marker:
        return "nuvio"
    if any(x in marker for x in ("smarttube", "teamsmart", "liskovsoft")):
        return "smarttube"
    return None


def nuvio_type(attributes):
    for name in ("is_trailer", "media_is_trailer", "trailer"):
        if str(attributes.get(name, "")).casefold() in ("true", "yes", "1"):
            return "Trailer"
    for name in ("media_content_type", "media_type", "content_type", "media_class"):
        value = str(attributes.get(name, "")).casefold().replace("_", " ").replace("-", " ")
        if value in ("trailer", "preview", "movie trailer", "tv trailer"):
            return "Trailer"
        if value in ("movie", "film"):
            return "Movie"
        if value in ("tv", "show", "tv show", "tvshow", "series", "tv series", "episode", "season"):
            return "Episode"
    if any(
        attributes.get(x) is not None
        for x in ("media_series_title", "media_season", "media_episode")
    ):
        return "Episode"
    artist = str(attributes.get("media_artist", ""))
    if re.search(r"\bS\d+\s*:\s*E\d+\b", artist, re.IGNORECASE):
        return "Episode"
    if re.fullmatch(r"(?:19|20)\d{2}", artist):
        return "Movie"
    return "Unknown"


def unmodified_image(data):
    """Preserve source/app artwork bytes, format, dimensions and transparency."""
    try:
        with Image.open(BytesIO(data)) as source:
            content_type = Image.MIME.get(source.format, "image/png")
            source.verify()
        return data, content_type
    except (OSError, ValueError, Image.DecompressionBombError):
        return None, None


def fit_poster(data, blurred=False, width_percent=100):
    """Use the original compositor only when its blurred-poster option is on."""
    if not blurred:
        return unmodified_image(data)
    try:
        return compose_poster(data, True, None, width_percent), "image/png"
    except (OSError, ValueError, Image.DecompressionBombError):
        return None, None


async def tmdb_poster(session, token, title, content_type, language, minimum_match=60):
    """Only search on an explicit opt-in, with the key in an authorization header."""
    if not token or not title:
        return None
    kind = "multi"
    try:
        async with session.get(
            f"https://api.themoviedb.org/3/search/{kind}",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": title, "language": language, "include_adult": "false"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            if response.status != 200:
                return None
            results = (await response.json()).get("results", [])
        for item in results:
            if kind == "multi" and item.get("media_type") not in ("movie", "tv"):
                continue
            name = item.get("title") or item.get("name") or ""
            path = item.get("poster_path")
            if (
                SequenceMatcher(None, name.casefold().strip(), title.casefold().strip()).ratio()
                * 100
                >= minimum_match
                and isinstance(path, str)
                and path.startswith("/")
            ):
                return PosterURL("https://image.tmdb.org/t/p/w500" + path, item.get("media_type"))
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, AttributeError, TypeError):
        pass
    return None


async def fetch_artwork(session, url):
    """Read only explicit HTTP artwork, with timeout and memory bounds."""
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        return None

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status != 200:
                return None
            chunks, size = [], 0
            async for chunk in response.content.iter_chunked(65536):
                size += len(chunk)
                if size > 8 * 1024 * 1024:
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None


def style_logo(data, scale=100, shape="square", background="transparent"):
    """Apply the former channel-logo sizing/canvas controls to app-supplied artwork."""
    try:
        with Image.open(BytesIO(data)) as source:
            logo = source.convert("RGBA")
            bounds = logo.getbbox()
            if not bounds:
                return None, None
            logo = logo.crop(bounds)
            width, height = (910, 512) if shape == "16:9" else (512, 512)
            if shape == "preserve":
                fitted = ImageOps.contain(logo, (480, 480), Image.Resampling.LANCZOS)
                width, height = fitted.width + 32, fitted.height + 32
            size = max(10, min(100, scale)) / 100
            fitted = ImageOps.contain(
                logo,
                (max(1, round((width - 32) * size)), max(1, round((height - 32) * size))),
                Image.Resampling.LANCZOS,
            )
            automatic = (
                "white"
                if ImageStat.Stat(logo.convert("L"), logo.getchannel("A")).mean[0] < 128
                else "black"
            )
            color = {"white": "white", "black": "black", "automatic": automatic}.get(
                background, (0, 0, 0, 0)
            )
            canvas = Image.new("RGBA", (width, height), color)
            canvas.alpha_composite(
                fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2)
            )
            result = BytesIO()
            canvas.save(result, "PNG")
            return result.getvalue(), "image/png"
    except (OSError, ValueError, Image.DecompressionBombError):
        return None, None


# Original Remote 3 compositor (IainDMC, MIT); see NOTICE.
def compose_poster(
    original: bytes,
    blurred: bool = True,
    logo_bytes: bytes | None = None,
    width_percent: float = 100,
) -> bytes:
    """Sharp fitted poster over a blurred, edge-darkened square backdrop."""
    from PIL import Image, ImageFilter, ImageOps

    with Image.open(BytesIO(original)) as source:
        poster = ImageOps.exif_transpose(source).convert("RGB")
    size = 640
    width = round(size * max(100, min(200, float(width_percent))) / 100)
    canvas = ImageOps.fit(poster, (width, size), method=Image.Resampling.LANCZOS)
    canvas = (
        canvas.filter(ImageFilter.GaussianBlur(24)).convert("RGBA")
        if blurred
        else Image.new("RGBA", (width, size), (0, 0, 0, 255))
    )
    foreground = ImageOps.contain(poster, (size, size), method=Image.Resampling.LANCZOS)
    left = (width - foreground.width) // 2
    top = (size - foreground.height) // 2
    mask = Image.new("L", (width, size))
    pixels = mask.load()
    for y in range(size):
        for x in range(width):
            distance = max(
                (left - x) / max(left, 1),
                (x - left - foreground.width + 1) / max(left, 1),
                (top - y) / max(top, 1),
                (y - top - foreground.height + 1) / max(top, 1),
                0,
            )
            pixels[x, y] = round(255 * (0.15 + 0.30 * min(distance, 1)))
    canvas.alpha_composite(
        Image.composite(
            Image.new("RGBA", canvas.size, (0, 0, 0, 255)), Image.new("RGBA", canvas.size), mask
        )
    )
    canvas.paste(foreground, (left, top))
    if logo_bytes:
        try:
            with Image.open(BytesIO(logo_bytes)) as source:
                logo = source.convert("RGBA")
            bounds = logo.getbbox()
            if bounds:
                logo = logo.crop(bounds)
                logo = ImageOps.contain(
                    logo, (round(width * 0.75), 190), method=Image.Resampling.LANCZOS
                )
                position = ((width - logo.width) // 2, size - logo.height - 26)
                shadow = Image.new("RGBA", canvas.size)
                shadow.paste(
                    (0, 0, 0, 190),
                    (position[0], position[1], position[0] + logo.width, position[1] + logo.height),
                    logo.getchannel("A"),
                )
                canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(5)))
                canvas.alpha_composite(logo, position)
        except Exception:
            # Unsupported logos must not prevent the programme poster displaying.
            pass
    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG")
    return output.getvalue()
