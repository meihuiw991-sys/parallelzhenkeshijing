const VIDEO_WIDTH = 1248;
const VIDEO_HEIGHT = 720;
const VIDEO_FPS = 24;
const INPUT_JPEG_QUALITY = 0.85;

const screen = document.querySelector(".screen");
const cameraVideo = document.getElementById("cameraVideo");
const renderCanvas = document.getElementById("renderCanvas");
const captureCanvas = document.getElementById("captureCanvas");
const travelToggle = document.getElementById("travelToggle");
const reconBar = document.getElementById("reconBar");
const reconIcon = document.getElementById("reconIcon");
const reconTitle = document.getElementById("reconTitle");
const renderStatus = document.getElementById("renderStatus");

let cameraStream = null;
let renderSocket = null;
let captureTimer = null;
let renderEnabled = false;
let modelReady = false;
let pendingOutputMeta = null;
let sequence = 0;
let statusTimer = null;
let renderAttempt = 0;

window.ParallelVerse = window.ParallelVerse || {};
window.ParallelVerse.voice = {
  supported: false,
  start: async () => { throw new Error("语音理解功能尚未启用"); },
  stop: async () => {},
};

travelToggle.setAttribute("role", "switch");
travelToggle.setAttribute("tabindex", "0");
travelToggle.setAttribute("aria-checked", "false");
travelToggle.addEventListener("click", toggleTravel);
travelToggle.addEventListener("keydown", event => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    toggleTravel();
  }
});

window.addEventListener("beforeunload", () => {
  stopRendering("page_unload");
  stopCamera();
});

initializeCamera();

async function initializeCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    showStatus("当前浏览器不支持摄像头访问", true, false);
    return;
  }
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: VIDEO_WIDTH },
        height: { ideal: VIDEO_HEIGHT },
        frameRate: { ideal: VIDEO_FPS, max: VIDEO_FPS },
        facingMode: "user",
      },
      audio: false,
    });
    cameraVideo.srcObject = cameraStream;
    await cameraVideo.play();
    screen.classList.add("camera-ready");
    showStatus("摄像头已连接", false);
  } catch (error) {
    showStatus(cameraErrorMessage(error), true, false);
  }
}

async function toggleTravel() {
  if (renderEnabled) {
    await stopRendering("client_request");
    return;
  }
  await startRendering();
}

async function startRendering() {
  if (!cameraStream) {
    await initializeCamera();
    if (!cameraStream) return;
  }

  const attempt = ++renderAttempt;
  renderEnabled = true;
  modelReady = false;
  sequence = 0;
  setTravelState(true);
  setReconstructionState("环境重构连接中", false);
  showStatus("正在读取渲染指令并连接模型…", false, false);

  try {
    const response = await fetch("/api/config/video-edit", { cache: "no-store" });
    if (!response.ok) throw new Error(await response.text());
    const { prompt } = await response.json();
    if (!prompt?.trim()) throw new Error("本地 prompt 为空");
    if (!renderEnabled || attempt !== renderAttempt) return;

    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const sessionId = `parallel-${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;
    const socket = new WebSocket(`${protocol}://${location.host}/ws/render/${sessionId}`);
    renderSocket = socket;
    socket.binaryType = "arraybuffer";
    socket.onopen = () => {
      if (!isCurrentRender(attempt, socket)) return socket.close(1000, "stale_session");
      socket.send(JSON.stringify({
        type: "start_stream_edit",
        prompt,
        options: { output_quality: 85, gate_enabled: false, use_pe: false },
      }));
    };
    socket.onmessage = event => handleRenderMessage(event, attempt, socket);
    socket.onerror = () => {
      if (isCurrentRender(attempt, socket)) failRendering("模型连接发生错误");
    };
    socket.onclose = event => {
      if (isCurrentRender(attempt, socket) && event.code !== 1000) {
        failRendering(`模型连接已断开 (${event.code})`);
      }
    };
  } catch (error) {
    failRendering(`无法开启穿越：${error.message || error}`);
  }
}

