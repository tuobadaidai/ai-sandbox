/**
 * AI 沙盒行为洞察系统 - 行为埋点 SDK
 * 记录候选人在沙盒中的所有操作行为
 */

class BehaviorTracker {
  constructor(candidateId, sessionId) {
    this.candidateId = candidateId;
    this.sessionId = sessionId;
    this.currentStage = 1;
    this.startTime = Date.now();
    this.eventBuffer = [];
    this.flushInterval = null;
    this.apiBase = window.location.origin;
    this.token = null;
    this.previousPromptLength = 0;
    this.promptHistory = [];
    this.undoRedoCount = 0;
  }

  setToken(token) {
    this.token = token;
    this.startFlushing();
  }

  /**
   * 生成唯一事件 ID
   */
  generateEventId() {
    return 'evt_' + Date.now().toString(36) + '_' + Math.random().toString(36).substr(2, 6);
  }

  /**
   * 记录一个行为事件（加入缓冲区，定时批量上报）
   */
  track(eventType, metadata = {}) {
    const event = {
      event_id: this.generateEventId(),
      candidate_id: this.candidateId,
      session_id: this.sessionId,
      timestamp: new Date().toISOString(),
      event_type: eventType,
      stage: this.currentStage,
      metadata: metadata
    };
    this.eventBuffer.push(event);

    // 高优先级事件立即上报
    const immediateEvents = ['STAGE_TRANSITION', 'TASK_START', 'TASK_SUBMIT'];
    if (immediateEvents.includes(eventType)) {
      this.flush();
    }
  }

  /**
   * 开始定时批量上报
   */
  startFlushing() {
    this.flushInterval = setInterval(() => this.flush(), 3000);
  }

  /**
   * 停止上报
   */
  stopFlushing() {
    if (this.flushInterval) {
      clearInterval(this.flushInterval);
      this.flushInterval = null;
    }
    this.flush(); // 最后一次上报
  }

  /**
   * 批量上报事件到后端
   */
  async flush() {
    if (this.eventBuffer.length === 0) return;

    const events = [...this.eventBuffer];
    this.eventBuffer = [];

    try {
      const resp = await fetch(`${this.apiBase}/api/events/${this.token}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events })
      });
      if (!resp.ok) {
        // 上报失败，放回缓冲区
        this.eventBuffer = events.concat(this.eventBuffer);
      }
    } catch (e) {
      // 网络错误，放回缓冲区
      this.eventBuffer = events.concat(this.eventBuffer);
    }
  }

  /**
   * 切换阶段
   */
  setStage(newStage) {
    const oldStage = this.currentStage;
    this.currentStage = newStage;
    this.track('STAGE_TRANSITION', {
      from_stage: oldStage,
      to_stage: newStage
    });
  }

  /**
   * 记录 AI prompt 发送
   */
  trackAIPromptSend(prompt) {
    const promptLength = prompt.length;
    // 分析 prompt 是否经过修改（和上一次的长度差异）
    const isModified = this.promptHistory.length > 0;
    const editType = this.classifyPromptEdit(prompt);
    this.promptHistory.push(prompt);

    this.track('AI_PROMPT_SEND', {
      prompt_length: promptLength,
      is_modified: isModified,
      edit_type: editType,
      iteration: this.promptHistory.length,
      has_decomposition: this.detectDecomposition(prompt),
      has_clarification: this.detectClarification(prompt)
    });

    this.previousPromptLength = promptLength;
  }

  /**
   * 记录 AI 响应接收
   */
  trackAIResponseRecv(response, containsHallucination) {
    this.track('AI_RESPONSE_RECV', {
      response_length: response.length,
      contains_hallucination: containsHallucination
    });
  }

  /**
   * 记录文本输入
   */
  trackTextInput(text, source) {
    this.track('TEXT_INPUT', {
      text_length: text.length,
      source: source || 'editor'
    });
  }

  /**
   * 记录复制粘贴
   */
  trackCopyPaste(direction, textLength) {
    this.track('COPY_PASTE', {
      direction: direction, // 'copy' or 'paste'
      text_length: textLength
    });
  }

  /**
   * 记录撤销/重做
   */
  trackUndoRedo(action) {
    this.undoRedoCount++;
    this.track('UNDO_REDO', {
      action: action, // 'undo' or 'redo'
      total_count: this.undoRedoCount
    });
  }

  /**
   * 检测 prompt 是否包含问题拆解关键词
   */
  detectDecomposition(text) {
    const keywords = ['首先', '第一步', '框架', '拆解', '分', '维度', '模块', '结构', '1.', '2.', '3.'];
    return keywords.some(kw => text.includes(kw));
  }

  /**
   * 检测 prompt 是否包含需求澄清
   */
  detectClarification(text) {
    const keywords = ['？', '?', '明确', '定义', '什么意思', '具体指', '范围', '哪些', '多少', '目标用户'];
    return keywords.some(kw => text.includes(kw));
  }

  /**
   * 分类 prompt 编辑类型
   */
  classifyPromptEdit(prompt) {
    if (this.promptHistory.length === 0) return 'initial';

    const prev = this.promptHistory[this.promptHistory.length - 1];
    const lengthDiff = prompt.length - prev.length;

    if (lengthDiff > 50) return 'expanded';
    if (lengthDiff < -50) return 'condensed';
    if (prompt.startsWith(prev.substring(0, 20))) return 'iterative';
    return 'restructured';
  }

  /**
   * 获取当前经过的秒数（相对于开始时间）
   */
  getElapsedSeconds() {
    return Math.floor((Date.now() - this.startTime) / 1000);
  }

  /**
   * 获取格式化的经过时间 MM:SS
   */
  getElapsedTime() {
    const totalSeconds = this.getElapsedSeconds();
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }
}

// 全局单例
window.tracker = null;
