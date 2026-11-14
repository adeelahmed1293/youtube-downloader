// In-page content script for YouTube Bulk & Shorts Downloader

let detectedVideos = [];
let selectedVideoIds = new Set();
let modalOpen = false;

// Initialize on page load and YouTube navigation
function init() {
  injectFloatingButton();
  scanPageVideos();

  // Watch for dynamic DOM changes as user scrolls
  const observer = new MutationObserver(() => {
    scanPageVideos();
  });
  observer.observe(document.body, { childList: true, subtree: true });
}

// Extract Video ID from URL or attributes
function extractIdFromHref(href) {
  if (!href) return null;
  const matchShort = href.match(/\/shorts\/([a-zA-Z0-9_-]{11})/);
  if (matchShort) return matchShort[1];
  const matchWatch = href.match(/[?&]v=([a-zA-Z0-9_-]{11})/);
  if (matchWatch) return matchWatch[1];
  return null;
}

// Scans all video and shorts cards visible on the YouTube page
function scanPageVideos() {
  const elements = document.querySelectorAll(
    'ytd-rich-item-renderer, ytd-reel-item-renderer, ytd-grid-video-renderer, ytd-video-renderer'
  );

  const seenIds = new Set(detectedVideos.map(v => v.id));

  elements.forEach(el => {
    const link = el.querySelector('a#thumbnail, a.ytd-thumbnail, a[href*="/shorts/"], a[href*="/watch"]');
    if (!link) return;

    const href = link.getAttribute('href');
    const vId = extractIdFromHref(href);
    if (!vId || seenIds.has(vId)) return;

    // Title
    const titleEl = el.querySelector('#video-title, #video-title-link, .ytd-reel-item-renderer #video-title');
    const title = titleEl ? titleEl.textContent.trim() : (el.querySelector('h3')?.textContent.trim() || "YouTube Short");

    // Thumbnail
    const img = el.querySelector('img');
    const thumb = img ? (img.src || img.getAttribute('data-thumb') || "") : `https://i.ytimg.com/vi/${vId}/hqdefault.jpg`;

    // Is Short?
    const isShort = href.includes('/shorts/') || el.tagName.toLowerCase().includes('reel');

    detectedVideos.push({
      id: vId,
      title: title,
      url: `https://www.youtube.com/watch?v=${vId}`,
      thumbnail: thumb || `https://i.ytimg.com/vi/${vId}/hqdefault.jpg`,
      isShort: isShort
    });
    seenIds.add(vId);
  });

  updateFloatingBadge();
}

// Injects floating launcher button
function injectFloatingButton() {
  if (document.getElementById('ytd-bulk-float-btn')) return;

  const btn = document.createElement('div');
  btn.id = 'ytd-bulk-float-btn';
  btn.innerHTML = `
    <span>⚡ Bulk Downloader</span>
    <span class="count-badge" id="ytd-float-count">0</span>
  `;
  btn.onclick = openModal;
  document.body.appendChild(btn);
}

function updateFloatingBadge() {
  const badge = document.getElementById('ytd-float-count');
  if (badge) {
    badge.textContent = detectedVideos.length;
  }
}

// Creates and opens modal overlay
function openModal() {
  let overlay = document.getElementById('ytd-bulk-modal-overlay');
  if (!overlay) {
    overlay = createModalDOM();
    document.body.appendChild(overlay);
  }

  renderModalCards();
  overlay.classList.add('active');
  modalOpen = true;
}

function closeModal() {
  const overlay = document.getElementById('ytd-bulk-modal-overlay');
  if (overlay) {
    overlay.classList.remove('active');
  }
  modalOpen = false;
}

function createModalDOM() {
  const overlay = document.createElement('div');
  overlay.id = 'ytd-bulk-modal-overlay';
  overlay.onclick = (e) => {
    if (e.target === overlay) closeModal();
  };

  overlay.innerHTML = `
    <div id="ytd-bulk-modal-box">
      <!-- Header -->
      <div class="ytd-modal-header">
        <h2>
          <span>⚡ YouTube Bulk & Shorts Downloader</span>
        </h2>
        <button class="ytd-modal-close" id="ytd-btn-close">✕</button>
      </div>

      <!-- Controls -->
      <div class="ytd-modal-controls">
        <input type="text" id="ytd-search-input" class="ytd-modal-search" placeholder="Search titles...">
        
        <div style="display: flex; gap: 8px;">
          <button class="ytd-btn-secondary" id="ytd-btn-select-all">Select All</button>
          <button class="ytd-btn-secondary" id="ytd-btn-filter-shorts">📱 Shorts Only</button>
          <button class="ytd-btn-secondary" id="ytd-btn-filter-all">✨ All</button>
        </div>

        <select id="ytd-quality-select" class="ytd-select">
          <option value="1080p">1080p Full HD</option>
          <option value="720p" selected>720p HD</option>
          <option value="480p">480p</option>
          <option value="audio_mp3">Audio MP3</option>
        </select>
      </div>

      <!-- Cards Grid -->
      <div class="ytd-modal-grid" id="ytd-cards-grid"></div>

      <!-- Footer -->
      <div class="ytd-modal-footer">
        <div id="ytd-status-text" style="font-size: 13px; color: #94a3b8;">
          Ready to download
        </div>
        <button class="ytd-btn-download" id="ytd-btn-start-dl" disabled>
          Download Selected (0)
        </button>
      </div>
    </div>
  `;

  // Attach event listeners
  overlay.querySelector('#ytd-btn-close').onclick = closeModal;
  overlay.querySelector('#ytd-search-input').oninput = filterGrid;
  overlay.querySelector('#ytd-btn-select-all').onclick = toggleSelectAll;
  overlay.querySelector('#ytd-btn-filter-shorts').onclick = () => filterType('shorts');
  overlay.querySelector('#ytd-btn-filter-all').onclick = () => filterType('all');
  overlay.querySelector('#ytd-btn-start-dl').onclick = startDownload;

  return overlay;
}