function handleRenderMessage(event, attempt, socket) {
  if (!isCurrentRender(attempt, socket)) return;
  if (typeof event.data !== "string") {
    if (!pendingOutputMeta) return;
    drawRenderedFrame(event.data, attempt, socket);
    pendingOutputMeta = null;
    return;
  }

  const message = JSON.parse(event.data);
  switch (message.type) {
    case "render_status":
      if (message.state === "queued") {
        setReconstructionState("等待模型资源", false);
        showStatus(`模型排队中，前方 ${message.ahead ?? "?"} 个会话`, false, false);
      }
      break;
    case "virtual_tryon_stream":
      modelReady = true;
      setReconstructionState("环境重构进行中", false);
      showStatus("模型已连接，正在生成首帧…", false, false);
      beginCapture();
      break;
    case "output_frame":
      pendingOutputMeta = message;
      break;
    case "model_event":
      if (["error", "session_timeout"].includes(message.event?.type)) {
        failRendering(`模型会话异常：${message.event.type}`);
      }
      break;
    case "error":
      failRendering(`${message.error_code}: ${message.message}`);
      break;
    case "virtual_tryon_stop":
      if (renderEnabled) failRendering("模型会话已停止");
      break;
  }
}

function beginCapture() {
  clearInterval(captureTimer);
  captureTimer = setInterval(captureFrame, 1000 / VIDEO_FPS);
}

function captureFrame() {
  if (!renderEnabled || !modelReady || renderSocket?.readyState !== WebSocket.OPEN || document.hidden) return;
  const attempt = renderAttempt;
  const socket = renderSocket;
  const context = captureCanvas.getContext("2d", { alpha: false });
  context.save();
  context.translate(VIDEO_WIDTH, 0);
  context.scale(-1, 1);
  context.drawImage(cameraVideo, 0, 0, VIDEO_WIDTH, VIDEO_HEIGHT);
  context.restore();
  captureCanvas.toBlob(blob => {
    if (!blob || !modelReady || !isCurrentRender(attempt, socket) || socket.readyState !== WebSocket.OPEN) return;
    sequence += 1;
    socket.send(JSON.stringify({
      type: "input_frame",
      seq: sequence,
      t_capture_ms: Date.now(),
      mime_type: "image/jpeg",
    }));
    socket.send(blob);
  }, "image/jpeg", INPUT_JPEG_QUALITY);
}

async function drawRenderedFrame(buffer, attempt, socket) {
  const bitmap = await createImageBitmap(new Blob([buffer], { type: "image/jpeg" }));
  if (!isCurrentRender(attempt, socket) || !modelReady) {
    bitmap.close();
    return;
  }
  const context = renderCanvas.getContext("2d", { alpha: false });
  context.drawImage(bitmap, 0, 0, VIDEO_WIDTH, VIDEO_HEIGHT);
  bitmap.close();
  if (!screen.classList.contains("travel-active")) {
    screen.classList.add("travel-active");
    setReconstructionState("环境重构完毕", true);
    showStatus("穿越画面已开启", false);
  }
}

async function stopRendering(reason, announce = true) {
  renderAttempt += 1;
  renderEnabled = false;
  modelReady = false;
  pendingOutputMeta = null;
  clearInterval(captureTimer);
  captureTimer = null;
  setTravelState(false);
  screen.classList.remove("travel-active");
  reconBar.classList.remove("show");
  renderCanvas.getContext("2d").clearRect(0, 0, VIDEO_WIDTH, VIDEO_HEIGHT);

  const socket = renderSocket;
  renderSocket = null;
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "tryon_stop" }));
    await new Promise(resolve => setTimeout(resolve, 100));
    socket.close(1000, reason);
  } else if (socket?.readyState === WebSocket.CONNECTING) {
    socket.close();
  }
  if (reason !== "page_unload" && announce) showStatus("已恢复原始摄像头画面", false);
}

function failRendering(message) {
  stopRendering("render_error", false).finally(() => showStatus(message, true, false));
}

function setTravelState(enabled) {
  travelToggle.classList.toggle("active", enabled);
  travelToggle.setAttribute("aria-checked", String(enabled));
  reconBar.classList.toggle("show", enabled);
}

function setReconstructionState(text, done) {
  reconTitle.textContent = text;
  reconIcon.classList.toggle("done", done);
}

function isCurrentRender(attempt, socket) {
  return renderEnabled && attempt === renderAttempt && socket === renderSocket;
}

function showStatus(message, error = false, autoHide = true) {
  clearTimeout(statusTimer);
  renderStatus.textContent = message;
  renderStatus.classList.toggle("error", error);
  renderStatus.classList.add("show");
  if (autoHide) statusTimer = setTimeout(() => renderStatus.classList.remove("show"), 2600);
}

function cameraErrorMessage(error) {
  if (error?.name === "NotAllowedError") return "摄像头权限被拒绝，请在浏览器设置中允许访问";
  if (error?.name === "NotFoundError") return "未检测到可用摄像头";
  return `摄像头启动失败：${error?.message || error}`;
}

function stopCamera() {
  cameraStream?.getTracks().forEach(track => track.stop());
  cameraStream = null;
}
