import os
import sys
import subprocess
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from pydantic import BaseModel

from downloader import fetch_youtube_metadata, ZipBatchManager

app = FastAPI(title="YouTube Bulk & Shorts Downloader (Zip Edition)")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp_batches")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Ephemeral Batch Manager: packages into ZIP, auto-sweeps old files
batch_mgr = ZipBatchManager(base_temp_dir=TEMP_DIR, max_concurrent=2)


class FetchRequest(BaseModel):
    url: str
    filter_type: str = "all"  # 'all', 'videos', 'shorts'
    max_results: Optional[int] = None


class BatchDownloadRequest(BaseModel):
    items: List[dict]
    quality: str = "1080p"  # 1080p, 720p, 480p, 360p, audio_mp3
    channel_name: Optional[str] = "YouTube_Shorts"


@app.get("/", response_class=HTMLResponse)
async def index():
    html_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(html_file):
        with open(html_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Frontend not found.</h1>"


@app.post("/api/fetch")
async def fetch_videos(req: FetchRequest):
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=400, detail="Please enter a valid YouTube URL.")
    try:
        data = fetch_youtube_metadata(
            url=req.url.strip(),
            filter_type=req.filter_type,
            max_results=req.max_results
        )
        return JSONResponse(content={"success": True, "data": data})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/api/batch-download")
async def start_batch_download(req: BatchDownloadRequest):
    """Starts a batch download job that packages directly into a ZIP archive."""
    if not req.items:
        raise HTTPException(status_code=400, detail="No items selected for download.")
    try:
        batch_id = batch_mgr.create_batch(
            items=req.items,
            quality=req.quality,
            channel_name=req.channel_name or "YouTube_Shorts"
        )
        return {"success": True, "batch_id": batch_id}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/api/batch-status/{batch_id}")
async def get_batch_status(batch_id: str):
    status = batch_mgr.get_batch_status(batch_id)
    if not status:
        raise HTTPException(status_code=404, detail="Download batch not found or already expired.")
    return status


@app.get("/api/download-zip/{batch_id}")
async def download_zip(batch_id: str):
    """
    Delivers the ZIP file to the user's browser.
    Schedules an automatic purge after 90 seconds, leaving ZERO permanent server storage.
    """
    batch = batch_mgr.get_batch_status(batch_id)
    if not batch:
        return JSONResponse(status_code=200, content={
            "status": "downloaded",
            "message": "Your ZIP file has been downloaded successfully and purged from the server."
        })

    zip_path = batch.get("zip_filepath")
    if not zip_path or not os.path.exists(zip_path):
        return JSONResponse(status_code=200, content={
            "status": "downloaded",
            "message": "Your ZIP file was already delivered and cleaned from server storage."
        })

    filename = batch.get("zip_filename", f"youtube_shorts_{batch_id}.zip")

    # Schedule background purge after 90s grace period
    batch_mgr.schedule_delete_batch(batch_id, delay_seconds=90)

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename
    )


if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting YouTube Bulk Downloader (Zip Edition) on http://localhost:5000 ...")
    uvicorn.run("app:app", host="0.0.0.0", port=5000, reload=False)
