from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import mimetypes
import os
import re
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ExtractorError


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
DOUYIN_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 aweme"
)
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
)

MEDIA_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".avif",
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".mkv",
    ".avi",
    ".mp3",
    ".m4a",
    ".wav",
}

URL_PATTERN = re.compile(r"https?://[^\s'\"<>，。；、）)】》\u4e00-\u9fff]+", re.IGNORECASE)
DOUYIN_ID_PATTERN = re.compile(r"/(?:share/)?(?P<kind>note|video|slides)/(?P<id>\d+)")
TWITTER_STATUS_PATTERN = re.compile(r"/status(?:es)?/(?P<id>\d+)", re.IGNORECASE)

SKIP_EXTENSIONS = {
    ".json",
    ".part",
    ".ytdl",
    ".tmp",
    ".description",
    ".vtt",
    ".srt",
}

MAX_FALLBACK_FILES = 20
MAX_FALLBACK_BYTES = int(os.getenv("MAX_DOWNLOAD_BYTES", str(1024 * 1024 * 1024)))


class ExtractionError(RuntimeError):
    pass


@dataclass
class MediaFile:
    filename: str
    kind: str
    size: int
    mime_type: str
    download_url: str


def get_download_root() -> Path:
    configured = os.getenv("DOWNLOAD_DIR")
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        root = Path(__file__).resolve().parents[1] / "downloads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_public_url(raw_url: str) -> str:
    url = extract_first_url(raw_url)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ExtractionError("请输入 http 或 https 开头的有效分享链接。")

    if os.getenv("ALLOW_PRIVATE_HOSTS", "").lower() in {"1", "true", "yes"}:
        return url

    host = parsed.hostname
    if not host:
        raise ExtractionError("链接缺少有效域名。")

    try:
        addresses = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ExtractionError(f"域名解析失败：{host}") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            raise ExtractionError("为安全起见，暂不支持解析内网、localhost 或本机地址。")

    return url


def extract_first_url(raw_value: str) -> str:
    value = raw_value.strip()
    match = URL_PATTERN.search(value)
    if match:
        return match.group(0).strip()
    return value


def file_kind(path: Path, content_type: str | None = None) -> str:
    mime = content_type or mimetypes.guess_type(path.name)[0] or ""
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return "file"


def content_type_extension(content_type: str | None, fallback: str = ".bin") -> str:
    if not content_type:
        return fallback
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime == "image/jpg":
        return ".jpg"
    if mime == "application/octet-stream":
        return fallback
    return mimetypes.guess_extension(mime) or fallback


def safe_filename(name: str, fallback: str) -> str:
    cleaned = unquote(name).split("?", 1)[0].split("#", 1)[0].strip()
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:140] or fallback


