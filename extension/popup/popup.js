document.getElementById("summarize").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id == null) return;
  // The worker delivers to the content script, injecting it first if the tab
  // predates the last extension reload. A failure here means Chrome genuinely
  // won't let extensions touch this page.
  const reply = await chrome.runtime.sendMessage({ type: "popup-summarize", tabId: tab.id });
  if (reply?.ok) {
    window.close();
    return;
  }
  const button = document.getElementById("summarize");
  button.disabled = true;
  button.textContent = "Can't run on this page";
  document.querySelector(".fine").textContent =
    "Chrome doesn't let extensions run on this page type (PDF viewer, browser pages, " +
    "the web store). For a PDF: go back to the page that links to it and right-click " +
    "the link → Summarize linked document with Yoola.";
});
