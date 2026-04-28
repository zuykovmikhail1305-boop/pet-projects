const state = {
  currentChatId: null,
  lastCode: "",
  attachments: [],
  isWaiting: false,
};

const chatList = document.getElementById("chatList");
const conversation = document.getElementById("conversation");
const messagesWrap = document.getElementById("messagesWrap");
const runBtn = document.getElementById("runBtn");
const promptInput = document.getElementById("promptInput");
const healthText = document.getElementById("healthText");
const attachmentStrip = document.getElementById("attachmentStrip");
const fileInput = document.getElementById("fileInput");
const copyLastBtn = document.getElementById("copyLastBtn");
const newChatBtn = document.getElementById("newChatBtn");
const attachBtn = document.getElementById("attachBtn");

const TYPING_SPEED = 22;
const PANEL_REVEAL_DELAY = 320;

async function api(url, options = {}) {
  const config = {
    ...options,
    headers: { ...(options.headers || {}) },
  };

  if (!(config.body instanceof FormData) && !config.headers["Content-Type"]) {
    config.headers["Content-Type"] = "application/json";
  }

  const response = await fetch(url, config);

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || "Request failed");
  }

  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function autosizeTextarea(textarea) {
  const maxHeight = 220;
  textarea.style.height = "auto";
  const next = Math.min(textarea.scrollHeight, maxHeight);
  textarea.style.height = `${next}px`;
  textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
}

