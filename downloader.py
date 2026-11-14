import os
import re
import sys
import time
import math
import glob
import uuid
import shutil
import zipfile
import threading
from urllib.parse import urlparse, parse_qs
from typing import Dict, List, Optional, Any, Callable
from contextlib import suppress
import yt_dlp

HD_CLIENTS = ["default", "mweb"]

def format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def format_views(count: Optional[int]) -> str:
    if not count:
        return "N/A"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def is_single_video_url(url: str) -> bool:
    """Checks if the URL is a single YouTube video or Short."""
    url = url.strip()
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.lower()
    
    if "youtu.be" in netloc:
        return True
    if any(kw in path for kw in ["/watch", "/shorts/", "/embed/", "/live/", "/v/"]):
        return True
    return False

def normalize_channel_url(url: str, filter_type: str = "all") -> str:
    """Ensure channel URL has appropriate tab if requested."""
    url = url.strip()
    if not ("youtube.com" in url or "youtu.be" in url):
        return url
        
    if is_single_video_url(url):
        return url

    parsed = urlparse(url)
    path = parsed.path.rstrip('/')

    # It's a channel or playlist
    if filter_type == "shorts":
        if not path.endswith("/shorts"):
            if path.endswith(("/videos", "/featured", "/playlists", "/community")):
                path = re.sub(r'/(videos|featured|playlists|community)$', '/shorts', path)
            else:
                path = f"{path}/shorts"
    elif filter_type == "videos":
        if not path.endswith("/videos"):
            if path.endswith(("/shorts", "/featured", "/playlists", "/community")):
                path = re.sub(r'/(shorts|featured|playlists|community)$', '/videos', path)
            else:
                path = f"{path}/videos"

    return f"{parsed.scheme or 'https'}://{parsed.netloc}{path}"

def fetch_youtube_metadata(url: str, filter_type: str = "all", max_results: Optional[int] = None) -> Dict[str, Any]:
    """
    Fast metadata extraction for a YouTube Video, Short, Channel or Playlist.
    Uses extract_flat so it extracts all videos without downloading video streams.
    If max_results is None or 0, it fetches ALL videos/shorts without limit.
    """
    url = url.strip()
    is_single = is_single_video_url(url)
    target_url = normalize_channel_url(url, filter_type)
    
    ydl_opts = {
        'extract_flat': 'in_playlist' if not is_single else False,
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': False,
    }

    if max_results and max_results > 0 and not is_single:
        ydl_opts['playlistend'] = max_results

    info = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=False)
    except Exception:
        # Fallback with ignoreerrors or minimal options
        try:
            fallback_opts = {
                'extract_flat': True,
                'skip_download': True,
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
            }
            with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                info = ydl.extract_info(target_url, download=False)
        except Exception:
            pass

    if not info:
        raise ValueError("Could not extract metadata from the provided URL. Please verify the link is accessible.")

    entries_raw = []
    is_playlist = "entries" in info and info["entries"] is not None

    if is_playlist and not is_single:
        entries_raw = list(info["entries"])
        channel_title = info.get("channel") or info.get("uploader") or info.get("title") or "YouTube Channel"
        channel_url = info.get("channel_url") or info.get("uploader_url") or target_url
    else:
        entries_raw = [info]
        channel_title = info.get("channel") or info.get("uploader") or info.get("title") or "YouTube Video"
        channel_url = info.get("channel_url") or target_url

    items = []
    for entry in entries_raw:
        if not entry:
            continue
        v_id = entry.get("id")
        if not v_id:
            continue
            
        title = entry.get("title") or "Untitled Video"
        webpage_url = entry.get("webpage_url") or entry.get("url") or f"https://www.youtube.com/watch?v={v_id}"
        if not webpage_url.startswith("http") or "googlevideo.com" in webpage_url:
            webpage_url = f"https://www.youtube.com/watch?v={v_id}"

        duration = entry.get("duration")
        view_count = entry.get("view_count")
        
        # Determine if it's a Short
        is_short = False
        if "/shorts/" in target_url or "/shorts/" in webpage_url:
            is_short = True
        elif duration is not None and 0 < duration <= 62:
            is_short = True
            
        # Only apply filter_type if this was a bulk channel / playlist scan (NOT a direct single video link)
        if is_playlist and not is_single:
            if filter_type == "shorts" and not is_short:
                continue
            if filter_type == "videos" and is_short and duration is not None and duration <= 60:
                continue

        thumbnails = entry.get("thumbnails") or []
        thumb_url = ""
        if thumbnails:
            thumb_url = thumbnails[-1].get("url")
        if not thumb_url:
            thumb_url = f"https://i.ytimg.com/vi/{v_id}/hqdefault.jpg"

        items.append({
            "id": v_id,
            "title": title,
            "url": webpage_url,
            "duration": duration,
            "duration_str": format_duration(duration),
            "views": format_views(view_count),
            "raw_views": view_count or 0,
            "thumbnail": thumb_url,
            "is_short": is_short,
            "upload_date": entry.get("upload_date") or ""
        })

    return {
        "title": channel_title,
        "url": channel_url,
        "is_playlist": is_playlist and not is_single,
        "filter_type": filter_type,
        "count": len(items),
        "items": items
    }


