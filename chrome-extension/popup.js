// Popup logic for YouTube Bulk & Shorts Downloader

document.addEventListener('DOMContentLoaded', async () => {
  const pageTitle = document.getElementById('current-page-title');
  const btnOpenInPage = document.getElementById('btn-open-in-page');
  const manualInput = document.getElementById('manual-url');
  const btnFetchUrl = document.getElementById('btn-fetch-url');

  // Query active tab
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  if (tab && tab.url && tab.url.includes('youtube.com')) {
    pageTitle.textContent = tab.title.replace(' - YouTube', '');
  } else {
    pageTitle.textContent = "Not on YouTube. Open YouTube to scan.";
    document.querySelector('.status-indicator').classList.remove('active');
  }

  // Open Downloader inside active YouTube tab
  btnOpenInPage.onclick = async () => {
    if (tab && tab.url && tab.url.includes('youtube.com')) {
      chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
          if (typeof openModal === 'function') {
            openModal();
          } else {
            alert("Please refresh the YouTube tab to activate downloader!");
          }
        }
      });
      window.close(); // Close popup so user sees full in-page overlay
    } else {
      // Navigate current tab to YouTube
      chrome.tabs.create({ url: "https://www.youtube.com" });
      window.close();
    }
  };

  // Inspect manual URL
  btnFetchUrl.onclick = () => {
    const url = manualInput.value.trim();
    if (!url) return;
    chrome.tabs.create({ url: url });
    window.close();
  };
});