function scrollConversationToBottom() {
  requestAnimationFrame(() => {
    messagesWrap.scrollTop = messagesWrap.scrollHeight;
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function renderChats(chats) {
  chatList.innerHTML = "";

  chats.forEach((chat) => {
    const item = document.createElement("button");
    item.className = `chat-item ${chat.id === state.currentChatId ? "active" : ""}`;
    item.innerHTML = `
      <span class="chat-item-title">${escapeHtml(chat.title)}</span>
      <span class="chat-item-arrow">›</span>
    `;
    item.onclick = () => loadChat(chat.id);
    chatList.appendChild(item);
  });
}

function renderAttachments() {
  attachmentStrip.innerHTML = "";
  attachmentStrip.classList.toggle("hidden", state.attachments.length === 0);

  state.attachments.forEach((file, index) => {
    const chip = document.createElement("div");
    chip.className = "attachment-chip";
    chip.innerHTML = `
      <span class="attachment-chip-name">${escapeHtml(file.name)}</span>
      <button class="attach-chip-remove" aria-label="Удалить файл">×</button>
    `;

    chip.querySelector(".attach-chip-remove").onclick = () => {
      state.attachments.splice(index, 1);
      renderAttachments();
    };

    attachmentStrip.appendChild(chip);
  });
}

function createTypingRow() {
  return `
    <div class="message-row assistant temp-typing-row" id="typingRow">
      <div class="bubble assistant typing-bubble">
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
      </div>
    </div>
  `;
}

async function animateTyping(element, fullText, speed = TYPING_SPEED) {
  element.textContent = "";

  for (let i = 0; i < fullText.length; i += 1) {
    element.textContent += fullText[i];
    scrollConversationToBottom();
    await sleep(speed);
  }
}

function buildValidationPanel(validation) {
  return `
    <div class="meta-panel reveal-panel hidden-reveal">
      ${Object.entries(validation)
        .map(
          ([key, value]) => `
        <div class="meta-item">
          <div class="meta-key">${escapeHtml(key)}</div>
          <div class="meta-value">${value.ok ? "OK" : "Ошибка"}</div>
          <div class="meta-desc">${escapeHtml(value.message || "")}</div>
        </div>
      `
        )
        .join("")}
    </div>
  `;
}

function buildIterationsPanel(iterations) {
  return `
    <div class="meta-panel reveal-panel hidden-reveal">
      ${iterations
        .map(
          (step) => `
        <div class="meta-item">
          <div class="meta-key">${escapeHtml(step.phase)}${step.attempt ? ` #${step.attempt}` : ""}</div>
          <div class="meta-desc">${escapeHtml(step.content || "")}</div>
        </div>
      `
        )
        .join("")}
    </div>
  `;
}

function buildCodePanel(code) {
  return `
    <div class="message-row assistant reveal-panel hidden-reveal code-row">
      <div class="assistant-stack">
        <div class="code-wrapper">
          <button class="copy-lua-btn" onclick="copyLuaCode(this)" aria-label="Копировать Lua">
            <img src="/static/copy.svg" alt="copy" />
          </button>
          <pre class="code-panel">${escapeHtml(code)}</pre>
        </div>
      </div>
    </div>
  `;
}

async function revealPanelsSequentially(container) {
  const panels = Array.from(container.querySelectorAll(".hidden-reveal"));
  for (const panel of panels) {
    await sleep(PANEL_REVEAL_DELAY);
    panel.classList.remove("hidden-reveal");
    panel.classList.add("revealed");
    scrollConversationToBottom();
  }
}

async function animateLastAssistantMessage() {
  const target = conversation.querySelector(".typing-target");
  if (!target) return;

  const fullText = target.dataset.fulltext || "";
  await animateTyping(target, fullText, TYPING_SPEED);

  const stack = target.closest(".assistant-stack");
  if (stack) {
    await revealPanelsSequentially(stack);
  }

  const delayedCodeRows = Array.from(conversation.querySelectorAll(".code-row.hidden-reveal"));
  for (const row of delayedCodeRows) {
    await sleep(PANEL_REVEAL_DELAY);
    row.classList.remove("hidden-reveal");
    row.classList.add("revealed");
    scrollConversationToBottom();
  }
}

function renderChat(chat, options = {}) {
  const { animateLastResult = false } = options;
  state.lastCode = "";

  const resultIndexes = [];
  const codeIndexes = [];

  chat.messages.forEach((message, index) => {
    if (message.kind === "result" || message.kind === "clarify") resultIndexes.push(index);
    if (message.kind === "code") codeIndexes.push(index);
  });

  const lastResultIndex = resultIndexes.length ? resultIndexes[resultIndexes.length - 1] : -1;
  const lastCodeIndex = codeIndexes.length ? codeIndexes[codeIndexes.length - 1] : -1;

  const blocks = chat.messages
    .map((message, index) => {
      if (message.kind === "prompt") {
        return `
          <div class="message-row user">
            <div class="bubble user">
              ${escapeHtml(message.content)}
            </div>
          </div>
        `;
      }

      if (message.kind === "clarify") {
        const shouldAnimate = animateLastResult && index === lastResultIndex;
        return `
          <div class="message-row assistant">
            <div class="assistant-stack">
              <div class="bubble assistant result-bubble">
                <div
                  class="agent-text ${shouldAnimate ? "typing-target" : ""}"
                  ${shouldAnimate ? `data-fulltext="${escapeHtml(message.content)}"` : ""}
                >${shouldAnimate ? "" : escapeHtml(message.content)}</div>
              </div>
            </div>
          </div>
        `;
      }

      if (message.kind === "result") {
        const shouldAnimate = animateLastResult && index === lastResultIndex;
        const validation = message.meta?.validation || {};
        const iterations = message.meta?.iterations || [];

        return `
          <div class="message-row assistant">
            <div class="assistant-stack">
              <div class="bubble assistant result-bubble">
                <div
                  class="agent-text ${shouldAnimate ? "typing-target" : ""}"
                  ${shouldAnimate ? `data-fulltext="${escapeHtml(message.content)}"` : ""}
                >${shouldAnimate ? "" : escapeHtml(message.content)}</div>
              </div>

              ${
                Object.keys(validation).length
                  ? shouldAnimate
                    ? buildValidationPanel(validation)
                    : `
                      <div class="meta-panel">
                        ${Object.entries(validation)
                          .map(
                            ([key, value]) => `
                          <div class="meta-item">
                            <div class="meta-key">${escapeHtml(key)}</div>
                            <div class="meta-value">${value.ok ? "OK" : "Ошибка"}</div>
                            <div class="meta-desc">${escapeHtml(value.message || "")}</div>
                          </div>
                        `
                          )
                          .join("")}
                      </div>
                    `
                  : ""
              }

              ${
                Array.isArray(iterations) && iterations.length
                  ? shouldAnimate
                    ? buildIterationsPanel(iterations)
                    : `
                      <div class="meta-panel">
                        ${iterations
                          .map(
                            (step) => `
                          <div class="meta-item">
                            <div class="meta-key">${escapeHtml(step.phase)}${step.attempt ? ` #${step.attempt}` : ""}</div>
                            <div class="meta-desc">${escapeHtml(step.content || "")}</div>
                          </div>
                        `
                          )
                          .join("")}
                      </div>
                    `
                  : ""
              }
            </div>
          </div>
        `;
      }

      if (message.kind === "code") {
        state.lastCode = message.content || "";
        const shouldDelayCode = animateLastResult && index === lastCodeIndex;

        if (shouldDelayCode) {
          return buildCodePanel(message.content);
        }

        return `
          <div class="message-row assistant">
            <div class="assistant-stack">
              <div class="code-wrapper">
                <button class="copy-lua-btn" onclick="copyLuaCode(this)" aria-label="Копировать Lua">
                  <img src="/static/copy.svg" alt="copy" />
                </button>
                <pre class="code-panel">${escapeHtml(message.content)}</pre>
              </div>
            </div>
          </div>
        `;
      }

      if (message.kind === "file") {
        return `
          <div class="message-row assistant">
            <div class="assistant-stack">
              <div class="file-chip-line">
                <div class="file-chip-card">${escapeHtml(message.meta?.name || message.content)}</div>
              </div>
            </div>
          </div>
        `;
      }

      return "";
    })
    .join("");

  conversation.innerHTML = blocks || `<div class="empty-state">Пока пусто.</div>`;
  scrollConversationToBottom();

  if (animateLastResult) {
    animateLastAssistantMessage();
  }
}

window.copyLuaCode = async (btn) => {
  const codeEl = btn.parentElement.querySelector(".code-panel");
  const code = codeEl ? codeEl.innerText : "";

  if (!code.trim()) {
    alert("Lua код пока не найден.");
    return;
  }

  try {
    await navigator.clipboard.writeText(code);
    btn.classList.add("copied");
    setTimeout(() => btn.classList.remove("copied"), 900);
  } catch {
    alert("Ошибка копирования");
  }
};

async function refreshChats() {
  const chats = await api("/api/chats");
  renderChats(chats);
}

async function loadChat(chatId) {
  const chat = await api(`/api/chats/${chatId}`);
  state.currentChatId = chat.id;
  renderChat(chat, { animateLastResult: false });
  await refreshChats();
}

async function createNewChat() {
  try {
    const data = await api("/api/chats", { method: "POST" });
    state.currentChatId = data.chat_id;
    state.attachments = [];
    promptInput.value = "";
    autosizeTextarea(promptInput);
    renderAttachments();
    conversation.innerHTML = `<div class="empty-state">Новый чат.</div>`;
    await refreshChats();
    await loadChat(state.currentChatId);
  } catch (error) {
    alert(`Ошибка создания чата: ${error.message}`);
  }
}

async function checkHealth() {
  try {
    const data = await api("/api/health");
    const ready = Boolean(data.model_ready);
    const model = data.model || "";

    healthText.textContent = ready
      ? `Ollama готова · ${model}`
      : `Ollama загружает модель · ${model}`;

    const statusDot = document.querySelector(".status-dot");
    if (statusDot) {
      statusDot.style.background = ready ? "#34c759" : "#ff9f0a";
    }
  } catch {
    healthText.textContent = "Не удалось проверить Ollama";
  }
}

async function uploadFiles(files) {
  for (const file of files) {
    const formData = new FormData();
    formData.append("file", file);

    const uploaded = await api("/api/files/upload", {
      method: "POST",
      body: formData,
    });

    state.attachments.push(uploaded);
  }

  renderAttachments();
}

function appendOptimisticUserMessage(text) {
  const node = document.createElement("div");
  node.className = "message-row user temp-user-row";
  node.innerHTML = `<div class="bubble user">${escapeHtml(text)}</div>`;
  conversation.appendChild(node);
  scrollConversationToBottom();
}

function appendTypingIndicator() {
  const wrapper = document.createElement("div");
  wrapper.innerHTML = createTypingRow();
  conversation.appendChild(wrapper.firstElementChild);
  scrollConversationToBottom();
}

function removeTypingIndicator() {
  const row = document.getElementById("typingRow");
  if (row) row.remove();
}

async function runPrompt() {
  const prompt = promptInput.value.trim();
  if (!prompt || state.isWaiting) return;

  state.isWaiting = true;
  runBtn.disabled = true;

  appendOptimisticUserMessage(prompt);
  appendTypingIndicator();

  const runBtnText = runBtn.querySelector("span");
  if (runBtnText) runBtnText.textContent = "Запуск...";

  try {
    const data = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({
        prompt,
        chat_id: state.currentChatId,
        attachments: state.attachments,
      }),
    });

    state.currentChatId = data.chat_id;
    promptInput.value = "";
    autosizeTextarea(promptInput);
    state.attachments = [];
    renderAttachments();

    removeTypingIndicator();
    renderChat(data.chat, { animateLastResult: true });
    await refreshChats();
  } catch (error) {
    removeTypingIndicator();
    alert(`Ошибка: ${error.message}`);
  } finally {
    state.isWaiting = false;
    runBtn.disabled = false;
    if (runBtnText) runBtnText.textContent = "Пуск";
  }
}

if (runBtn) {
  runBtn.onclick = runPrompt;
}

if (newChatBtn) {
  newChatBtn.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    await createNewChat();
  });
}

if (attachBtn) {
  attachBtn.onclick = () => fileInput.click();
}

if (copyLastBtn) {
  copyLastBtn.onclick = async () => {
    if (!state.lastCode) {
      alert("Lua код пока не найден.");
      return;
    }
    await navigator.clipboard.writeText(state.lastCode);
  };
}

if (fileInput) {
  fileInput.onchange = async (event) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;

    try {
      await uploadFiles(files);
    } catch (error) {
      alert(`Ошибка загрузки файла: ${error.message}`);
    } finally {
      fileInput.value = "";
    }
  };
}

if (promptInput) {
  promptInput.addEventListener("input", () => autosizeTextarea(promptInput));
  promptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      runPrompt();
    }
  });
}

async function init() {
  await checkHealth();
  await refreshChats();
  autosizeTextarea(promptInput);
  conversation.innerHTML = `<div class="empty-state">Пока пусто.</div>`;
}

init();