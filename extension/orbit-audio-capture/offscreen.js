let audioContext = null;
let mediaStream = null;
let source = null;
let processor = null;
let socket = null;
let visualTimer = null;
let visualVideo = null;
let previousVisualThumbnail = null;
let lastSentVisualThumbnail = null;
let lastVisualSentAt = 0;
let captureStartedAt = 0;

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== "ORBIT_OFFSCREEN_START") return false;

  startCapture(message)
    .then(() => sendResponse({ ok: true }))
    .catch((error) => {
      console.error("Orbit offscreen capture failed:", error);
      sendResponse({ ok: false, error: String(error) });
    });
  return true;
});

async function startCapture(config) {
  await stopCapture();

  try {
    const audioFormat = config.audioFormat || {};
    const visualConfig = config.visualCapture || {};
    const visualEnabled = Boolean(visualConfig.enabled);
    captureStartedAt = performance.now();
    const sampleRate = Number(audioFormat.sampleRate || 16000);
    const channels = Number(audioFormat.channels || 1);

    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: "tab",
          chromeMediaSourceId: config.streamId
        }
      },
      video: visualEnabled ? {
        mandatory: {
          chromeMediaSource: "tab",
          chromeMediaSourceId: config.streamId,
          maxFrameRate: 5
        }
      } : false
    });

    audioContext = new AudioContext({ sampleRate });
    await audioContext.resume();
    const actualSampleRate = audioContext.sampleRate;

    socket = new WebSocket(config.webSocketUrl);
    socket.binaryType = "arraybuffer";
    await waitForSocketOpen(socket);
    const activeSocket = socket;
    activeSocket.addEventListener("close", () => {
      if (socket !== activeSocket) return;
      socket = null;
      void stopCapture();
    });
    activeSocket.send(JSON.stringify({
      type: "start",
      encoding: "linear16",
      sample_rate: actualSampleRate,
      channels,
      session_id: config.sessionId,
      meeting_id: config.meetingId
    }));

    source = audioContext.createMediaStreamSource(mediaStream);
    processor = audioContext.createScriptProcessor(4096, 1, 1);
    processor.onaudioprocess = (event) => {
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      const pcm16 = convertToMonoPcm16(event.inputBuffer);
      if (pcm16.byteLength > 0) socket.send(pcm16.buffer);
    };

    source.connect(audioContext.destination);
    source.connect(processor);
    processor.connect(audioContext.destination);

    if (visualEnabled && mediaStream.getVideoTracks().length > 0) {
      startVisualSampling(mediaStream, visualConfig);
    }
  } catch (error) {
    await stopCapture();
    throw error;
  }
}

function startVisualSampling(stream, config) {
  visualVideo = document.createElement("video");
  visualVideo.muted = true;
  visualVideo.autoplay = true;
  visualVideo.playsInline = true;
  visualVideo.srcObject = stream;
  void visualVideo.play();

  const sampleIntervalMs = Math.max(1000, Number(config.sampleIntervalMs || 3000));
  visualTimer = setInterval(() => sampleVisualFrame(config), sampleIntervalMs);
}

