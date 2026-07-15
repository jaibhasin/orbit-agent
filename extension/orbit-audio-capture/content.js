const ALLOW_MEDIA_PATTERN = /allow\s+(?:microphone\s+and\s+camera|camera\s+and\s+microphone)/i;

function controlLabel(node) {
  if (!node) return "";
  return [
    node.getAttribute && node.getAttribute("aria-label"),
    node.getAttribute && node.getAttribute("title"),
    node.textContent
  ].filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
}

function isAllowMediaControl(node) {
  return Boolean(node && ALLOW_MEDIA_PATTERN.test(controlLabel(node)));
}

function suppressAllowMediaControls(root) {
  if (!root || typeof root.querySelectorAll !== "function") return;
  for (const node of root.querySelectorAll("button, [role='button']")) {
    if (!isAllowMediaControl(node) || node.dataset.orbitSuppressed === "allow-media") continue;
    node.dataset.orbitSuppressed = "allow-media";
    node.style.display = "none";
  }
}

if (typeof document.addEventListener === "function") {
  document.addEventListener("click", (event) => {
    const control = event.target && event.target.closest
      ? event.target.closest("button, [role='button']")
      : null;
    if (!isAllowMediaControl(control)) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
  }, true);
}

suppressAllowMediaControls(document);
if (typeof MutationObserver !== "undefined" && document.documentElement) {
  new MutationObserver(() => suppressAllowMediaControls(document)).observe(
    document.documentElement,
    { childList: true, subtree: true }
  );
}

window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  const message = event.data || {};
  if (message.source !== "orbit" || message.type !== "ORBIT_START_CAPTURE") return;

  chrome.runtime.sendMessage({
    type: "ORBIT_CAPTURE_CONFIG",
    sessionId: message.sessionId,
    meetingId: message.meetingId,
    webSocketUrl: message.webSocketUrl,
    audioFormat: message.audioFormat || {
      encoding: "linear16",
      sampleRate: 16000,
      channels: 1
    },
    visualCapture: message.visualCapture || { enabled: false }
  }, () => {
    injectStartButton();
  });
});

chrome.runtime.onMessage.addListener((message) => {
  if (!message || message.type !== "ORBIT_CAPTURE_STATUS") return false;
  updateCaptureButton(message);
  return false;
});

function injectStartButton() {
  if (document.getElementById("orbit-audio-capture-button")) return;

  const button = document.createElement("button");
  button.id = "orbit-audio-capture-button";
  button.type = "button";
  button.textContent = "Start Orbit capture";
  button.style.cssText = [
    "position:fixed",
    "z-index:2147483647",
    "right:24px",
    "bottom:24px",
    "padding:10px 14px",
    "border-radius:999px",
    "border:0",
    "background:#111827",
    "color:#fff",
    "font:600 13px sans-serif",
    "box-shadow:0 8px 24px rgba(0,0,0,.28)",
    "cursor:pointer"
  ].join(";");

  button.addEventListener("click", () => {
    button.textContent = "Starting Orbit capture...";
    chrome.runtime.sendMessage({ type: "ORBIT_USER_START_CAPTURE" }, (response) => {
      updateCaptureButton(response, chrome.runtime.lastError?.message);
    });
  });

  document.documentElement.appendChild(button);
}

function updateCaptureButton(response, runtimeError) {
  const button = document.getElementById("orbit-audio-capture-button");
  if (!button) return;

  if (response && response.ok) {
    button.textContent = "Orbit capture active";
    button.disabled = true;
    button.style.opacity = "0.72";
    return;
  }

  button.textContent = "Use Alt+Shift+O or the extension icon";
  console.warn(
    "Orbit capture did not start. Use the extension shortcut or icon:",
    runtimeError || (response && response.error)
  );
}
