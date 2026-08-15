const assistantQuestionHints = document.getElementById("questionHints");
const assistantExpandedHeader = document.getElementById("expandedHeader");
const assistantQuestion = document.getElementById("expandedQ");
const assistantReply = document.getElementById("expandedA");
const assistantDetail = document.getElementById("dingDetail");
const assistantDetailTitle = assistantDetail.querySelector(".ding-detail-title");
const assistantDetailSub = assistantDetail.querySelector(".ding-detail-sub");
const assistantDetailBody = document.getElementById("dingDetailBody");

let assistantSocket = null;
let microphoneStream = null;
let inputAudioContext = null;
let outputAudioContext = null;
let captureNode = null;
let visionTimer = null;
let nextPlaybackTime = 0;
let playbackSources = new Set();
let userTranscript = "";
let assistantTranscript = "";
let assistantReady = false;
let microphoneRunning = false;
let audioInputConfirmed = false;
let capturedAudioChunks = 0;
let sentVisionFrames = 0;
let assistantInitializing = false;
let assistantInitializationError = null;

function voiceLog(message, details) {
  if (details === undefined) {
    console.info(`[ParallelVerse Voice] ${message}`);
  } else {
    console.info(`[ParallelVerse Voice] ${message}`, details);
  }
}

function voiceError(message, error) {
  console.error(`[ParallelVerse Voice] ${message}`, error);
}

window.ParallelVerse = window.ParallelVerse || {};
window.ParallelVerse.voice = {
  supported: true,
  start: initializeAssistant,
  stop: stopAssistant,
};

initializeAssistant();
window.addEventListener("beforeunload", stopAssistant);
document.addEventListener("click", resumeOutputAudio);
document.addEventListener("pointerdown", resumeOutputAudio);
document.addEventListener("keydown", resumeOutputAudio);

async function initializeAssistant() {
  if (assistantInitializing) return;
  if (microphoneStream && inputAudioContext && assistantSocket?.readyState === WebSocket.OPEN) return;
  assistantInitializing = true;
  assistantInitializationError = null;
  voiceLog("开始初始化语音助手", { secureContext: window.isSecureContext, origin: location.origin });
  setAssistantStatus("connecting", "语音助手连接中");
  try {
    if (!microphoneStream || !inputAudioContext) await startMicrophone();
    if (assistantSocket?.readyState !== WebSocket.OPEN) await connectAssistantSocket();
    startVisionSnapshots();
  } catch (error) {
    assistantInitializationError = error;
    voiceError("语音助手初始化失败", error);
    setAssistantStatus("error", error.message || String(error));
  } finally {
    assistantInitializing = false;
  }
}

function connectAssistantSocket() {
  return new Promise((resolve, reject) => {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const randomPart = crypto.randomUUID?.().slice(0, 8) || Math.random().toString(36).slice(2, 10);
    const sessionId = `assistant-${Date.now()}-${randomPart}`;
    voiceLog("正在连接本地 Assistant WebSocket", { sessionId });
    const socket = new WebSocket(`${protocol}://${location.host}/ws/assistant/${sessionId}`);
    assistantSocket = socket;
    const timeout = setTimeout(() => {
      socket.close();
      reject(new Error("本地 Assistant WebSocket 连接超时"));
    }, 10000);
    socket.onopen = () => {
      clearTimeout(timeout);
      voiceLog("本地 Assistant WebSocket 已连接", { sessionId });
      resolve();
    };
    socket.onmessage = handleAssistantMessage;
    socket.onerror = event => {
      clearTimeout(timeout);
      voiceError("本地 Assistant WebSocket 连接错误", event);
      reject(new Error("语音助手连接失败"));
    };
    socket.onclose = event => {
      clearTimeout(timeout);
      voiceLog("本地 Assistant WebSocket 已关闭", { code: event.code, reason: event.reason });
      assistantReady = false;
      if (event.code !== 1000) setAssistantStatus("error", `语音助手已断开 (${event.code})`);
    };
  });
}