function sampleVisualFrame(config) {
  if (
    !visualVideo ||
    visualVideo.readyState < 2 ||
    !visualVideo.videoWidth ||
    !visualVideo.videoHeight ||
    !socket ||
    socket.readyState !== WebSocket.OPEN
  ) return;

  const crop = insetCrop(visualVideo.videoWidth, visualVideo.videoHeight, 0.08);
  const thumbnail = createThumbnail(visualVideo, crop);
  const nowMs = performance.now();
  const options = {
    current: thumbnail,
    previousSample: previousVisualThumbnail,
    lastSent: lastSentVisualThumbnail,
    nowMs,
    lastSentAt: lastVisualSentAt,
    stabilityThreshold: Number(config.stabilityThreshold || 0.02),
    changeThreshold: Number(config.changeThreshold || 0.08),
    cooldownMs: Math.max(1000, Number(config.cooldownMs || 8000))
  };

  const shouldSend = OrbitFrameChange.shouldSendFrame(options);
  previousVisualThumbnail = thumbnail;
  if (!shouldSend) return;

  const maxWidth = Math.max(320, Number(config.maxWidth || 1280));
  const scale = Math.min(1, maxWidth / crop.width);
  const width = Math.max(1, Math.round(crop.width * scale));
  const height = Math.max(1, Math.round(crop.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { alpha: false });
  context.drawImage(
    visualVideo,
    crop.x,
    crop.y,
    crop.width,
    crop.height,
    0,
    0,
    width,
    height
  );

  const changeScore = lastSentVisualThumbnail
    ? OrbitFrameChange.thumbnailDifference(lastSentVisualThumbnail, thumbnail)
    : 1;
  socket.send(JSON.stringify({
    type: "visual_frame",
    timestamp_ms: Math.max(0, Math.round(nowMs - captureStartedAt)),
    image_data_url: canvas.toDataURL("image/jpeg", Number(config.jpegQuality || 0.65)),
    width,
    height,
    change_score: Number(changeScore.toFixed(4))
  }));
  lastSentVisualThumbnail = thumbnail;
  lastVisualSentAt = nowMs;
}

function createThumbnail(video, crop) {
  const canvas = document.createElement("canvas");
  canvas.width = 32;
  canvas.height = 18;
  const context = canvas.getContext("2d", { alpha: false, willReadFrequently: true });
  context.drawImage(video, crop.x, crop.y, crop.width, crop.height, 0, 0, 32, 18);
  const pixels = context.getImageData(0, 0, 32, 18).data;
  const grayscale = new Uint8Array(32 * 18);
  for (let pixel = 0, output = 0; pixel < pixels.length; pixel += 4, output += 1) {
    grayscale[output] = Math.round(
      pixels[pixel] * 0.299 + pixels[pixel + 1] * 0.587 + pixels[pixel + 2] * 0.114
    );
  }
  return grayscale;
}

function insetCrop(width, height, insetRatio) {
  const insetX = Math.round(width * insetRatio);
  const insetY = Math.round(height * insetRatio);
  return {
    x: insetX,
    y: insetY,
    width: Math.max(1, width - insetX * 2),
    height: Math.max(1, height - insetY * 2)
  };
}

async function stopCapture() {
  if (visualTimer) {
    clearInterval(visualTimer);
    visualTimer = null;
  }
  if (visualVideo) {
    visualVideo.pause();
    visualVideo.srcObject = null;
    visualVideo.remove();
    visualVideo = null;
  }
  previousVisualThumbnail = null;
  lastSentVisualThumbnail = null;
  lastVisualSentAt = 0;
  captureStartedAt = 0;
  if (source) {
    source.disconnect();
    source = null;
  }
  if (processor) {
    processor.disconnect();
    processor = null;
  }
  if (audioContext) {
    await audioContext.close();
    audioContext = null;
  }
  if (mediaStream) {
    for (const track of mediaStream.getTracks()) track.stop();
    mediaStream = null;
  }
  const activeSocket = socket;
  socket = null;
  if (activeSocket && activeSocket.readyState !== WebSocket.CLOSED) {
    if (activeSocket.readyState === WebSocket.OPEN) {
      activeSocket.send(JSON.stringify({ type: "stop" }));
    }
    activeSocket.close();
  }
}

function waitForSocketOpen(targetSocket) {
  return new Promise((resolve, reject) => {
    targetSocket.onopen = resolve;
    targetSocket.onerror = () => reject(new Error("Orbit audio WebSocket failed to open."));
    targetSocket.onclose = () => reject(new Error("Orbit audio WebSocket closed before opening."));
  });
}

function convertToMonoPcm16(inputBuffer) {
  const length = inputBuffer.length;
  const channels = inputBuffer.numberOfChannels;
  const output = new Int16Array(length);

  for (let index = 0; index < length; index += 1) {
    let sample = 0;
    for (let channel = 0; channel < channels; channel += 1) {
      sample += inputBuffer.getChannelData(channel)[index];
    }
    sample /= Math.max(channels, 1);
    sample = Math.max(-1, Math.min(1, sample));
    output[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }

  return output;
}