def media_url_from_path(root: Path, path: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return f"/media/{relative}"


class MediaDownloader:
    def __init__(self, download_root: Path | None = None):
        self.download_root = download_root or get_download_root()

    async def extract(self, raw_url: str) -> dict[str, Any]:
        return await self.resolve(raw_url)

    async def resolve(self, raw_url: str) -> dict[str, Any]:
        url = validate_public_url(raw_url)
        douyin_error: str | None = None
        ytdlp_error: str | None = None

        if self._is_douyin_url(url):
            try:
                return await self._resolve_from_douyin(url)
            except Exception as exc:
                douyin_error = self._human_error(exc)

        xiaohongshu_error: str | None = None
        if self._is_xiaohongshu_url(url):
            try:
                return await self._resolve_from_xiaohongshu(url)
            except Exception as exc:
                xiaohongshu_error = self._human_error(exc)

        dewu_error: str | None = None
        if self._is_dewu_url(url):
            try:
                return await self._resolve_from_dewu(url)
            except Exception as exc:
                dewu_error = self._human_error(exc)

        twitter_error: str | None = None
        if self._is_twitter_url(url):
            try:
                return await self._resolve_from_twitter(url)
            except Exception as exc:
                twitter_error = self._human_error(exc)
                raise ExtractionError(f"Twitter/X 解析失败：{twitter_error}") from exc

        try:
            return await asyncio.to_thread(self._resolve_with_ytdlp, url)
        except Exception as exc:
            ytdlp_error = self._human_error(exc)

        try:
            result = await self._resolve_from_html(url)
            result["warnings"].insert(0, f"yt-dlp 未能直接解析，已使用网页兜底解析：{ytdlp_error}")
            return result
        except Exception as exc:
            fallback_error = self._human_error(exc)
            platform_error = f"；抖音分享页解析：{douyin_error}" if douyin_error else ""
            platform_error += f"；小红书页面解析：{xiaohongshu_error}" if xiaohongshu_error else ""
            platform_error += f"；得物页面解析：{dewu_error}" if dewu_error else ""
            platform_error += f"；Twitter/X 页面解析：{twitter_error}" if twitter_error else ""
            raise ExtractionError(
                "解析失败。公开视频建议直接复制作品分享链接；需要登录的平台可配置 "
                f"YTDLP_COOKIE_FILE。yt-dlp：{ytdlp_error}{platform_error}；兜底解析：{fallback_error}"
            ) from exc

    def _create_job_dir(self) -> Path:
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        path = self.download_root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _download_with_ytdlp(self, url: str, job_dir: Path) -> dict[str, Any]:
        options: dict[str, Any] = {
            "outtmpl": str(job_dir / "%(extractor_key)s" / "%(id)s" / "%(title).120B.%(ext)s"),
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "noplaylist": False,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": False,
            "retries": 2,
            "fragment_retries": 2,
            "http_headers": {"User-Agent": USER_AGENT},
        }

        cookie_file = os.getenv("YTDLP_COOKIE_FILE")
        if cookie_file:
            options["cookiefile"] = cookie_file

        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)

        files = self._collect_files(job_dir)
        if not files:
            raise ExtractionError("解析成功但没有发现已下载的媒体文件。")

        return self._build_response(
            url=url,
            resolved_url=info.get("webpage_url") or url if isinstance(info, dict) else url,
            title=self._title_from_info(info),
            extractor=info.get("extractor_key") if isinstance(info, dict) else "yt-dlp",
            files=files,
            warnings=[],
        )

    def _resolve_with_ytdlp(self, url: str) -> dict[str, Any]:
        options: dict[str, Any] = {
            "format": "best",
            "noplaylist": False,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": False,
            "skip_download": True,
            "http_headers": {"User-Agent": USER_AGENT},
        }

        cookie_file = os.getenv("YTDLP_COOKIE_FILE")
        if cookie_file:
            options["cookiefile"] = cookie_file

        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=False)

        candidates = self._ytdlp_media_candidates(info)
        if not candidates:
            raise ExtractionError("yt-dlp 没有解析到可直接下载的媒体地址。")

        return self._build_response(
            url=url,
            resolved_url=info.get("webpage_url") or url if isinstance(info, dict) else url,
            title=self._title_from_info(info),
            extractor=info.get("extractor_key") if isinstance(info, dict) else "yt-dlp",
            files=[],
            warnings=[],
            remote_urls=candidates[:MAX_FALLBACK_FILES],
        )

    async def _resolve_from_html(self, url: str) -> dict[str, Any]:
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(30.0, connect=10.0),
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if self._is_media_response(url, content_type):
                return self._build_response(
                    url=url,
                    resolved_url=str(response.url),
                    title=self._filename_from_remote_url(str(response.url), content_type, "media"),
                    extractor="direct",
                    files=[],
                    warnings=[],
                    remote_urls=[str(response.url)],
                )

            soup = BeautifulSoup(response.text, "html.parser")
            title = self._html_title(soup) or str(response.url)
            candidates = self._html_media_candidates(soup, response.text, str(response.url))
            if not candidates:
                raise ExtractionError("页面中没有找到可直接下载的图片或视频地址。")

            return self._build_response(
                url=url,
                resolved_url=str(response.url),
                title=title,
                extractor="html-fallback",
                files=[],
                warnings=[],
                remote_urls=candidates[:MAX_FALLBACK_FILES],
            )

    async def _resolve_from_douyin(self, url: str) -> dict[str, Any]:
        async with httpx.AsyncClient(
            follow_redirects=False,
            headers={"User-Agent": DOUYIN_USER_AGENT},
            timeout=httpx.Timeout(30.0, connect=10.0),
        ) as client:
            share_url, resolved_url = await self._douyin_share_url(client, url)
            response = await client.get(share_url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            title = self._html_title(soup) or self._douyin_title_from_html(response.text) or "抖音作品"
            candidates = self._douyin_media_candidates(soup, response.text, str(response.url))
            if not candidates:
                raise ExtractionError("抖音分享页中没有找到图集或视频地址。")

            return self._build_response(
                url=url,
                resolved_url=resolved_url,
                title=title,
                extractor="douyin-share",
                files=[],
                warnings=[],
                remote_urls=candidates[:MAX_FALLBACK_FILES],
            )

    async def _resolve_from_xiaohongshu(self, url: str) -> dict[str, Any]:
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": MOBILE_USER_AGENT},
            timeout=httpx.Timeout(30.0, connect=10.0),
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            title = self._xiaohongshu_title(soup, response.text)
            candidates = self._xiaohongshu_media_candidates(soup, response.text, str(response.url))
            if not candidates:
                raise ExtractionError("小红书页面中没有找到图片或视频地址。")

            return self._build_response(
                url=url,
                resolved_url=str(response.url),
                title=title,
                extractor="xiaohongshu-share",
                files=[],
                warnings=[],
                remote_urls=candidates[:MAX_FALLBACK_FILES],
            )

    async def _resolve_from_dewu(self, url: str) -> dict[str, Any]:
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": MOBILE_USER_AGENT},
            timeout=httpx.Timeout(30.0, connect=10.0),
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            next_data = self._next_data(soup)
            title = self._dewu_title(next_data) or self._html_title(soup) or "得物动态"
            candidates = self._dewu_media_candidates(soup, response.text, str(response.url), next_data)
            if not candidates:
                raise ExtractionError("得物页面中没有找到图片或视频地址。")

            return self._build_response(
                url=url,
                resolved_url=str(response.url),
                title=title,
                extractor="dewu-share",
                files=[],
                warnings=[],
                remote_urls=candidates[:MAX_FALLBACK_FILES],
            )

    async def _resolve_from_twitter(self, url: str) -> dict[str, Any]:
        return await self._download_from_twitter(url, self.download_root)

    async def _download_from_html(self, url: str, job_dir: Path) -> dict[str, Any]:
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(30.0, connect=10.0),
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if self._is_media_response(url, content_type):
                path = await self._stream_download(client, str(response.url), job_dir, "media")
                return self._build_response(
                    url=url,
                    resolved_url=str(response.url),
                    title=path.stem,
                    extractor="direct",
                    files=[path],
                    warnings=[],
                )

            soup = BeautifulSoup(response.text, "html.parser")
            title = self._html_title(soup) or str(response.url)
            candidates = self._html_media_candidates(soup, response.text, str(response.url))

            files: list[Path] = []
            warnings: list[str] = []
            for index, candidate in enumerate(candidates[:MAX_FALLBACK_FILES], start=1):
                try:
                    if ".m3u8" in candidate.lower():
                        nested = self._download_with_ytdlp(candidate, job_dir / f"hls-{index}")
                        files.extend(self.download_root / item["download_url"].removeprefix("/media/") for item in nested["items"])
                    else:
                        files.append(await self._stream_download(client, candidate, job_dir, f"media-{index}"))
                except Exception as exc:
                    warnings.append(f"跳过一个候选媒体：{self._human_error(exc)}")

            files = [path for path in files if path.exists()]
            if not files:
                raise ExtractionError("页面中没有找到可直接下载的图片或视频地址。")

            return self._build_response(
                url=url,
                resolved_url=str(response.url),
                title=title,
                extractor="html-fallback",
                files=files,
                warnings=warnings,
            )

    async def _download_from_douyin(self, url: str, job_dir: Path) -> dict[str, Any]:
        async with httpx.AsyncClient(
            follow_redirects=False,
            headers={"User-Agent": DOUYIN_USER_AGENT},
            timeout=httpx.Timeout(30.0, connect=10.0),
        ) as client:
            share_url, resolved_url = await self._douyin_share_url(client, url)
            response = await client.get(share_url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            title = self._html_title(soup) or self._douyin_title_from_html(response.text) or "抖音作品"
            candidates = self._douyin_media_candidates(soup, response.text, str(response.url))
            if not candidates:
                raise ExtractionError("抖音分享页中没有找到图集或视频地址。")

            download_client = httpx.AsyncClient(
                follow_redirects=True,
                headers={
                    "User-Agent": DOUYIN_USER_AGENT,
                    "Referer": share_url,
                },
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
            async with download_client:
                files: list[Path] = []
                warnings: list[str] = []
                for index, candidate in enumerate(candidates[:MAX_FALLBACK_FILES], start=1):
                    try:
                        files.append(await self._stream_download(download_client, candidate, job_dir, f"douyin-{index}"))
                    except Exception as exc:
                        warnings.append(f"跳过一个抖音候选媒体：{self._human_error(exc)}")

            files = [path for path in files if path.exists()]
            if not files:
                raise ExtractionError("找到抖音媒体地址，但下载失败。")

            return self._build_response(
                url=url,
                resolved_url=resolved_url,
                title=title,
                extractor="douyin-share",
                files=files,
                warnings=[] if files else warnings,
            )

    async def _download_from_xiaohongshu(self, url: str, job_dir: Path) -> dict[str, Any]:
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": MOBILE_USER_AGENT},
            timeout=httpx.Timeout(30.0, connect=10.0),
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            title = self._xiaohongshu_title(soup, response.text)
            candidates = self._xiaohongshu_media_candidates(soup, response.text, str(response.url))
            if not candidates:
                raise ExtractionError("小红书页面中没有找到图片或视频地址。")

            download_client = httpx.AsyncClient(
                follow_redirects=True,
                headers={
                    "User-Agent": MOBILE_USER_AGENT,
                    "Referer": str(response.url),
                },
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
            async with download_client:
                files: list[Path] = []
                warnings: list[str] = []
                for index, candidate in enumerate(candidates[:MAX_FALLBACK_FILES], start=1):
                    try:
                        files.append(await self._stream_download(download_client, candidate, job_dir, f"xhs-{index}"))
                    except Exception as exc:
                        warnings.append(f"跳过一个小红书候选媒体：{self._human_error(exc)}")

            files = [path for path in files if path.exists()]
            if not files:
                raise ExtractionError("找到小红书媒体地址，但下载失败。")

            return self._build_response(
                url=url,
                resolved_url=str(response.url),
                title=title,
                extractor="xiaohongshu-share",
                files=files,
                warnings=[] if files else warnings,
            )

    async def _download_from_dewu(self, url: str, job_dir: Path) -> dict[str, Any]:
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": MOBILE_USER_AGENT},
            timeout=httpx.Timeout(30.0, connect=10.0),
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            next_data = self._next_data(soup)
            title = self._dewu_title(next_data) or self._html_title(soup) or "得物动态"
            candidates = self._dewu_media_candidates(soup, response.text, str(response.url), next_data)
            if not candidates:
                raise ExtractionError("得物页面中没有找到图片或视频地址。")

            download_client = httpx.AsyncClient(
                follow_redirects=True,
                headers={
                    "User-Agent": MOBILE_USER_AGENT,
                    "Referer": str(response.url),
                },
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
            async with download_client:
                files: list[Path] = []
                warnings: list[str] = []
                for index, candidate in enumerate(candidates[:MAX_FALLBACK_FILES], start=1):
                    try:
                        if ".m3u8" in candidate.lower():
                            nested = self._download_with_ytdlp(candidate, job_dir / f"dewu-hls-{index}")
                            files.extend(
                                self.download_root / item["download_url"].removeprefix("/media/")
                                for item in nested["items"]
                            )
                        else:
                            files.append(await self._stream_download(download_client, candidate, job_dir, f"dewu-{index}"))
                    except Exception as exc:
                        warnings.append(f"跳过一个得物候选媒体：{self._human_error(exc)}")

            files = [path for path in files if path.exists()]
            if not files:
                raise ExtractionError("找到得物媒体地址，但下载失败。")

            return self._build_response(
                url=url,
                resolved_url=str(response.url),
                title=title,
                extractor="dewu-share",
                files=files,
                warnings=[] if files else warnings,
            )

    async def _download_from_twitter(self, url: str, job_dir: Path) -> dict[str, Any]:
        tweet_id = self._twitter_status_id(url)
        if not tweet_id:
            raise ExtractionError("没有从 Twitter/X 链接中识别到推文 ID。")

        api_url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&lang=zh-cn"
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": "https://platform.twitter.com/",
            "Accept": "application/json,text/plain,*/*",
        }
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers=headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
        ) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            tweet = response.json()

            title = self._twitter_title(tweet)
            extractor = "twitter-syndication"
            candidates = self._twitter_media_candidates(tweet)
            if not candidates:
                html_title, html_candidates = await self._twitter_html_media(client, url)
                title = html_title or title
                candidates = html_candidates
                extractor = "twitter-html"
            if not candidates:
                raise ExtractionError("Twitter/X 公开数据中没有找到图片或视频地址。")

            return self._build_response(
                url=url,
                resolved_url=url,
                title=title,
                extractor=extractor,
                files=[],
                warnings=[],
                remote_urls=candidates[:MAX_FALLBACK_FILES],
            )

    async def _stream_download(self, client: httpx.AsyncClient, url: str, job_dir: Path, fallback_name: str) -> Path:
        safe_url = validate_public_url(url)
        async with client.stream("GET", safe_url) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            final_url = str(response.url)
            if not self._is_media_response(final_url, content_type):
                raise ExtractionError(f"候选链接不是图片或视频：{content_type or final_url}")

            filename = self._filename_from_response(final_url, content_type, fallback_name)
            target = self._unique_path(job_dir / filename)
            total = 0
            with target.open("wb") as file:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_FALLBACK_BYTES:
                        raise ExtractionError("文件过大，已停止下载。")
                    file.write(chunk)
            return target

    def _collect_files(self, job_dir: Path) -> list[Path]:
        files: list[Path] = []
        for path in job_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in SKIP_EXTENSIONS:
                continue
            if path.name.endswith((".part", ".ytdl")):
                continue
            files.append(path)
        return sorted(files, key=lambda item: item.stat().st_mtime)

    def _build_response(
        self,
        *,
        url: str,
        resolved_url: str,
        title: str,
        extractor: str | None,
        files: list[Path],
        warnings: list[str],
        remote_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        items = []
        for path in files:
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            items.append(
                MediaFile(
                    filename=path.name,
                    kind=file_kind(path, mime),
                    size=path.stat().st_size,
                    mime_type=mime,
                    download_url=media_url_from_path(self.download_root, path),
                ).__dict__
            )

        for index, remote_url in enumerate(remote_urls or [], start=1):
            mime = self._remote_mime_type(remote_url)
            filename = self._filename_from_remote_url(remote_url, mime, f"media-{index}")
            items.append(
                MediaFile(
                    filename=filename,
                    kind=file_kind(Path(filename), mime),
                    size=0,
                    mime_type=mime,
                    download_url=remote_url,
                ).__dict__
            )

        return {
            "success": True,
            "source_url": url,
            "resolved_url": resolved_url,
            "title": title,
            "extractor": extractor or "unknown",
            "items": items,
            "warnings": warnings,
        }

    def _filename_from_response(self, url: str, content_type: str | None, fallback_name: str) -> str:
        parsed = urlparse(url)
        original = Path(parsed.path).name
        extension = Path(original).suffix.lower()
        if extension not in MEDIA_EXTENSIONS:
            extension = content_type_extension(content_type, ".bin")
        base = Path(original).stem if original else fallback_name
        return safe_filename(f"{base}{extension}", f"{fallback_name}{extension}")

    def _filename_from_remote_url(self, url: str, content_type: str, fallback_name: str) -> str:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        original = Path(parsed.path).name
        extension = Path(original).suffix.lower()
        if extension not in MEDIA_EXTENSIONS:
            extension = content_type_extension(content_type, ".bin")
        if not extension and query.get("format"):
            extension = f".{query['format'].strip('.')}"
        base = Path(original).stem if original else fallback_name
        return safe_filename(f"{base}{extension}", f"{fallback_name}{extension}")

    def _remote_mime_type(self, url: str) -> str:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if query.get("format"):
            fmt = query["format"].lower()
            if fmt == "jpg":
                return "image/jpeg"
            if fmt in {"png", "webp", "gif"}:
                return f"image/{fmt}"
        guessed = mimetypes.guess_type(parsed.path)[0]
        if guessed:
            return guessed
        if self._looks_like_video_url(url):
            return "video/mp4"
        if self._looks_like_twitter_video_url(url):
            return "video/mp4"
        if "pbs.twimg.com" in parsed.netloc:
            return "image/jpeg"
        return "application/octet-stream"

    def _html_media_candidates(self, soup: BeautifulSoup, html: str, base_url: str) -> list[str]:
        candidates: list[str] = []
        meta_keys = {
            "og:video",
            "og:video:url",
            "og:video:secure_url",
            "og:image",
            "twitter:image",
            "twitter:image:src",
            "twitter:player:stream",
        }

        for tag in soup.find_all("meta"):
            key = tag.get("property") or tag.get("name")
            value = tag.get("content")
            if key in meta_keys and value:
                candidates.append(urljoin(base_url, value))

        for tag_name in ("video", "source"):
            for tag in soup.find_all(tag_name):
                value = tag.get("src")
                if value:
                    candidates.append(urljoin(base_url, value))

        media_pattern = re.compile(
            r"https?:\\?/\\?/[^\"'<>\\\s]+?\.(?:mp4|m3u8|mov|webm|jpg|jpeg|png|webp|gif)(?:\?[^\"'<>\\\s]*)?",
            re.IGNORECASE,
        )
        for match in media_pattern.findall(html):
            candidates.append(match.replace("\\/", "/"))

        return self._dedupe(candidates)

    async def _douyin_share_url(self, client: httpx.AsyncClient, url: str) -> tuple[str, str]:
        parsed = urlparse(url)
        resolved_url = url

        if parsed.netloc.endswith("v.douyin.com"):
            response = await client.get(url)
            location = response.headers.get("location")
            if not location:
                raise ExtractionError("抖音短链没有返回跳转地址。")
            resolved_url = urljoin(url, location)
            parsed = urlparse(resolved_url)

        match = DOUYIN_ID_PATTERN.search(parsed.path)
        if not match:
            raise ExtractionError("没有从抖音链接中识别到作品 ID。")

        kind = "video" if match.group("kind") == "video" else "note"
        aweme_id = match.group("id")
        share_url = f"https://www.iesdouyin.com/share/{kind}/{aweme_id}/?from_ssr=1"
        return share_url, resolved_url

    def _douyin_media_candidates(self, soup: BeautifulSoup, page_html: str, base_url: str) -> list[str]:
        if "/share/video/" in urlparse(base_url).path.lower():
            video_candidates = self._douyin_router_video_candidates(page_html)
            if video_candidates:
                return self._preferred_douyin_candidates(video_candidates)[:1]

        candidates: list[str] = []

        for image in soup.select(".gallery-container img[src], .aweme-share-swiper-item img[src]"):
            src = image.get("src")
            if src:
                candidates.append(urljoin(base_url, src))

        for tag_name in ("video", "source"):
            for tag in soup.find_all(tag_name):
                src = tag.get("src")
                if src:
                    candidates.append(urljoin(base_url, src))

        normalized_html = html.unescape(page_html).replace("\\u002F", "/").replace("\\u0026", "&")
        for match in re.findall(
            r"https?://[^\"'<>\\\s]+(?:douyinpic|douyinvod|idouyinvod)[^\"'<>\\\s]+",
            normalized_html,
            flags=re.IGNORECASE,
        ):
            url = html.unescape(match.replace("\\/", "/")).rstrip(",;)]}")
            if "aweme-avatar" in url or "favicon" in url or "logo" in url:
                continue
            if "biz_tag=aweme_images" in url or "tplv-dy-shrink" in url or any(ext in url.lower() for ext in (".mp4", ".webp", ".jpg", ".jpeg", ".png")):
                candidates.append(url)

        return self._preferred_douyin_candidates(candidates)

    def _douyin_router_video_candidates(self, page_html: str) -> list[str]:
        router_data = self._json_assignment(page_html, "window._ROUTER_DATA")
        if not isinstance(router_data, dict):
            return []

        candidates: list[str] = []
        for item in self._douyin_aweme_items(router_data):
            video = item.get("video") if isinstance(item, dict) else None
            if not isinstance(video, dict):
                continue

            candidates.extend(self._douyin_media_addr_urls(video.get("download_addr")))
            candidates.extend(self._douyin_media_addr_urls(video.get("play_addr")))
            candidates.extend(self._douyin_media_addr_urls(video.get("play_addr_h264")))
            candidates.extend(self._douyin_media_addr_urls(video.get("play_addr_bytevc1")))

            for bitrate in video.get("bit_rate") or []:
                if isinstance(bitrate, dict):
                    candidates.extend(self._douyin_media_addr_urls(bitrate.get("play_addr")))

            candidates.extend(self._douyin_video_urls_from_tree(video))

        variants: list[str] = []
        for url in self._dedupe(candidates):
            variants.extend(self._douyin_video_url_variants(url))
        return self._dedupe(variants)

    def _douyin_aweme_items(self, value: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        stack = [value]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                item_list = current.get("item_list")
                if isinstance(item_list, list):
                    items.extend(item for item in item_list if isinstance(item, dict))
                for nested in current.values():
                    if isinstance(nested, (dict, list)):
                        stack.append(nested)
            elif isinstance(current, list):
                stack.extend(item for item in current if isinstance(item, (dict, list)))
        return items

    def _douyin_media_addr_urls(self, address: Any) -> list[str]:
        if not isinstance(address, dict):
            return []

        candidates: list[str] = []
        url_list = address.get("url_list")
        if isinstance(url_list, list):
            candidates.extend(item for item in url_list if isinstance(item, str))

        for key in ("url", "main_url", "backup_url"):
            value = address.get(key)
            if isinstance(value, str):
                candidates.append(value)

        return [self._normalize_embedded_url(url) for url in candidates if self._looks_like_video_url(url)]

    def _douyin_video_urls_from_tree(self, value: Any) -> list[str]:
        candidates: list[str] = []
        stack = [value]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                stack.extend(item for item in current.values() if isinstance(item, (dict, list, str)))
            elif isinstance(current, list):
                stack.extend(item for item in current if isinstance(item, (dict, list, str)))
            elif isinstance(current, str) and self._looks_like_video_url(current):
                candidates.append(self._normalize_embedded_url(current))
        return candidates

    def _douyin_video_url_variants(self, url: str) -> list[str]:
        normalized = self._normalize_embedded_url(url)
        variants = [normalized]
        parsed = urlparse(normalized)
        lower_path = parsed.path.lower()
        if "/aweme/v1/play" not in lower_path:
            return variants

        ratios = ["1080p", "720p", "540p"]
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if query.get("ratio") and query["ratio"] not in ratios:
            ratios.append(query["ratio"])

        endpoints = []
        if "/playwm/" in lower_path:
            endpoints.append(parsed.path.replace("/playwm/", "/play/"))
        endpoints.append(parsed.path)
        if "/play/" in lower_path:
            endpoints.append(parsed.path.replace("/play/", "/playwm/"))

        generated: list[str] = []
        for endpoint in self._dedupe(endpoints):
            for ratio in ratios:
                next_query = query.copy()
                next_query["ratio"] = ratio
                generated.append(urlunparse(parsed._replace(path=endpoint, query=urlencode(next_query))))
        return self._dedupe(generated + variants)

    def _looks_like_video_url(self, url: str) -> bool:
        lower = self._normalize_embedded_url(url).lower()
        return any(
            marker in lower
            for marker in (
                "/aweme/v1/play",
                "douyinvod",
                "idouyinvod",
                "vcloud",
                ".mp4",
                ".m3u8",
                "mime_type=video",
            )
        )

    def _json_assignment(self, page_html: str, assignment: str) -> Any | None:
        pattern = rf"{re.escape(assignment)}\s*=\s*(\{{.*?\}})\s*</script>"
        match = re.search(pattern, page_html, flags=re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(html.unescape(match.group(1)))
        except json.JSONDecodeError:
            return None

    def _normalize_embedded_url(self, url: str) -> str:
        return html.unescape(url).replace("\\/", "/").replace("\\u002F", "/").replace("\\u0026", "&")

    def _douyin_title_from_html(self, page_html: str) -> str | None:
        match = re.search(r"<title[^>]*>(.*?)</title>", page_html, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()

    def _is_douyin_url(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        return host.endswith(("douyin.com", "iesdouyin.com"))

    def _is_xiaohongshu_url(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        return host.endswith(("xiaohongshu.com", "xhslink.com", "xhscdn.com"))

    def _is_dewu_url(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        return host.endswith(("dewu.com", "dw4.co", "poizon.com"))

    def _is_twitter_url(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        return host.endswith(("twitter.com", "x.com", "mobile.twitter.com", "fxtwitter.com", "vxtwitter.com"))

    def _xiaohongshu_media_candidates(self, soup: BeautifulSoup, page_html: str, base_url: str) -> list[str]:
        candidates: list[str] = []

        for image in soup.select(".note-image-container img[src], .swiper-slide img[src], img[data-xhs-img][src]"):
            src = image.get("src")
            if src:
                candidates.append(urljoin(base_url, src))

        for tag_name in ("video", "source"):
            for tag in soup.find_all(tag_name):
                src = tag.get("src")
                if src:
                    candidates.append(urljoin(base_url, src))

        normalized_html = html.unescape(page_html).replace("\\u002F", "/").replace("\\u0026", "&")
        for match in re.findall(
            r"https?://[^\"'<>\\\s]+(?:xhscdn|xiaohongshu)[^\"'<>\\\s]+",
            normalized_html,
            flags=re.IGNORECASE,
        ):
            url = html.unescape(match.replace("\\/", "/")).rstrip(",;)]}")
            lower = url.lower()
            if "avatar" in lower or "favicon" in lower or "picasso-static" in lower or "fe-static" in lower:
                continue
            if any(marker in lower for marker in ("notes_pre_post", "sns-webpic", "sns-video", ".mp4", ".m3u8", ".jpg", ".jpeg", ".png", ".webp")):
                candidates.append(url)

        return self._preferred_xiaohongshu_candidates(candidates)

    def _preferred_xiaohongshu_candidates(self, candidates: list[str]) -> list[str]:
        by_key: dict[str, str] = {}
        for url in self._dedupe(candidates):
            if urlparse(url).scheme not in {"http", "https"}:
                continue
            key = self._xiaohongshu_candidate_key(url)
            current = by_key.get(key)
            if current is None or self._xiaohongshu_candidate_score(url) > self._xiaohongshu_candidate_score(current):
                by_key[key] = url
        preferred = sorted(by_key.values(), key=self._xiaohongshu_candidate_score, reverse=True)
        videos = [url for url in preferred if self._xiaohongshu_candidate_score(url) >= 10_000]
        return videos[:1] if videos else preferred

    def _xiaohongshu_candidate_key(self, url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path.split("!", 1)[0]
        token = Path(path).name
        if token:
            return token
        return path or url

    def _xiaohongshu_candidate_score(self, url: str) -> int:
        lower = url.lower()
        score = 0
        if any(marker in lower for marker in ("sns-video", ".mp4", ".m3u8")):
            score += 10_000
        if any(marker in lower for marker in ("origin", "original", "uhd", "1080", "hd", "high")):
            score += 2_500
        if any(marker in lower for marker in ("720", "sd", "low")):
            score += 800
        if "!style_" in lower or "!nd_" in lower:
            score -= 1_500
        if "!h5_1080" in lower:
            score += 2_000
        if "imageview2" in lower:
            score -= 500
        if ".jpg" in lower or ".jpeg" in lower:
            score += 200
        elif ".webp" in lower:
            score += 100
        dimensions = re.findall(r"(?<!\d)(\d{3,4})[_x/](\d{3,4})(?!\d)", lower)
        if dimensions:
            score += max(int(width) * int(height) for width, height in dimensions) // 1_000
        return score

    def _xiaohongshu_title(self, soup: BeautifulSoup, page_html: str) -> str:
        for selector in (
            ".note-content .title",
            ".title",
            ".desc",
            ".note-text",
        ):
            node = soup.select_one(selector)
            if node:
                text = node.get_text(" ", strip=True)
                if text:
                    return text[:100]
        return self._html_title(soup) or self._douyin_title_from_html(page_html) or "小红书笔记"

    def _next_data(self, soup: BeautifulSoup) -> dict[str, Any]:
        script = soup.find("script", id="__NEXT_DATA__")
        if not script:
            return {}
        raw = script.string or script.get_text("", strip=False)
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def _dewu_media_candidates(
        self,
        soup: BeautifulSoup,
        page_html: str,
        base_url: str,
        next_data: dict[str, Any],
    ) -> list[str]:
        candidates = self._dewu_content_media_candidates(next_data)

        if not candidates:
            for image in soup.select("img[src], source[src], video[src]"):
                src = image.get("src")
                if src:
                    candidates.append(urljoin(base_url, src))

            candidates.extend(self._dewu_urls_from_tree(next_data))

            normalized_html = html.unescape(page_html).replace("\\u002F", "/").replace("\\u0026", "&")
            for match in re.findall(
                r"https?://[^\"'<>\\\s]+(?:dewu|poizon)[^\"'<>\\\s]+",
                normalized_html,
                flags=re.IGNORECASE,
            ):
                candidates.append(match.replace("\\/", "/").rstrip(",;)]}"))

        return self._preferred_dewu_candidates(candidates)

    def _dewu_content_media_candidates(self, next_data: dict[str, Any]) -> list[str]:
        page_props = next_data.get("props", {}).get("pageProps", {})
        meta_info = page_props.get("metaOGInfo", {}) if isinstance(page_props, dict) else {}
        data = meta_info.get("data") if isinstance(meta_info, dict) else None
        if not isinstance(data, list):
            return []

        candidates: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, dict):
                continue

            media = content.get("media")
            media_list = media.get("list") if isinstance(media, dict) else None
            if isinstance(media_list, list):
                for media_item in media_list:
                    if isinstance(media_item, dict):
                        candidates.extend(self._dewu_media_fields(media_item))

            cover = content.get("cover")
            if isinstance(cover, dict):
                candidates.extend(self._dewu_media_fields(cover))

            candidates.extend(self._dewu_media_fields(content))

        return candidates

    def _dewu_media_fields(self, value: dict[str, Any]) -> list[str]:
        candidates: list[str] = []
        for key in (
            "url",
            "originUrl",
            "originalUrl",
            "videoUrl",
            "videoShareUrl",
            "playUrl",
            "coverUrl",
            "imageUrl",
        ):
            item = value.get(key)
            if isinstance(item, str) and item:
                candidates.append(item)
        return candidates

    def _dewu_urls_from_tree(self, value: Any) -> list[str]:
        candidates: list[str] = []
        stack = [value]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                stack.extend(current.values())
            elif isinstance(current, list):
                stack.extend(current)
            elif isinstance(current, str) and self._looks_like_dewu_media_url(current):
                candidates.append(current)
        return candidates

    def _looks_like_dewu_media_url(self, url: str) -> bool:
        lower = self._normalize_embedded_url(url).lower()
        parsed = urlparse(lower)
        if not any(marker in parsed.netloc for marker in ("dewu", "poizon")):
            return False
        return any(
            marker in lower
            for marker in (
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
                ".gif",
                ".mp4",
                ".m3u8",
                "image-cdn",
                "video",
            )
        )

    def _preferred_dewu_candidates(self, candidates: list[str]) -> list[str]:
        by_key: dict[str, str] = {}
        order: list[str] = []
        for url in self._dedupe([self._normalize_embedded_url(item) for item in candidates]):
            if urlparse(url).scheme not in {"http", "https"} or not self._looks_like_dewu_media_url(url):
                continue
            key = self._dewu_candidate_key(url)
            current = by_key.get(key)
            if current is None:
                order.append(key)
                by_key[key] = url
            elif self._dewu_candidate_score(url) > self._dewu_candidate_score(current):
                by_key[key] = url
        preferred = [by_key[key] for key in order if key in by_key]
        videos = [url for url in preferred if self._dewu_candidate_score(url) >= 10_000]
        return videos[:1] if videos else preferred

    def _dewu_candidate_key(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.path or url

    def _dewu_candidate_score(self, url: str) -> int:
        lower = url.lower()
        score = 0
        if ".mp4" in lower or ".m3u8" in lower or "video" in lower:
            score += 10_000
        if "community" in lower:
            score += 1_200
        if "image-cdn" in lower:
            score += 800
        if ".jpg" in lower or ".jpeg" in lower:
            score += 300
        elif ".webp" in lower:
            score += 180
        dimensions = re.findall(r"(?<!\d)w(\d{3,5})h(\d{3,5})(?!\d)", lower)
        if dimensions:
            score += max(int(width) * int(height) for width, height in dimensions) // 1_000
        return score

    def _dewu_title(self, next_data: dict[str, Any]) -> str | None:
        page_props = next_data.get("props", {}).get("pageProps", {})
        meta_info = page_props.get("metaOGInfo", {}) if isinstance(page_props, dict) else {}
        data = meta_info.get("data") if isinstance(meta_info, dict) else None
        if not isinstance(data, list):
            return None

        for item in data:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, dict):
                continue
            title = content.get("title")
            if isinstance(title, str) and title.strip():
                return title.strip()[:120]
            text = content.get("content")
            if isinstance(text, str) and text.strip():
                return text.strip()[:120]
        return None

    def _twitter_status_id(self, url: str) -> str | None:
        match = TWITTER_STATUS_PATTERN.search(urlparse(url).path)
        return match.group("id") if match else None

    def _twitter_media_candidates(self, tweet: dict[str, Any]) -> list[str]:
        candidates: list[str] = []
        media_items = tweet.get("mediaDetails")
        if isinstance(media_items, list):
            for item in media_items:
                if not isinstance(item, dict):
                    continue
                media_type = str(item.get("type") or "").lower()
                if media_type == "photo":
                    candidates.extend(self._twitter_photo_variants(item.get("media_url_https") or item.get("media_url")))
                    continue

                variants = item.get("video_info", {}).get("variants") if isinstance(item.get("video_info"), dict) else None
                if isinstance(variants, list):
                    candidates.extend(self._preferred_twitter_video_variants(variants))

                video_url = item.get("video_url") or item.get("media_url_https")
                if isinstance(video_url, str) and video_url:
                    candidates.append(video_url)

        for photo in tweet.get("photos") or []:
            if isinstance(photo, dict):
                candidates.extend(self._twitter_photo_variants(photo.get("url") or photo.get("media_url_https")))

        return self._dedupe([candidate for candidate in candidates if self._looks_like_twitter_media_url(candidate)])

    async def _twitter_html_media(self, client: httpx.AsyncClient, url: str) -> tuple[str | None, list[str]]:
        response = await client.get(url)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        title = self._html_title(soup) or self._douyin_title_from_html(response.text)
        candidates = self._twitter_html_media_candidates(response.text)
        return title, candidates

    def _twitter_html_media_candidates(self, page_html: str) -> list[str]:
        normalized_html = html.unescape(page_html).replace("\\u002F", "/").replace("\\u0026", "&")
        raw_candidates: list[str] = []

        for match in re.findall(
            r"https?://(?:video|pbs)\.twimg\.com/[^\"'<>\\\s]+",
            normalized_html,
            flags=re.IGNORECASE,
        ):
            raw_candidates.append(match.replace("\\/", "/").rstrip(",;)]}"))

        video_candidates = [
            url
            for url in self._dedupe(raw_candidates)
            if self._looks_like_twitter_video_url(url)
        ]
        if video_candidates:
            return [max(video_candidates, key=self._twitter_video_candidate_score)]

        photo_candidates: list[str] = []
        for url in self._dedupe(raw_candidates):
            parsed = urlparse(url)
            lower = url.lower()
            if "pbs.twimg.com" not in parsed.netloc:
                continue
            if "/profile_images/" in lower or "/profile_banners/" in lower:
                continue
            if "/media/" not in lower and "/amplify_video_thumb/" not in lower:
                continue
            photo_candidates.extend(self._twitter_photo_variants(url))

        return self._dedupe([url for url in photo_candidates if self._looks_like_twitter_media_url(url)])

    def _looks_like_twitter_video_url(self, url: str) -> bool:
        lower = self._normalize_embedded_url(url).lower()
        parsed = urlparse(lower)
        if "video.twimg.com" not in parsed.netloc:
            return False
        return any(marker in lower for marker in (".mp4", ".m3u8", "/amplify_video/", "/ext_tw_video/", "/tweet_video/"))

    def _twitter_video_candidate_score(self, url: str) -> int:
        lower = url.lower()
        score = 0
        if ".mp4" in lower:
            score += 10_000
        elif ".m3u8" in lower:
            score += 3_000
        dimensions = re.findall(r"/(\d{3,5})x(\d{3,5})/", lower)
        if dimensions:
            score += max(int(width) * int(height) for width, height in dimensions) // 1_000
        return score

    def _twitter_photo_variants(self, url: Any) -> list[str]:
        if not isinstance(url, str) or not url:
            return []
        normalized = self._normalize_embedded_url(url)
        parsed = urlparse(normalized)
        if "pbs.twimg.com" not in parsed.netloc:
            return [normalized]

        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if query.get("format"):
            query["name"] = "4096x4096"
            return [urlunparse(parsed._replace(query=urlencode(query)))]
        separator = "&" if parsed.query else "?"
        return [f"{normalized}{separator}name=4096x4096"]

    def _preferred_twitter_video_variants(self, variants: list[Any]) -> list[str]:
        candidates: list[tuple[int, str]] = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            url = variant.get("url")
            content_type = str(variant.get("content_type") or "").lower()
            if not isinstance(url, str) or "mp4" not in content_type:
                continue
            bitrate = variant.get("bitrate")
            score = bitrate if isinstance(bitrate, int) else 0
            candidates.append((score, self._normalize_embedded_url(url)))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [candidates[0][1]] if candidates else []

    def _looks_like_twitter_media_url(self, url: str) -> bool:
        lower = self._normalize_embedded_url(url).lower()
        parsed = urlparse(lower)
        if not parsed.scheme.startswith("http"):
            return False
        if not any(host in parsed.netloc for host in ("twimg.com", "video.twimg.com")):
            return False
        return any(marker in lower for marker in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", "format=jpg", "format=png"))

    def _twitter_title(self, tweet: dict[str, Any]) -> str:
        text = tweet.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()[:120]
        user = tweet.get("user")
        if isinstance(user, dict):
            name = user.get("name") or user.get("screen_name")
            if isinstance(name, str) and name.strip():
                return f"{name.strip()} 的推文"
        return "Twitter/X 推文"

    def _preferred_douyin_candidates(self, candidates: list[str]) -> list[str]:
        by_key: dict[str, str] = {}
        for url in self._dedupe(candidates):
            if urlparse(url).scheme not in {"http", "https"}:
                continue
            key = self._douyin_candidate_key(url)
            current = by_key.get(key)
            if current is None or self._douyin_candidate_score(url) > self._douyin_candidate_score(current):
                by_key[key] = url
        return list(by_key.values())

    def _douyin_candidate_key(self, url: str) -> str:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if "/aweme/v1/play" in parsed.path.lower() and query.get("video_id"):
            return f"video:{query['video_id']}"
        path = parsed.path.split("~", 1)[0]
        return path or url

    def _douyin_candidate_score(self, url: str) -> int:
        lower = url.lower()
        score = 0
        if "/aweme/v1/play" in lower:
            score += 12_000
        if any(marker in lower for marker in ("douyinvod", "idouyinvod", ".mp4", ".m3u8", "mime_type=video")):
            score += 10_000
        if "/aweme/v1/play/" in lower:
            score += 4_000
        if "/aweme/v1/playwm/" in lower:
            score -= 2_500
        if "ratio=1080p" in lower or "definition=1080p" in lower:
            score += 3_000
        elif "ratio=720p" in lower or "definition=720p" in lower:
            score += 1_800
        elif "ratio=540p" in lower or "definition=540p" in lower:
            score += 700
        if "water" in lower:
            score -= 5_000
        if "~q80" in lower and "tplv" not in lower:
            score += 4_000
        elif "q80" in lower:
            score += 1_500
        elif "q75" in lower:
            score += 900
        if ".jpeg" in lower or ".jpg" in lower:
            score += 200
        elif ".webp" in lower:
            score += 100
        if "tplv-dy-shrink" in lower:
            score -= 300

        dimensions = re.findall(r"(?<!\d)(\d{3,4})[_:](\d{3,4})(?!\d)", lower)
        if dimensions:
            score += max(int(width) * int(height) for width, height in dimensions) // 1_000
        return score

    def _html_title(self, soup: BeautifulSoup) -> str | None:
        for selector in (
            ("meta", {"property": "og:title"}),
            ("meta", {"name": "twitter:title"}),
        ):
            tag = soup.find(*selector)
            if tag and tag.get("content"):
                return tag["content"].strip()
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        return None

    def _is_media_response(self, url: str, content_type: str | None) -> bool:
        mime = (content_type or "").split(";", 1)[0].strip().lower()
        if mime.startswith(("image/", "video/", "audio/")):
            return True
        return Path(urlparse(url).path).suffix.lower() in MEDIA_EXTENSIONS

    def _unique_path(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            return path

        stem = path.stem
        suffix = path.suffix
        for index in range(2, 10_000):
            candidate = path.with_name(f"{stem}-{index}{suffix}")
            if not candidate.exists():
                return candidate
        raise ExtractionError("无法生成唯一文件名。")

    def _ytdlp_media_candidates(self, info: Any) -> list[str]:
        candidates: list[str] = []
        for item in self._ytdlp_info_items(info):
            if not isinstance(item, dict):
                continue

            direct_url = item.get("url")
            if isinstance(direct_url, str) and self._looks_like_resolved_media_url(direct_url):
                candidates.append(self._normalize_embedded_url(direct_url))

            formats = item.get("formats")
            if isinstance(formats, list):
                scored: list[tuple[int, str]] = []
                for media_format in formats:
                    if not isinstance(media_format, dict):
                        continue
                    url = media_format.get("url")
                    if not isinstance(url, str) or not self._looks_like_resolved_media_url(url):
                        continue
                    score = self._ytdlp_format_score(media_format)
                    scored.append((score, self._normalize_embedded_url(url)))
                if scored:
                    scored.sort(key=lambda value: value[0], reverse=True)
                    candidates.append(scored[0][1])

        return self._dedupe(candidates)

    def _ytdlp_info_items(self, info: Any) -> list[dict[str, Any]]:
        if not isinstance(info, dict):
            return []
        entries = info.get("entries")
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)]
        return [info]

    def _ytdlp_format_score(self, media_format: dict[str, Any]) -> int:
        score = 0
        ext = str(media_format.get("ext") or "").lower()
        protocol = str(media_format.get("protocol") or "").lower()
        vcodec = str(media_format.get("vcodec") or "")
        acodec = str(media_format.get("acodec") or "")
        if ext == "mp4":
            score += 5_000
        if "m3u8" in protocol:
            score -= 2_000
        if vcodec != "none" and acodec != "none":
            score += 4_000
        elif vcodec != "none":
            score += 2_000
        if isinstance(media_format.get("height"), int):
            score += int(media_format["height"]) * 10
        if isinstance(media_format.get("tbr"), (int, float)):
            score += int(media_format["tbr"])
        return score

    def _looks_like_resolved_media_url(self, url: str) -> bool:
        parsed = urlparse(self._normalize_embedded_url(url))
        if parsed.scheme not in {"http", "https"}:
            return False
        if Path(parsed.path).suffix.lower() in MEDIA_EXTENSIONS:
            return True
        lower = url.lower()
        return any(marker in lower for marker in ("mime_type=video", "format=jpg", "format=png", ".m3u8"))

    def _title_from_info(self, info: Any) -> str:
        if isinstance(info, dict):
            if info.get("title"):
                return str(info["title"])
            entries = info.get("entries") or []
            for entry in entries:
                if isinstance(entry, dict) and entry.get("title"):
                    return str(entry["title"])
        return "已下载媒体"

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _human_error(self, error: Exception) -> str:
        if isinstance(error, ExtractionError):
            return str(error)
        if isinstance(error, (DownloadError, ExtractorError)):
            return str(error).replace("\n", " ").strip()
        if isinstance(error, httpx.HTTPStatusError):
            return f"HTTP {error.response.status_code}"
        return str(error).replace("\n", " ").strip() or error.__class__.__name__
