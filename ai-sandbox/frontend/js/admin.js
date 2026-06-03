/**
 * AI 沙盒 - 管理后台
 * 候选人列表、行为日志查看、报告展示
 */

class AdminPanel {
  constructor() {
    this.apiBase = window.location.origin;
    this.sessionId = localStorage.getItem('admin_session_id') || '';
  }

  /**
   * 管理员登录 - 通过 POST 请求，密码在 body 中传递
   */
  async login(secret) {
    try {
      const resp = await fetch(`${this.apiBase}/api/admin/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ secret })
      });
      if (!resp.ok) return false;
      const data = await resp.json();
      this.sessionId = data.session_id;
      localStorage.setItem('admin_session_id', this.sessionId);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * 管理员登出
   */
  async logout() {
    try {
      await fetch(`${this.apiBase}/api/admin/logout`, {
        method: 'POST',
        headers: { 'X-Admin-Session': this.sessionId }
      });
    } catch { /* ignore */ }
    this.sessionId = '';
    localStorage.removeItem('admin_session_id');
  }

  /**
   * 带认证的 fetch 封装
   */
  async authFetch(url, options = {}) {
    const headers = {
      ...(options.headers || {}),
      'X-Admin-Session': this.sessionId
    };
    const resp = await fetch(url, { ...options, headers });
    if (resp.status === 401) {
      // 会话过期，清除本地缓存
      this.sessionId = '';
      localStorage.removeItem('admin_session_id');
      throw new Error('SESSION_EXPIRED');
    }
    return resp;
  }

  /**
   * 获取候选人列表
   */
  async getCandidates() {
    const resp = await this.authFetch(`${this.apiBase}/api/admin/candidates`);
    if (!resp.ok) throw new Error('获取候选人列表失败');
    return await resp.json();
  }

  /**
   * 获取候选人的详细行为数据
   */
  async getCandidateDetail(candidateId) {
    const resp = await this.authFetch(`${this.apiBase}/api/admin/candidates/${candidateId}/events`);
    if (!resp.ok) throw new Error('获取候选人详情失败');
    return await resp.json();
  }

  /**
   * 触发评估
   */
  async evaluateCandidate(candidateId) {
    const resp = await this.authFetch(`${this.apiBase}/api/admin/candidates/${candidateId}/evaluate`, {
      method: 'POST'
    });
    if (!resp.ok) throw new Error('评估失败');
    return await resp.json();
  }

  /**
   * 获取评估报告
   */
  async getReport(candidateId) {
    const resp = await this.authFetch(`${this.apiBase}/api/admin/candidates/${candidateId}/report`);
    if (!resp.ok) throw new Error('获取报告失败');
    return await resp.json();
  }

  /**
   * 渲染候选人列表
   */
  renderCandidateList(candidates, containerEl) {
    if (candidates.length === 0) {
      containerEl.innerHTML = `
        <div style="text-align:center;padding:60px;color:var(--text-muted)">
          <p>暂无候选人数据</p>
          <p style="font-size:12px;margin-top:8px">创建候选人后会在此显示</p>
        </div>
      `;
      return;
    }

    containerEl.innerHTML = `
      <table class="candidate-table">
        <thead>
          <tr>
            <th>姓名</th>
            <th>状态</th>
            <th>级别</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          ${candidates.map(c => `
            <tr>
              <td>${this.escapeHtml(c.name)}</td>
              <td><span class="status-badge status-${c.status}">${this.statusLabel(c.status)}</span></td>
              <td>${c.level ? `<span class="level-badge level-${c.level}">${c.level}</span>` : '<span style="color:var(--text-muted)">-</span>'}</td>
              <td style="font-size:12px;color:var(--text-muted)">${new Date(c.created_at).toLocaleString('zh-CN')}</td>
              <td>
                <div style="display:flex;gap:8px">
                  <button class="btn btn-ghost btn-sm" data-action="viewDetail" data-id="${c.id}">详情</button>
                  ${c.status === 'completed' || c.status === 'testing' ?
                    `<button class="btn btn-primary btn-sm" data-action="triggerEvaluate" data-id="${c.id}" data-name="${this.escapeHtml(c.name)}">评估</button>` : ''}
                  ${c.has_evaluation ?
                    `<button class="btn btn-ghost btn-sm" data-action="viewReport" data-id="${c.id}" style="border-color:var(--accent);color:var(--accent)">报告</button>` : ''}
                </div>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;

    // 事件委托：监听按钮点击
    containerEl.onclick = (e) => {
      const btn = e.target.closest('[data-action]');
      if (!btn) return;
      const action = btn.dataset.action;
      const id = btn.dataset.id;
      if (action === 'viewDetail') {
        if (typeof window.viewDetail === 'function') {
          window.viewDetail(id);
        } else {
          console.error('window.viewDetail is not defined');
        }
      } else if (action === 'triggerEvaluate') {
        if (typeof window.triggerEvaluate === 'function') {
          window.triggerEvaluate(id, btn.dataset.name || '');
        } else {
          console.error('window.triggerEvaluate is not defined');
        }
      } else if (action === 'viewReport') {
        if (typeof window.viewReport === 'function') {
          window.viewReport(id);
        } else {
          console.error('window.viewReport is not defined');
        }
      }
    };
  }

  /**
   * 渲染评估报告
   */
  renderReport(data, containerEl) {
    const { candidate, evaluation } = data;
    const scores = evaluation.dimension_scores;
    const contradictions = evaluation.contradictions;
    const profile = evaluation.cognitive_profile;

    const dimensionLabels = {
      ai_fluency: 'AI流利度',
      human_ai_judgment: '人机判断力',
      architecture_design: '架构设计力',
      hybrid_orchestration: '混合编排力',
      cognitive_depth: '认知深度',
      problem_modeling: '问题建模能力'
    };

    const dimensionColors = {
      ai_fluency: '#0ea5e9',
      human_ai_judgment: '#10b981',
      architecture_design: '#f59e0b',
      hybrid_orchestration: '#a855f7',
      cognitive_depth: '#ec4899',
      problem_modeling: '#06b6d4'
    };

    // 新六维度标签
    const newDimensionLabels = {
      problem_definition: '问题定义能力',
      task_decomposition: '任务拆解能力',
      information_acquisition: '信息获取能力',
      hypothesis_construction: '假设构建能力',
      hypothesis_correction: '假设修正能力',
      integrated_judgment: '综合判断力'
    };

    const newDimensionColors = {
      problem_definition: '#06b6d4',
      task_decomposition: '#a855f7',
      information_acquisition: '#10b981',
      hypothesis_construction: '#f59e0b',
      hypothesis_correction: '#ec4899',
      integrated_judgment: '#0ea5e9'
    };

    containerEl.innerHTML = `
      <div class="report-body">
        <!-- 综合结果 -->
        <div class="comprehensive-result">
          <div class="level">${evaluation.level}</div>
          <div class="score">综合得分 ${evaluation.comprehensive_score}/16 &nbsp;|&nbsp; 平均分 ${evaluation.average_score}/4</div>
          <div style="margin-top:12px;font-size:13px;color:var(--text-muted)">置信度: ${evaluation.confidence}</div>
          ${evaluation.collaboration_style ? `<div style="margin-top:8px;font-size:13px;color:var(--text-accent)">协作风格: ${evaluation.collaboration_style}</div>` : ''}
          ${evaluation.cmmi_maturity_level ? `<div style="margin-top:4px;font-size:13px;color:var(--text-accent)">CMMI成熟度: ${evaluation.cmmi_maturity_level}</div>` : ''}
        </div>

        <!-- 新六维度评分（高管测评） -->
        ${evaluation.new_dimension_scores ? `
        <div class="report-section" style="margin-top:32px">
          <h2>新六维度能力评分（0-100分）</h2>
          <div class="score-grid">
            ${Object.entries(newDimensionLabels).map(([key, label]) => {
              const value = evaluation.new_dimension_scores[key] || 0;
              const pct = value;
              const color = newDimensionColors[key];
              return `
                <div class="score-card">
                  <div class="label">${label}</div>
                  <div class="value" style="color:${color}">${value.toFixed(0)}</div>
                  <div class="bar">
                    <div class="bar-fill" style="width:${pct}%;background:${color}"></div>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
        ` : ''}

        <!-- 旧六维度评分 -->
        <div class="report-section" style="margin-top:32px">
          <h2>六维度能力评分（1-4分）</h2>
          <div class="score-grid">
            ${Object.entries(dimensionLabels).map(([key, label]) => {
              const value = scores[key] || 0;
              const pct = (value / 4) * 100;
              const color = dimensionColors[key];
              return `
                <div class="score-card">
                  <div class="label">${label}</div>
                  <div class="value" style="color:${color}">${value.toFixed(1)}</div>
                  <div class="bar">
                    <div class="bar-fill" style="width:${pct}%;background:${color}"></div>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>

        <!-- 矛盾检测 -->
        ${contradictions && contradictions.length > 0 ? `
          <div class="report-section">
            <h2>矛盾信号 (${contradictions.length})</h2>
            ${contradictions.map(c => `
              <div class="contradiction-item">
                <div class="type">${this.escapeHtml(c.type)}</div>
                <div class="desc">${this.escapeHtml(c.description)}</div>
                <div class="conf">置信度: ${c.confidence} ${c.evidence ? '| ' + this.escapeHtml(c.evidence) : ''}</div>
              </div>
            `).join('')}
          </div>
        ` : ''}

        <!-- 认知画像 -->
        <div class="report-section">
          <h2>认知画像</h2>
          <div class="profile-grid">
            ${Object.entries({
              decision_style: '决策风格',
              thinking_structure: '思维结构',
              ai_collaboration_habit: 'AI协同习惯',
              complexity_capacity: '复杂度承载',
              ownership: '责任感',
              risk_preference: '风险偏好',
              correction_ability: '修正能力',
              authenticity_risk: '真实性风险'
            }).map(([key, label]) => `
              <div class="profile-item">
                <div class="label">${label}</div>
                <div class="value">${profile[key] ? this.escapeHtml(profile[key]) : '<span style="color:var(--text-muted)">未观察到</span>'}</div>
              </div>
            `).join('')}
          </div>
        </div>

        <!-- 行为叙事 -->
        <div class="report-section">
          <h2>行为叙事记录</h2>
          <div class="narrative-text">${this.escapeHtml(evaluation.narrative_text)}</div>
        </div>
      </div>
    `;
  }

  /**
   * 渲染行为详情
   */
  renderEventDetail(data, containerEl) {
    const { candidate, events, ai_interactions } = data;

    // 按时间合并事件和AI交互
    const timeline = [];
    events.forEach(e => {
      timeline.push({ time: e.timestamp, type: 'event', data: e });
    });
    ai_interactions.forEach(a => {
      timeline.push({ time: a.created_at, type: 'ai', data: a });
    });
    timeline.sort((a, b) => new Date(a.time) - new Date(b.time));

    containerEl.innerHTML = `
      <div style="max-width:900px;margin:0 auto">
        <h2 style="margin-bottom:16px">行为日志 - ${this.escapeHtml(candidate.name)}</h2>
        <div style="font-size:13px;color:var(--text-muted);margin-bottom:20px">
          共 ${events.length} 个行为事件，${ai_interactions.length} 次 AI 交互
        </div>
        ${timeline.map(item => {
          if (item.type === 'ai') {
            const a = item.data;
            return `
              <div style="padding:12px 16px;background:var(--bg-card);border-radius:var(--radius-sm);margin-bottom:6px;border-left:3px solid var(--success)">
                <div style="font-size:11px;color:var(--text-muted)">Stage ${a.stage} | AI交互 | ${new Date(a.time).toLocaleTimeString('zh-CN')}</div>
                <div style="margin-top:6px;font-size:13px"><strong>Prompt:</strong> ${this.escapeHtml(a.prompt.substring(0, 200))}${a.prompt.length > 200 ? '...' : ''}</div>
                <div style="margin-top:4px;font-size:13px;color:var(--text-secondary)"><strong>Response:</strong> ${a.response_length}字 | ${a.response_time_ms}ms ${a.contains_hallucination ? '| ⚠️ 含幻觉数据' : ''}</div>
              </div>
            `;
          } else {
            const e = item.data;
            const meta = typeof e.metadata === 'string' ? JSON.parse(e.metadata) : e.metadata;
            return `
              <div style="padding:8px 16px;background:var(--bg-secondary);border-radius:var(--radius-sm);margin-bottom:4px;font-size:12px">
                <span style="color:var(--text-muted)">Stage ${e.stage}</span> |
                <span style="color:var(--accent)">${e.event_type}</span> |
                <span style="color:var(--text-muted)">${new Date(e.timestamp).toLocaleTimeString('zh-CN')}</span>
                ${Object.keys(meta).length > 0 ? `<span style="color:var(--text-muted);margin-left:8px">${JSON.stringify(meta)}</span>` : ''}
              </div>
            `;
          }
        }).join('')}
      </div>
    `;
  }

  statusLabel(status) {
    const labels = { pending: '待开始', testing: '进行中', completed: '已完成', evaluated: '已评估' };
    return labels[status] || status;
  }

  escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

// 全局单例
window.admin = new AdminPanel();