class ZipBatchManager:
    """
    Manages ephemeral batch downloads.
    1. Downloads selected items into a temporary batch folder.
    2. Packages all downloaded files into a single ZIP archive.
    3. Deletes raw video files once zipped to conserve disk space.
    4. Auto-sweeps old batches after 30 minutes to ensure ZERO permanent server storage.
    """
    def __init__(self, base_temp_dir: str = "temp_batches", max_concurrent: int = 2):
        self.base_temp_dir = base_temp_dir
        os.makedirs(self.base_temp_dir, exist_ok=True)
        self.max_concurrent = max_concurrent
        self.batches: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        
        # Background cleanup thread (runs every 5 mins)
        self._cleaner_thread = threading.Thread(target=self._auto_clean_loop, daemon=True)
        self._cleaner_thread.start()

    def create_batch(self, items: List[Dict[str, Any]], quality: str = "1080p", channel_name: str = "youtube") -> str:
        batch_id = uuid.uuid4().hex[:12]
        safe_name = sanitize_filename(channel_name) or "youtube"
        batch_folder = os.path.join(self.base_temp_dir, batch_id)
        os.makedirs(batch_folder, exist_ok=True)

        batch_info = {
            "batch_id": batch_id,
            "channel_name": safe_name,
            "quality": quality,
            "batch_folder": batch_folder,
            "items": items,
            "total_items": len(items),
            "completed_items": 0,
            "failed_items": 0,
            "current_title": "",
            "current_percent": 0.0,
            "current_speed": "0 KB/s",
            "overall_percent": 0.0,
            "status": "downloading",  # downloading, zipping, completed, error
            "zip_filename": f"{safe_name}_{quality}_{batch_id}.zip",
            "zip_filepath": None,
            "zip_size_mb": 0.0,
            "error": None,
            "created_at": time.time()
        }

        with self._lock:
            self.batches[batch_id] = batch_info

        # Start background processing thread for this batch
        threading.Thread(target=self._process_batch, args=(batch_id,), daemon=True).start()
        return batch_id

    def get_batch_status(self, batch_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self.batches.get(batch_id)

    def schedule_delete_batch(self, batch_id: str, delay_seconds: int = 90):
        """Mark as downloaded and schedule folder purge after grace period."""
        with self._lock:
            if batch_id in self.batches:
                self.batches[batch_id]["status"] = "downloaded"
                self.batches[batch_id]["downloaded_at"] = time.time()
                
        def _delayed():
            time.sleep(delay_seconds)
            self.delete_batch(batch_id)
            
        threading.Thread(target=_delayed, daemon=True).start()

    def delete_batch(self, batch_id: str):
        """Delete the batch directory from disk to leave 0 storage."""
        with self._lock:
            self.batches.pop(batch_id, None)
        folder = os.path.join(self.base_temp_dir, batch_id)
        if os.path.exists(folder):
            with suppress(Exception):
                shutil.rmtree(folder, ignore_errors=True)

    def _auto_clean_loop(self):
        """Sweeper that purges any batch older than 30 minutes."""
        while True:
            time.sleep(300)  # Every 5 minutes
            cutoff = time.time() - 1800  # 30 mins ago
            expired = []
            with self._lock:
                for b_id, b_data in list(self.batches.items()):
                    if b_data.get("created_at", 0) < cutoff:
                        expired.append(b_id)
            for b_id in expired:
                self.delete_batch(b_id)

    def _process_batch(self, batch_id: str):
        with self._lock:
            batch = self.batches.get(batch_id)
        if not batch:
            return

        batch_folder = batch["batch_folder"]
        items = batch["items"]
        quality = batch["quality"]
        total = len(items)

        # Format selector based on requested quality
        if quality == "audio_mp3":
            format_str = "bestaudio/best"
            postprocessors = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        elif quality == "720p":
            format_str = "bestvideo[vcodec^=avc1][height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720][ext=mp4]/best[ext=mp4]/best"
            postprocessors = []
        elif quality == "480p":
            format_str = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]"
            postprocessors = []
        elif quality == "360p":
            format_str = "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]"
            postprocessors = []
        else: # 1080p
            format_str = "bestvideo[vcodec^=avc1][height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080][ext=mp4]/best[ext=mp4]/best"
            postprocessors = []

        outtmpl = os.path.join(batch_folder, "%(title)s [%(id)s].%(ext)s")

        for idx, item in enumerate(items):
            url = item.get("url") or f"https://www.youtube.com/watch?v={item['id']}"
            title = item.get("title", "Video")
            
            with self._lock:
                batch["current_title"] = title
                batch["current_percent"] = 0.0

            def _progress_hook(d):
                if d['status'] == 'downloading':
                    tot = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    down = d.get('downloaded_bytes') or 0
                    pct = round((down / tot * 100), 1) if tot > 0 else 0.0
                    spd = d.get('speed') or 0
                    speed_str = f"{spd / 1024 / 1024:.1f} MB/s" if spd > 1024 * 1024 else f"{spd / 1024:.0f} KB/s"
                    
                    with self._lock:
                        batch["current_percent"] = pct
                        batch["current_speed"] = speed_str
                        # Overall percentage
                        overall = round(((idx + (pct / 100.0)) / total) * 90.0, 1)
                        batch["overall_percent"] = min(overall, 90.0)

            ydl_opts = {
                'format': format_str,
                'outtmpl': outtmpl,
                'merge_output_format': 'mp4' if quality != "audio_mp3" else None,
                'progress_hooks': [_progress_hook],
                'postprocessors': postprocessors,
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
                'noprogress': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': HD_CLIENTS
                    }
                }
            }

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                with self._lock:
                    batch["completed_items"] += 1
            except Exception as e:
                with self._lock:
                    batch["failed_items"] += 1

        # Phase 2: Create ZIP Archive
        with self._lock:
            batch["status"] = "zipping"
            batch["current_title"] = "Packaging files into ZIP..."
            batch["overall_percent"] = 92.0

        zip_filepath = os.path.join(batch_folder, batch["zip_filename"])
        
        # Collect all downloaded video/audio files
        media_files = []
        for root, _, files in os.walk(batch_folder):
            for file in files:
                if not file.endswith(".zip") and not file.startswith("."):
                    media_files.append(os.path.join(root, file))

        if not media_files:
            with self._lock:
                batch["status"] = "error"
                batch["error"] = "No videos could be downloaded from YouTube."
            return

        try:
            # ZIP_STORED avoids re-compressing already compressed video files (runs at multiple GB/s)
            with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_STORED) as zf:
                for fpath in media_files:
                    zf.write(fpath, arcname=os.path.basename(fpath))

            # Delete individual video files to instantly free disk space!
            for fpath in media_files:
                with suppress(Exception):
                    os.remove(fpath)

            zip_size = os.path.getsize(zip_filepath) / (1024 * 1024)  # MB

            with self._lock:
                batch["status"] = "completed"
                batch["overall_percent"] = 100.0
                batch["zip_filepath"] = zip_filepath
                batch["zip_size_mb"] = round(zip_size, 1)
                batch["current_title"] = "Ready for download!"
        except Exception as e:
            with self._lock:
                batch["status"] = "error"
                batch["error"] = f"Failed to create ZIP: {str(e)}"
