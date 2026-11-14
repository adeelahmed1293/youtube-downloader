// Service worker for YouTube Bulk & Shorts Downloader

// Sanitize filename for safe local disk storage
function sanitizeFilename(name) {
  return (name || "video").replace(/[\\/:*?"<>|]/g, "").trim().substring(0, 100);
}

// Global active batch state
let activeBatch = null;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === "START_BATCH_DOWNLOAD") {
    handleBatchDownload(msg.payload, sendResponse);
    return true; // Keep message channel open for async response
  }
  
  if (msg.action === "GET_BATCH_STATUS") {
    sendResponse({ success: true, batch: activeBatch });
    return false;
  }
  
  if (msg.action === "CANCEL_BATCH") {
    if (activeBatch) {
      activeBatch.cancelled = true;
      activeBatch.status = "cancelled";
    }
    sendResponse({ success: true });
    return false;
  }
});

// Resolve stream download URL for a video/short
async function resolveDownloadUrl(videoId, quality) {
  // Option 1: Cobalt Open Stream Resolver API
  const cobaltEndpoints = [
    "https://cobalt-api.kwiatekm.pl",
    "https://api.cobalt.tools",
    "https://cobalt.canine.tools"
  ];

  const targetUrl = `https://www.youtube.com/watch?v=${videoId}`;
  const isAudio = quality === "audio_mp3";

  for (const endpoint of cobaltEndpoints) {
    try {
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          url: targetUrl,
          videoQuality: quality === "1080p" ? "1080" : (quality === "720p" ? "720" : "480"),
          downloadMode: isAudio ? "audio" : "auto",
          audioFormat: isAudio ? "mp3" : undefined,
          youtubeVideoCodec: "h264"
        })
      });

      if (resp.ok) {
        const data = await resp.json();
        if (data.url) {
          return { streamUrl: data.url, ext: isAudio ? "mp3" : "mp4" };
        }
      }
    } catch (e) {
      // Try next endpoint
    }
  }

  // Option 2: Fallback to Invidious / Piped API
  const invidiousInstances = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://yewtu.be"
  ];

  for (const instance of invidiousInstances) {
    try {
      const resp = await fetch(`${instance}/api/v1/videos/${videoId}`);
      if (resp.ok) {
        const data = await resp.json();
        const formats = data.formatStreams || [];
        if (formats.length > 0) {
          // Sort by resolution
          formats.sort((a, b) => (parseInt(b.resolution) || 0) - (parseInt(a.resolution) || 0));
          return { streamUrl: formats[0].url, ext: "mp4" };
        }
      }
    } catch (e) {
      // Continue
    }
  }

  throw new Error("Could not resolve stream URL for " + videoId);
}

// Sequentially downloads batch items into Chrome Downloads folder
async function handleBatchDownload(payload, sendResponse) {
  const { items, quality, channelName } = payload;

  if (!items || items.length === 0) {
    sendResponse({ success: false, error: "No items to download" });
    return;
  }

  const safeFolder = sanitizeFilename(channelName || "YouTube_Shorts");
  
  activeBatch = {
    total: items.length,
    completed: 0,
    failed: 0,
    currentIndex: 0,
    currentTitle: "",
    status: "downloading",
    cancelled: false
  };

  sendResponse({ success: true, message: "Batch download started" });

  for (let i = 0; i < items.length; i++) {
    if (activeBatch.cancelled) break;

    const item = items[i];
    activeBatch.currentIndex = i + 1;
    activeBatch.currentTitle = item.title;

    try {
      const { streamUrl, ext } = await resolveDownloadUrl(item.id, quality);
      const safeTitle = sanitizeFilename(item.title);
      const filename = `YouTube_Shorts/${safeFolder}/${safeTitle} [${item.id}].${ext}`;

      await new Promise((resolve, reject) => {
        chrome.downloads.download({
          url: streamUrl,
          filename: filename,
          conflictAction: "uniquify",
          saveAs: false
        }, (downloadId) => {
          if (chrome.runtime.lastError || !downloadId) {
            reject(chrome.runtime.lastError || new Error("Download failed to start"));
          } else {
            resolve(downloadId);
          }
        });
      });

      activeBatch.completed++;
    } catch (err) {
      console.warn("Item download failed:", item.title, err);
      activeBatch.failed++;
    }

    // Small delay between downloads to prevent throttling
    await new Promise(r => setTimeout(r, 800));
  }

  activeBatch.status = activeBatch.cancelled ? "cancelled" : "completed";
}
