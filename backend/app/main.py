from __future__ import annotations

import mimetypes
import os
from typing import Literal
from urllib.parse import quote
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .downloader import ExtractionError, MediaDownloader, get_download_root, safe_filename, validate_public_url


download_root = get_download_root()
downloader = MediaDownloader(download_root)
frontend_origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

app = FastAPI(
    title="Media Link Downloader",
    version="0.1.0",
    description="Extract and download public images or videos from shared links.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=str(download_root)), name="media")


class ExtractRequest(BaseModel):
    url: str = Field(min_length=8, max_length=4096)


class MediaItem(BaseModel):
    filename: str
    kind: Literal["image", "video", "audio", "file"]
    size: int
    mime_type: str
    download_url: str


class ExtractResponse(BaseModel):
    success: bool
    source_url: str
    resolved_url: str
    title: str
    extractor: str
    items: list[MediaItem]
    warnings: list[str] = []


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/extract", response_model=ExtractResponse)
async def extract_media(payload: ExtractRequest) -> ExtractResponse:
    try:
        result = await downloader.resolve(payload.url)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc)}) from exc

    return ExtractResponse(**result)


@app.post("/api/resolve", response_model=ExtractResponse)
async def resolve_media(payload: ExtractRequest) -> ExtractResponse:
    return await extract_media(payload)


@app.get("/api/download/{media_path:path}")
def download_media(media_path: str) -> FileResponse:
    target = (download_root / media_path).resolve()
    try:
        target.relative_to(download_root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc

    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type, filename=target.name)


@app.get("/api/download-remote")
async def download_remote_media(
    url: str = Query(min_length=8, max_length=4096),
    filename: str | None = Query(default=None, max_length=180),
) -> StreamingResponse:
    safe_url = validate_public_url(url)
    client = httpx.AsyncClient(
        follow_redirects=True,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            ),
            "Referer": remote_referer(safe_url),
        },
        timeout=httpx.Timeout(90.0, connect=10.0),
    )
    response: httpx.Response | None = None

    try:
        response = await client.send(client.build_request("GET", safe_url), stream=True)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if not downloader._is_media_response(str(response.url), content_type):
            raise HTTPException(status_code=422, detail="远程链接不是可下载的图片或视频")

        media_type = content_type.split(";", 1)[0].strip() or "application/octet-stream"
        fallback_name = str(response.url).rsplit("/", 1)[-1] or "media"
        download_name = safe_filename(filename or fallback_name, "media")
        headers = {
            "Access-Control-Expose-Headers": "Content-Length, Content-Disposition",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(download_name)}",
        }
        content_length = response.headers.get("content-length")
        if content_length:
            headers["Content-Length"] = content_length

        async def stream_body():
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        return StreamingResponse(stream_body(), media_type=media_type, headers=headers)
    except HTTPException:
        if response is not None:
            await response.aclose()
        await client.aclose()
        raise
    except Exception as exc:
        if response is not None:
            await response.aclose()
        await client.aclose()
        raise HTTPException(status_code=422, detail="远程文件下载失败") from exc


def remote_referer(url: str) -> str:
    host = urlparse(url).hostname or ""
    if host.endswith(("poizon.com", "dewu.com")):
        return "https://m.dewu.com/"
    if "twimg.com" in host:
        return "https://x.com/"
    if host.endswith(("xhscdn.com", "xiaohongshu.com")):
        return "https://www.xiaohongshu.com/"
    if host.endswith(("douyin.com", "douyinvod.com", "idouyinvod.com")):
        return "https://www.iesdouyin.com/"
    return f"{urlparse(url).scheme}://{host}/" if host else "https://www.google.com/"
