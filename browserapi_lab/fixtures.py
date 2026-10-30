"""Local test fixtures for browserapi-lab."""
from pathlib import Path


FAKE_CHAT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fake Chat - browserapi-lab fixture</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: system-ui, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
        .chat-container { background: white; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); overflow: hidden; }
        .messages { height: 400px; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 16px; }
        .message { max-width: 85%; padding: 12px 16px; border-radius: 12px; line-height: 1.5; animation: fadeIn 0.2s ease; }
        .message.user { align-self: flex-end; background: #0066cc; color: white; border-bottom-right-radius: 4px; }
        .message.assistant { align-self: flex-start; background: #f0f0f0; color: #333; border-bottom-left-radius: 4px; }
        .message .content { white-space: pre-wrap; word-wrap: break-word; }
        .message code { background: rgba(0,0,0,0.1); padding: 2px 6px; border-radius: 4px; font-family: monospace; }
        .message pre { background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 6px; overflow-x: auto; margin: 8px 0; }
        .message pre code { background: none; padding: 0; color: inherit; }
        .message ul, .message ol { margin: 8px 0; padding-left: 24px; }
        .message table { border-collapse: collapse; margin: 8px 0; font-size: 0.9em; }
        .message th, .message td { border: 1px solid #ddd; padding: 6px 12px; }
        .message th { background: #f5f5f5; }
        .message a { color: #0066cc; text-decoration: none; }
        .message a:hover { text-decoration: underline; }
        .message blockquote { border-left: 3px solid #0066cc; margin: 8px 0; padding-left: 12px; color: #666; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
        .input-area { padding: 16px; border-top: 1px solid #eee; display: flex; gap: 8px; }
        .input-wrapper { flex: 1; position: relative; }
        textarea, input, [contenteditable] { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-family: inherit; font-size: 14px; resize: vertical; min-height: 44px; max-height: 200px; }
        textarea:focus, input:focus, [contenteditable]:focus { outline: none; border-color: #0066cc; box-shadow: 0 0 0 3px rgba(0,102,204,0.1); }
        button.send-btn { padding: 12px 24px; background: #0066cc; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 500; height: 44px; }
        button.send-btn:hover { background: #0052a3; }
        button.send-btn:disabled { background: #ccc; cursor: not-allowed; }
        .controls { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
        .controls label { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #666; cursor: pointer; }
        .status { padding: 8px 12px; background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px; font-size: 13px; display: none; }
        .status.visible { display: block; }
        .indicators { display: flex; gap: 12px; padding: 8px 16px; font-size: 12px; color: #666; border-top: 1px solid #eee; }
        .indicator { display: flex; align-items: center; gap: 4px; }
        .indicator .dot { width: 8px; height: 8px; border-radius: 50%; background: #ccc; }
        .indicator .dot.active { background: #28a745; }
        .indicator .dot.busy { background: #dc3545; animation: pulse 1s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        .streaming { position: relative; }
        .streaming::after { content: ''; display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #0066cc; animation: blink 1s infinite; margin-left: 4px; vertical-align: middle; }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
    </style>
</head>
<body>
    <h1>Fake Chat Fixture</h1>
    <p>Deterministic test page for browserapi-lab. No external dependencies.</p>

    <div class="chat-container" role="application" aria-label="Chat">
        <div class="messages" id="messages" role="log" aria-live="polite" aria-atomic="false">
            <div class="message user" data-testid="user-message">
                <div class="content">Hello, this is a test message from the user.</div>
            </div>
            <div class="message assistant" data-testid="assistant-message">
                <div class="content">Hello! This is a test response from the assistant. It includes <strong>bold</strong>, <em>italic</em>, and <code>inline code</code>.</div>
            </div>
        </div>

        <div class="indicators" role="status" aria-live="polite">
            <div class="indicator" id="busy-indicator" data-testid="busy-indicator" aria-busy="false">
                <span class="dot" id="busy-dot"></span>
                <span>Busy: <span id="busy-status">idle</span></span>
            </div>
            <div class="indicator" id="stop-indicator" data-testid="stop-indicator">
                <span class="dot" id="stop-dot"></span>
                <span>Stop: <span id="stop-status">hidden</span></span>
            </div>
            <div class="indicator" id="copy-indicator" data-testid="copy-indicator">
                <span class="dot" id="copy-dot"></span>
                <span>Copy: <span id="copy-status">hidden</span></span>
            </div>
        </div>

        <div class="input-area">
            <div class="input-wrapper">
                <textarea
                    id="prompt-textarea"
                    placeholder="Type your message here (textarea)..."
                    aria-label="Message input (textarea)"
                    data-testid="prompt-textarea"
                ></textarea>
                <input
                    type="text"
                    id="prompt-input"
                    placeholder="Or type here (input)..."
                    aria-label="Message input (input)"
                    data-testid="prompt-input"
                    style="display: none;"
                >
                <div
                    id="prompt-contenteditable"
                    contenteditable="true"
                    role="textbox"
                    aria-label="Message input (contenteditable)"
                    data-testid="prompt-contenteditable"
                    style="display: none; min-height: 44px; padding: 12px;"
                ></div>
            </div>
            <button class="send-btn" id="send-btn" data-testid="send-button" aria-label="Send message">Send</button>
            <button class="stop-btn" id="stop-btn" data-testid="stop-button" aria-label="Stop generation" style="display: none;">Stop</button>
            <button class="copy-btn" id="copy-btn" data-testid="copy-button" aria-label="Copy response" style="display: none;">Copy</button>
        </div>

        <div class="controls">
            <label><input type="radio" name="input-type" value="textarea" checked onchange="switchInput('textarea')"> Textarea</label>
            <label><input type="radio" name="input-type" value="input" onchange="switchInput('input')"> Input</label>
            <label><input type="radio" name="input-type" value="contenteditable" onchange="switchInput('contenteditable')"> ContentEditable</label>
        </div>
        <div class="controls">
            <label><input type="checkbox" id="toggle-streaming" onchange="toggleStreaming(this.checked)" checked> Streaming (char-by-char)</label>
            <label><input type="checkbox" id="toggle-long-pause" onchange="toggleLongPause(this.checked)"> Long pause in middle (3s)</label>
            <label><input type="checkbox" id="toggle-error" onchange="toggleError(this.checked)"> Simulate error</label>
            <label><input type="checkbox" id="toggle-rate-limit" onchange="toggleRateLimit(this.checked)"> Simulate rate limit</label>
            <label><input type="checkbox" id="toggle-login" onchange="toggleLogin(this.checked)"> Require login</label>
            <label><input type="checkbox" id="toggle-test-mode" onchange="setTestMode(this.checked)"> Test mode (instant)</label>
        </div>
        <div class="status" id="status-bar"></div>
    </div>

    <script>
        // State
        let streaming = true;
        let longPause = false;
        let simulateError = false;
        let simulateRateLimit = false;
        let requireLogin = false;
        let currentInputType = 'textarea';
        let isGenerating = false;
        let abortController = null;
        
        // Test mode: instant responses, no streaming delays
        let testMode = false;
        
        function setTestMode(enabled) {
            testMode = enabled;
            streaming = !enabled;
            longPause = false;
            simulateError = false;
            simulateRateLimit = false;
            requireLogin = false;
            document.getElementById('toggle-streaming').checked = !enabled;
            document.getElementById('toggle-long-pause').checked = false;
            document.getElementById('toggle-error').checked = false;
            document.getElementById('toggle-rate-limit').checked = false;
            document.getElementById('toggle-login').checked = false;
        }

        const messagesEl = document.getElementById('messages');
        const sendBtn = document.getElementById('send-btn');
        const statusBar = document.getElementById('status-bar');
        const busyDot = document.getElementById('busy-dot');
        const busyStatus = document.getElementById('busy-status');
        const stopDot = document.getElementById('stop-dot');
        const stopStatus = document.getElementById('stop-status');
        const copyDot = document.getElementById('copy-dot');
        const copyStatus = document.getElementById('copy-status');

        function getActiveInput() {
            switch (currentInputType) {
                case 'textarea': return document.getElementById('prompt-textarea');
                case 'input': return document.getElementById('prompt-input');
                case 'contenteditable': return document.getElementById('prompt-contenteditable');
            }
        }

        function switchInput(type) {
            currentInputType = type;
            document.getElementById('prompt-textarea').style.display = type === 'textarea' ? 'block' : 'none';
            document.getElementById('prompt-input').style.display = type === 'input' ? 'block' : 'none';
            document.getElementById('prompt-contenteditable').style.display = type === 'contenteditable' ? 'block' : 'none';
            getActiveInput().focus();
        }

        function toggleStreaming(v) { streaming = v; }
        function toggleLongPause(v) { longPause = v; }
        function toggleError(v) { simulateError = v; }
        function toggleRateLimit(v) { simulateRateLimit = v; }
        function toggleLogin(v) { requireLogin = v; }

        function showStatus(msg, isError = false) {
            statusBar.textContent = msg;
            statusBar.className = 'status visible' + (isError ? ' error' : '');
            statusBar.style.background = isError ? '#f8d7da' : '#fff3cd';
            statusBar.style.borderColor = isError ? '#f5c6cb' : '#ffc107';
        }

        function setBusy(busy) {
            document.getElementById('busy-indicator').setAttribute('aria-busy', busy);
            busyDot.classList.toggle('active', busy);
            busyDot.classList.toggle('busy', busy);
            busyStatus.textContent = busy ? 'generating' : 'idle';
        }

        function setStop(visible) {
            stopDot.classList.toggle('active', visible);
            stopStatus.textContent = visible ? 'visible' : 'hidden';
            const stopBtn = document.getElementById('stop-btn');
            if (stopBtn) stopBtn.style.display = visible ? 'inline-flex' : 'none';
            const sendBtn = document.getElementById('send-btn');
            if (sendBtn) sendBtn.style.display = visible ? 'none' : 'inline-flex';
        }

        function setCopy(visible) {
            copyDot.classList.toggle('active', visible);
            copyStatus.textContent = visible ? 'visible' : 'hidden';
            const copyBtn = document.getElementById('copy-btn');
            if (copyBtn) copyBtn.style.display = visible ? 'inline-flex' : 'none';
        }

        function addMessage(role, content) {
            const div = document.createElement('div');
            div.className = `message ${role}`;
            div.setAttribute('data-testid', `${role}-message`);
            div.innerHTML = `<div class="content">${content}</div>`;
            messagesEl.appendChild(div);
            messagesEl.scrollTop = messagesEl.scrollHeight;
            return div.querySelector('.content');
        }

        async function streamResponse(text, contentEl) {
            isGenerating = true;
            setBusy(true);
            setStop(true);
            setCopy(false);
            contentEl.classList.add('streaming');

            abortController = new AbortController();

            try {
                if (requireLogin) {
                    throw new Error("Login required");
                }
                if (simulateRateLimit) {
                    throw new Error("Rate limit exceeded. Please wait.");
                }

                if (testMode) {
                    // Simulated streaming in test mode (fast but observable)
                    const chunks = text.split('');
                    let accumulated = '';
                    for (let i = 0; i < chunks.length; i++) {
                        if (abortController.signal.aborted) break;
                        accumulated += chunks[i];
                        contentEl.textContent = accumulated;
                        messagesEl.scrollTop = messagesEl.scrollHeight;
                        await new Promise(r => setTimeout(r, 1)); // Fast streaming
                    }
                } else {
                    const chunks = text.split('');
                    let accumulated = '';
                    let pauseDone = false;

                    for (let i = 0; i < chunks.length; i++) {
                        if (abortController.signal.aborted) break;

                        accumulated += chunks[i];
                        contentEl.textContent = accumulated;
                        messagesEl.scrollTop = messagesEl.scrollHeight;

                        // Long pause in the middle
                        if (longPause && !pauseDone && i === Math.floor(chunks.length / 2)) {
                            pauseDone = true;
                            await new Promise(r => setTimeout(r, 3000));
                        }

                        // Streaming delay
                        if (streaming) {
                            await new Promise(r => setTimeout(r, 30 + Math.random() * 20));
                        }
                    }
                }

                if (simulateError && !abortController.signal.aborted) {
                    throw new Error("Simulated error during generation");
                }

            } catch (e) {
                contentEl.textContent = `Error: ${e.message}`;
                contentEl.style.color = '#dc3545';
                showStatus(e.message, true);
            } finally {
                isGenerating = false;
                contentEl.classList.remove('streaming');
                setBusy(false);
                setStop(false);
                setCopy(true);
                sendBtn.disabled = false;
                getActiveInput().disabled = false;
            }
        }

        function stopGeneration() {
            if (abortController) {
                abortController.abort();
            }
        }

        async function handleSend() {
            if (isGenerating) {
                stopGeneration();
                return;
            }

            const input = getActiveInput();
            const text = currentInputType === 'contenteditable'
                ? input.innerText.trim()
                : input.value.trim();

            if (!text) return;

            addMessage('user', text);
            input.value = '';
            if (currentInputType === 'contenteditable') input.innerText = '';

            sendBtn.disabled = true;
            input.disabled = true;

            const contentEl = addMessage('assistant', '');

            // Simulated response with markdown-like content
            const response = `Here's a comprehensive response with various elements:

**Bold text** and *italic text* and \`inline code\`.

\`\`\`python
def hello_world():
    print("Hello, World!")
    return 42
\`\`\`

A list of items:
- First item
- Second item with **bold**
- Third item with \`code\`

A numbered list:
1. Step one
2. Step two
3. Step three

A simple table:

| Name | Value | Description |
|------|-------|-------------|
| Alpha | 1 | First item |
| Beta | 2 | Second item |
| Gamma | 3 | Third item |

A [link to example.com](https://example.com).

> A blockquote with some quoted text.

Final paragraph.`;

            await streamResponse(response, contentEl);
        }

        // Event listeners
        sendBtn.addEventListener('click', handleSend);

        document.querySelectorAll('textarea, input, [contenteditable]').forEach(el => {
            el.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    if (currentInputType === 'contenteditable') {
                        e.preventDefault();
                        handleSend();
                    } else if (el.tagName !== 'TEXTAREA') {
                        e.preventDefault();
                        handleSend();
                    }
                }
            });
        });

        // Initialize
        document.getElementById('prompt-textarea').focus();
    </script>
</body>
</html>
"""


def create_fake_chat(output_path: str) -> None:
    """Create the fake chat HTML fixture."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FAKE_CHAT_HTML)
    print(f"Created fixture: {path}")