async function startMicrophone() {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("当前浏览器不支持麦克风采集");
  voiceLog("开始申请麦克风权限");
  microphoneStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
    video: false,
  });
  voiceLog("麦克风权限已获得", {
    tracks: microphoneStream.getAudioTracks().map(track => ({
      label: track.label,
      enabled: track.enabled,
      muted: track.muted,
      readyState: track.readyState,
      settings: track.getSettings(),
    })),
  });
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) throw new Error("当前浏览器不支持 Web Audio API");
  inputAudioContext = new AudioContextClass();
  voiceLog("输入 AudioContext 已创建", { state: inputAudioContext.state, sampleRate: inputAudioContext.sampleRate });
  await inputAudioContext.audioWorklet.addModule("/static/audio-capture-worklet.js?v=20260815-2");
  voiceLog("AudioWorklet 模块加载完成");
  const source = inputAudioContext.createMediaStreamSource(microphoneStream);
  captureNode = new AudioWorkletNode(inputAudioContext, "pcm16-capture");
  const silentGain = inputAudioContext.createGain();
  silentGain.gain.value = 0;
  captureNode.port.onmessage = event => {
    capturedAudioChunks += 1;
    if (capturedAudioChunks === 1 || capturedAudioChunks % 50 === 0) {
      voiceLog("已采集 PCM16 音频分片", {
        count: capturedAudioChunks,
        bytes: event.data.byteLength,
        assistantReady,
        socketState: assistantSocket?.readyState,
      });
    }
    if (!assistantReady || assistantSocket?.readyState !== WebSocket.OPEN) return;
    assistantSocket.send(JSON.stringify({
      type: "audio_chunk",
      audio: arrayBufferToBase64(event.data),
    }));
  };
  source.connect(captureNode).connect(silentGain).connect(inputAudioContext.destination);
  await inputAudioContext.resume();
  microphoneRunning = inputAudioContext.state === "running";
  inputAudioContext.onstatechange = () => {
    voiceLog("输入 AudioContext 状态变化", { state: inputAudioContext.state });
    microphoneRunning = inputAudioContext.state === "running";
    refreshAssistantReadyStatus();
  };
  refreshAssistantReadyStatus();
  voiceLog("麦克风采集链路初始化完成", { state: inputAudioContext.state });
}

function handleAssistantMessage(event) {
  const message = JSON.parse(event.data);
  if (message.type !== "assistant_audio_delta") {
    voiceLog(`收到 Assistant 事件 ${message.type}`, JSON.stringify(message));
  }
  switch (message.type) {
    case "assistant_status":
      assistantReady = message.state === "ready";
      refreshAssistantReadyStatus();
      break;
    case "audio_input_ready":
      audioInputConfirmed = true;
      refreshAssistantReadyStatus();
      break;
    case "speech_started":
      cancelPlayback();
      userTranscript = "";
      assistantTranscript = "";
      updateDialogue();
      setAssistantStatus("ready", "正在聆听…");
      break;
    case "speech_stopped":
      setAssistantStatus("ready", "正在思考…");
      break;
    case "user_transcript_delta":
      userTranscript += message.delta || "";
      updateDialogue();
      break;
    case "user_transcript_completed":
      userTranscript = message.transcript || userTranscript;
      updateDialogue();
      break;
    case "assistant_text_delta":
      assistantTranscript += message.delta || "";
      updateDialogue();
      break;
    case "assistant_text_replace":
      assistantTranscript = message.text || "";
      updateDialogue();
      break;
    case "assistant_text_done":
    case "assistant_response_done":
      setAssistantStatus("ready", "可以继续对话");
      break;
    case "assistant_audio_delta":
      voiceLog("收到回复音频分片", { base64Length: message.audio?.length || 0 });
      queueAudio(message.audio);
      break;
    case "vision_analysis":
      updateVisionCard(message);
      break;
    case "assistant_route":
      if (message.route === "interaction") setAssistantStatus("ready", "正在理解当前画面…");
      break;
    case "assistant_error":
    case "error":
      voiceError("Assistant 返回错误", message);
      setAssistantStatus("error", message.message || "语音助手发生错误");
      break;
    case "assistant_tts_error":
      voiceError("Voice TTS 返回错误", message);
      setAssistantStatus("ready", message.message || "文本结果可用，语音播报失败");
      break;
  }
}

function setAssistantStatus(state, label) {
  assistantQuestionHints.classList.add("collapsed", "assistant-mode");
  let indicator = assistantExpandedHeader.querySelector(".assistant-connection");
  if (!indicator) {
    indicator = document.createElement("div");
    indicator.className = "assistant-connection";
    indicator.innerHTML = '<span class="assistant-connection-dot"></span><span></span>';
    assistantExpandedHeader.prepend(indicator);
  }
  indicator.className = `assistant-connection ${state}`;
  indicator.lastElementChild.textContent = label;
  updateDialogue();
}

function refreshAssistantReadyStatus() {
  if (!assistantReady) {
    setAssistantStatus("connecting", "语音助手连接中");
    return;
  }
  if (!microphoneRunning) {
    setAssistantStatus("error", "点击页面任意位置以启用麦克风");
    return;
  }
  if (!audioInputConfirmed) {
    setAssistantStatus("ready", "麦克风启动中…");
    return;
  }
  setAssistantStatus("ready", "可以开始对话");
}

function updateDialogue() {
  assistantQuestion.className = "question-q assistant-user-text";
  assistantReply.className = "question-a assistant-reply-text";
  assistantQuestion.textContent = userTranscript ? `你：${stripMarkdownBold(userTranscript)}` : "你可以直接开口和我对话";
  assistantReply.textContent = assistantTranscript ? `助手：${stripMarkdownBold(assistantTranscript)}` : "";
  assistantExpandedHeader.scrollTop = assistantExpandedHeader.scrollHeight;
}

