"""Optional movie/show artwork for Nuvio and SmartTube; never used for live TV."""

from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher
from io import BytesIO

import aiohttp
from PIL import Image, ImageFilter, ImageOps, ImageStat


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


def fit_poster(data, blurred=False, width_percent=100):
    """Keep a complete poster on a square background suitable for Remote 3."""
    try:
        with Image.open(BytesIO(data)) as source:
            poster = ImageOps.exif_transpose(source).convert("RGBA")
            width = round(512 * max(100, min(200, width_percent)) / 100)
            if blurred:
                canvas = ImageOps.fit(poster, (width, 512), method=Image.Resampling.LANCZOS)
                canvas = canvas.filter(ImageFilter.GaussianBlur(24))
                canvas.alpha_composite(Image.new("RGBA", canvas.size, (0, 0, 0, 100)))
            else:
                canvas = Image.new("RGBA", (width, 512))
            fitted = ImageOps.contain(poster, (480, 480), Image.Resampling.LANCZOS)
            canvas.alpha_composite(
                fitted, ((width - fitted.width) // 2, (512 - fitted.height) // 2)
            )
            output = BytesIO()
            canvas.save(output, "PNG")
            return output.getvalue(), "image/png"
    except (OSError, ValueError, Image.DecompressionBombError):
        return None, None


async def tmdb_poster(session, token, title, content_type, language, minimum_match=60):
    """Only search on an explicit opt-in, with the key in an authorization header."""
    if not token or not title:
        return None
    kind = {"Movie": "movie", "Episode": "tv"}.get(content_type, "multi")
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
                return "https://image.tmdb.org/t/p/w500" + path
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
