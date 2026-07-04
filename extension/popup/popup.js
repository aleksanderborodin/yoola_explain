document.getElementById("summarize").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id == null) return;
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "summarize-current" });
    window.close();
  } catch {
    // No content script here (chrome:// pages, the PDF viewer, web store).
    const button = document.getElementById("summarize");
    button.disabled = true;
    button.textContent = "Can't run on this page";
    document.querySelector(".fine").textContent =
      "Chrome doesn't let extensions run on this page type (PDF viewer, browser pages). " +
      "For a PDF: go back to the page that links to it and right-click the link → " +
      "Summarize linked document with Yoola.";
  }
});