function stripMarkdownBold(text) {
  return String(text || "").replaceAll("**", "");
}

function updateVisionCard(message) {
  if (message.state === "skipped") {
    assistantDetail.classList.add("show", "visual-error");
    assistantDetail.classList.remove("visual-loading");
    assistantDetailTitle.textContent = "视觉解析";
    assistantDetailSub.textContent = message.question || "当前画面";
    assistantDetailBody.textContent = "视觉模型未返回有效结果，已切换到普通对话。";
    return;
  }
  assistantDetail.classList.add("show");
  assistantDetail.classList.toggle("visual-loading", message.state === "loading");
  assistantDetail.classList.toggle("visual-error", message.state === "error");
  assistantDetailTitle.textContent = "视觉解析";
  assistantDetailSub.textContent = message.question || "当前画面";
  if (message.state === "loading") assistantDetailBody.textContent = "正在理解当前画面…";
  if (message.state === "completed") assistantDetailBody.textContent = stripMarkdownBold(message.result) || "未获得分析结果";
  if (message.state === "error") assistantDetailBody.textContent = stripMarkdownBold(message.message) || "视觉分析暂时不可用";
}

function startVisionSnapshots() {
  clearInterval(visionTimer);
  sendVisionSnapshot();
  visionTimer = setInterval(sendVisionSnapshot, 1000);
}

function sendVisionSnapshot() {
  if (!assistantReady || assistantSocket?.readyState !== WebSocket.OPEN) return;
  const camera = document.getElementById("cameraVideo");
  if (camera.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;

  const canvas = document.createElement("canvas");
  canvas.width = 640;
  canvas.height = 360;
  const context = canvas.getContext("2d", { alpha: false });
  context.translate(canvas.width, 0);
  context.scale(-1, 1);
  context.drawImage(camera, 0, 0, canvas.width, canvas.height);
  const image = canvas.toDataURL("image/jpeg", 0.65).split(",", 2)[1];
  assistantSocket.send(JSON.stringify({ type: "vision_frame", image }));
  sentVisionFrames += 1;
  if (sentVisionFrames === 1 || sentVisionFrames % 10 === 0) {
    voiceLog("已上传视觉快照", {
      count: sentVisionFrames,
      source: "camera",
      base64Length: image.length,
    });
  }
}

async function queueAudio(encodedAudio) {
  if (!encodedAudio) return;
  if (!outputAudioContext) outputAudioContext = new AudioContext();
  const bytes = base64ToUint8Array(encodedAudio);
  const pcm = new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2));
  const audioBuffer = outputAudioContext.createBuffer(1, pcm.length, 24000);
  const channel = audioBuffer.getChannelData(0);
  for (let index = 0; index < pcm.length; index += 1) channel[index] = pcm[index] / 32768;
  const source = outputAudioContext.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(outputAudioContext.destination);
  playbackSources.add(source);
  source.onended = () => playbackSources.delete(source);
  nextPlaybackTime = Math.max(nextPlaybackTime, outputAudioContext.currentTime + 0.03);
  source.start(nextPlaybackTime);
  nextPlaybackTime += audioBuffer.duration;
}

function cancelPlayback() {
  for (const source of playbackSources) {
    try { source.stop(); } catch (_) {}
  }
  playbackSources.clear();
  nextPlaybackTime = outputAudioContext?.currentTime || 0;
}

async function resumeOutputAudio() {
  if (!inputAudioContext && !outputAudioContext) {
    if (assistantInitializationError) {
      voiceError("音频上下文尚未创建，最近一次初始化错误", assistantInitializationError);
    } else {
      voiceLog("音频上下文尚未创建，重新初始化语音助手");
    }
    await initializeAssistant();
    return;
  }
  voiceLog("尝试恢复音频上下文", {
    inputState: inputAudioContext?.state,
    outputState: outputAudioContext?.state,
  });
  if (outputAudioContext?.state === "suspended") await outputAudioContext.resume();
  if (inputAudioContext?.state === "suspended") await inputAudioContext.resume();
  microphoneRunning = inputAudioContext?.state === "running";
  voiceLog("音频上下文恢复结果", {
    inputState: inputAudioContext?.state,
    outputState: outputAudioContext?.state,
  });
  refreshAssistantReadyStatus();
}

function stopAssistant() {
  clearInterval(visionTimer);
  cancelPlayback();
  microphoneStream?.getTracks().forEach(track => track.stop());
  captureNode?.disconnect();
  inputAudioContext?.close();
  outputAudioContext?.close();
  if (assistantSocket?.readyState === WebSocket.OPEN) assistantSocket.close(1000, "page_unload");
  assistantSocket = null;
  assistantReady = false;
  microphoneRunning = false;
  audioInputConfirmed = false;
  assistantInitializing = false;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) binary += String.fromCharCode(bytes[index]);
  return btoa(binary);
}

function base64ToUint8Array(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}
