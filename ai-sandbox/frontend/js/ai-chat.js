/**
 * AI 沙盒 - 内置 AI 聊天组件
 * 封装与后端 AI 代理的交互
 */

class AIChat {
  constructor(containerEl, tracker) {
    this.container = containerEl;
    this.tracker = tracker;
    this.messages = [];
    this.currentStage = 1;
    this.conversationId = null;
    this.isLoading = false;
    this.messageQueue = [];
    this.apiBase = window.location.origin;
    this.token = null;
    this.onStageChange = null; // 回调函数
  }

  setToken(token) {
    this.token = token;
  }

  setStage(stage) {
    this.currentStage = stage;
  }

  /**
   * 发送消息给 AI
   */
  async sendMessage(text) {
    if (!text.trim() || this.isLoading) return;

    // 记录 prompt 发送行为
    this.tracker.trackAIPromptSend(text);

    // 添加用户消息到 UI
    this.appendMessage('user', text);

    // 清空输入框
    const input = this.container.querySelector('.chat-input');
    if (input) input.value = '';

    this.isLoading = true;
    this.updateSendButton();

    try {
      const resp = await fetch(`${this.apiBase}/api/ai/chat/${this.token}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          stage: this.currentStage,
          conversation_id: this.conversationId
        })
      });

      if (!resp.ok) {
        throw new Error(`AI 服务错误: ${resp.status}`);
      }

      const data = await resp.json();
      this.conversationId = data.conversation_id;

      // 记录 AI 响应接收行为
      this.tracker.trackAIResponseRecv(data.response, data.contains_hallucination);

      // 添加 AI 消息到 UI
      this.appendMessage('ai', data.response, {
        containsHallucination: data.contains_hallucination,
        responseTime: data.response_time_ms
      });

    } catch (e) {
      this.appendMessage('system', `AI 服务暂时不可用，请稍后重试。错误: ${e.message}`);
    } finally {
      this.isLoading = false;
      this.updateSendButton();

      // 处理消息队列
      if (this.messageQueue.length > 0) {
        const next = this.messageQueue.shift();
        this.sendMessage(next);
      }
    }
  }

  /**
   * 添加消息到聊天区域
   */
  appendMessage(role, content, options = {}) {
    const messagesEl = this.container.querySelector('.chat-messages');
    if (!messagesEl) return;

    const msgEl = document.createElement('div');
    msgEl.className = `message ${role}`;

    let avatar = '';
    if (role === 'user') avatar = '<div class="message-avatar">U</div>';
    else if (role === 'ai') avatar = '<div class="message-avatar">AI</div>';
    else avatar = '<div class="message-avatar" style="background:var(--danger-dim);color:var(--danger)">!</div>';

    let extra = '';
    if (role === 'ai' && options.containsHallucination) {
      extra = '<div class="hallucination-warning">&#9888; 此响应中可能包含不准确的信息</div>';
    }
    if (role === 'ai' && options.responseTime) {
      extra += `<div style="font-size:11px;color:var(--text-muted);margin-top:4px">响应时间: ${options.responseTime}ms</div>`;
    }

    msgEl.innerHTML = `
      ${avatar}
      <div class="message-content">${this.escapeHtml(content)}${extra}</div>
    `;

    messagesEl.appendChild(msgEl);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    this.messages.push({ role, content, options });
  }

  /**
   * 更新发送按钮状态
   */
  updateSendButton() {
    const btn = this.container.querySelector('.send-btn');
    if (btn) {
      btn.disabled = this.isLoading;
      btn.textContent = this.isLoading ? '思考中...' : '发送';
    }
  }

  /**
   * 队列发送（如果当前正在加载，排队等待）
   */
  queueMessage(text) {
    if (this.isLoading) {
      this.messageQueue.push(text);
    } else {
      this.sendMessage(text);
    }
  }

  /**
   * 清空聊天记录
   */
  clear() {
    this.messages = [];
    this.conversationId = null;
    const messagesEl = this.container.querySelector('.chat-messages');
    if (messagesEl) messagesEl.innerHTML = '';
  }

  /**
   * HTML 转义
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

// 全局单例
window.aiChat = null;