let activeFilter = 'all';

function filterType(type) {
  activeFilter = type;
  renderModalCards();
}

function filterGrid() {
  const query = document.getElementById('ytd-search-input').value.toLowerCase().trim();
  const cards = document.querySelectorAll('.ytd-item-card');
  cards.forEach(card => {
    const title = card.getAttribute('data-title').toLowerCase();
    if (!query || title.includes(query)) {
      card.style.display = 'flex';
    } else {
      card.style.display = 'none';
    }
  });
}

function renderModalCards() {
  const grid = document.getElementById('ytd-cards-grid');
  if (!grid) return;
  grid.innerHTML = '';

  const items = detectedVideos.filter(v => {
    if (activeFilter === 'shorts') return v.isShort;
    return true;
  });

  if (items.length === 0) {
    grid.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: #64748b;">
        No videos found on this page. Scroll down on YouTube to load more videos!
      </div>
    `;
    updateDownloadBtn();
    return;
  }

  items.forEach(v => {
    const isSelected = selectedVideoIds.has(v.id);
    const card = document.createElement('div');
    card.className = `ytd-item-card ${isSelected ? 'selected' : ''}`;
    card.setAttribute('data-id', v.id);
    card.setAttribute('data-title', v.title);

    card.innerHTML = `
      <div class="ytd-item-thumb">
        <img src="${v.thumbnail}" loading="lazy">
        <input type="checkbox" class="ytd-item-check" ${isSelected ? 'checked' : ''}>
        <span class="ytd-item-duration">${v.isShort ? 'SHORT' : 'VIDEO'}</span>
      </div>
      <div class="ytd-item-info">
        <div class="ytd-item-title" title="${v.title}">${v.title}</div>
      </div>
    `;

    card.onclick = () => toggleSelect(v.id);
    grid.appendChild(card);
  });

  updateDownloadBtn();
}

function toggleSelect(id) {
  if (selectedVideoIds.has(id)) {
    selectedVideoIds.delete(id);
  } else {
    selectedVideoIds.add(id);
  }

  const card = document.querySelector(`.ytd-item-card[data-id="${id}"]`);
  if (card) {
    const isSel = selectedVideoIds.has(id);
    card.classList.toggle('selected', isSel);
    const check = card.querySelector('.ytd-item-check');
    if (check) check.checked = isSel;
  }

  updateDownloadBtn();
}

function toggleSelectAll() {
  const items = detectedVideos.filter(v => activeFilter === 'shorts' ? v.isShort : true);
  if (selectedVideoIds.size === items.length && items.length > 0) {
    selectedVideoIds.clear();
  } else {
    items.forEach(v => selectedVideoIds.add(v.id));
  }
  renderModalCards();
}

function updateDownloadBtn() {
  const btn = document.getElementById('ytd-btn-start-dl');
  if (!btn) return;
  const count = selectedVideoIds.size;
  btn.textContent = `Download Selected (${count})`;
  btn.disabled = count === 0;
}

// Starts batch download via Chrome background service worker
async function startDownload() {
  const selectedItems = detectedVideos.filter(v => selectedVideoIds.has(v.id));
  if (selectedItems.length === 0) return;

  const quality = document.getElementById('ytd-quality-select').value;
  const btn = document.getElementById('ytd-btn-start-dl');
  const statusText = document.getElementById('ytd-status-text');

  btn.disabled = true;
  statusText.textContent = `Starting download for ${selectedItems.length} items...`;

  // Determine channel name from page title or header
  const channelHeader = document.querySelector('ytd-channel-name yt-formatted-string, #channel-name');
  const channelName = channelHeader ? channelHeader.textContent.trim() : "YouTube_Shorts";

  chrome.runtime.sendMessage({
    action: "START_BATCH_DOWNLOAD",
    payload: {
      items: selectedItems,
      quality: quality,
      channelName: channelName
    }
  }, (resp) => {
    if (resp && resp.success) {
      statusText.innerHTML = `🚀 Downloading directly to <b>Downloads/YouTube_Shorts/</b>`;
      pollProgress();
    } else {
      statusText.textContent = "Error: " + (resp?.error || "Could not start download");
      btn.disabled = false;
    }
  });
}

function pollProgress() {
  const statusText = document.getElementById('ytd-status-text');
  const interval = setInterval(() => {
    chrome.runtime.sendMessage({ action: "GET_BATCH_STATUS" }, (resp) => {
      if (resp && resp.batch) {
        const b = resp.batch;
        statusText.innerHTML = `Downloading ${b.currentIndex}/${b.total} (${b.completed} done): <i>${b.currentTitle.substring(0, 30)}...</i>`;

        if (b.status === "completed") {
          clearInterval(interval);
          statusText.innerHTML = `🎉 <b>Complete!</b> Downloaded ${b.completed} files directly into Downloads folder.`;
          document.getElementById('ytd-btn-start-dl').disabled = false;
        }
      } else {
        clearInterval(interval);
      }
    });
  }, 1000);
}

// Start content script
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
