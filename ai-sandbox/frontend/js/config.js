/**
 * AI 沙盒 - 系统配置面板
 * AI连接 / 题本管理 / 评估维度 配置器
 */

class ConfigPanel {
  constructor() {
    this.apiBase = window.location.origin;
    this.activeTab = 'ai';
    this.aiConfig = null;
    this.evaluationConfig = null;
    this.tasks = null;
  }

  /**
   * 带认证的 fetch
   */
  async authFetch(url, options = {}) {
    const sessionId = localStorage.getItem('admin_session_id') || '';
    const headers = {
      ...(options.headers || {}),
      'Content-Type': 'application/json',
      'X-Admin-Session': sessionId
    };
    const resp = await fetch(url, { ...options, headers });
    if (resp.status === 401) {
      throw new Error('SESSION_EXPIRED');
    }
    return resp;
  }

  /**
   * 渲染配置面板到容器
   */
  async render(containerEl) {
    this.container = containerEl;
    containerEl.innerHTML = `
      <div class="config-panel">
        <div class="config-tabs">
          <button class="config-tab active" data-tab="ai">🤖 AI 连接</button>
          <button class="config-tab" data-tab="tasks">📋 题本管理</button>
          <button class="config-tab" data-tab="evaluation">📊 评估维度</button>
          <button class="config-tab" data-tab="changelog">📜 变更历史</button>
        </div>
        <div class="config-body" id="config-body">
          <div style="text-align:center;padding:40px;color:var(--text-muted)">加载中...</div>
        </div>
      </div>
    `;

    // Tab 切换
    containerEl.querySelectorAll('.config-tab').forEach(btn => {
      btn.onclick = () => {
        containerEl.querySelectorAll('.config-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.activeTab = btn.dataset.tab;
        this.loadTab();
      };
    });

    await this.loadTab();
  }

  async loadTab() {
    const body = document.getElementById('config-body');
    if (!body) return;

    try {
      switch (this.activeTab) {
        case 'ai': await this.renderAITab(body); break;
        case 'tasks': await this.renderTasksTab(body); break;
        case 'evaluation': await this.renderEvaluationTab(body); break;
        case 'changelog': await this.renderChangelogTab(body); break;
      }
    } catch (e) {
      body.innerHTML = `<div style="padding:40px;color:#e74c3c">加载失败: ${this.escapeHtml(e.message)}</div>`;
    }
  }

  // ========== AI 连接 ==========

  async renderAITab(body) {
    const resp = await this.authFetch(`${this.apiBase}/api/admin/config/ai`);
    if (!resp.ok) throw new Error('获取AI配置失败');
    this.aiConfig = await resp.json();

    const c = this.aiConfig;
    const provider = c.provider || 'auto';

    body.innerHTML = `
      <div class="config-section">
        <h3>AI 服务配置</h3>

        <div class="config-field">
          <label>当前后端</label>
          <div class="radio-group">
            <label class="radio-label"><input type="radio" name="ai-provider" value="auto" ${provider === 'auto' || !provider ? 'checked' : ''}> 自动检测</label>
            <label class="radio-label"><input type="radio" name="ai-provider" value="dashscope" ${provider === 'dashscope' ? 'checked' : ''}> DashScope (通义千问)</label>
            <label class="radio-label"><input type="radio" name="ai-provider" value="ollama" ${provider === 'ollama' ? 'checked' : ''}> Ollama (本地)</label>
            <label class="radio-label"><input type="radio" name="ai-provider" value="mock" ${provider === 'mock' ? 'checked' : ''}> Mock (测试)</label>
          </div>
        </div>

        <div class="config-subsection" id="cfg-dashscope">
          <h4>DashScope 配置</h4>
          <div class="config-field">
            <label>API Key</label>
            <div style="display:flex;gap:8px">
              <input type="password" class="form-input config-input" id="cfg-ds-apikey" value="${this.escapeHtml(c.dashscope?.api_key || '')}" placeholder="sk-xxx">
              <button class="btn btn-ghost btn-sm" onclick="document.getElementById('cfg-ds-apikey').type=document.getElementById('cfg-ds-apikey').type==='password'?'text':'password'">👁️</button>
            </div>
          </div>
          <div class="config-field">
            <label>Model</label>
            <input type="text" class="form-input config-input" id="cfg-ds-model" value="${this.escapeHtml(c.dashscope?.model || 'qwen-plus')}" placeholder="qwen-plus">
          </div>
          <div class="config-field">
            <label>Base URL</label>
            <input type="text" class="form-input config-input" id="cfg-ds-baseurl" value="${this.escapeHtml(c.dashscope?.base_url || '')}" placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1">
          </div>
        </div>

        <div class="config-subsection" id="cfg-ollama">
          <h4>Ollama 配置</h4>
          <div class="config-field">
            <label>Model</label>
            <input type="text" class="form-input config-input" id="cfg-ol-model" value="${this.escapeHtml(c.ollama?.model || 'qwen2:1.5b')}" placeholder="qwen2:1.5b">
          </div>
          <div class="config-field">
            <label>Base URL</label>
            <input type="text" class="form-input config-input" id="cfg-ol-baseurl" value="${this.escapeHtml(c.ollama?.base_url || '')}" placeholder="http://localhost:11434/v1">
          </div>
        </div>

        <div class="config-subsection">
          <h4>高级参数</h4>
          <div class="config-field">
            <label>Temperature <span id="cfg-temp-val">${c.params?.temperature ?? 0.7}</span></label>
            <input type="range" min="0" max="1" step="0.1" value="${c.params?.temperature ?? 0.7}" class="config-slider" id="cfg-temperature" oninput="document.getElementById('cfg-temp-val').textContent=this.value">
          </div>
          <div class="config-field">
            <label>Max Tokens</label>
            <input type="number" class="form-input config-input" id="cfg-max-tokens" value="${c.params?.max_tokens ?? 2048}" min="100" max="8192">
          </div>
          <div class="config-field">
            <label>Timeout (秒)</label>
            <input type="number" class="form-input config-input" id="cfg-timeout" value="${c.params?.timeout ?? 60}" min="5" max="300">
          </div>
          <div class="config-field">
            <label>幻觉注入率 <span id="cfg-hall-val">${c.hallucination_rate ?? 0.15}</span></label>
            <input type="range" min="0" max="0.3" step="0.01" value="${c.hallucination_rate ?? 0.15}" class="config-slider" id="cfg-hallucination" oninput="document.getElementById('cfg-hall-val').textContent=this.value">
          </div>
        </div>

        <div class="config-actions">
          <button class="btn btn-ghost" onclick="window.configPanel.testAIConnection()">🔗 测试连接</button>
          <button class="btn btn-primary" onclick="window.configPanel.saveAIConfig()">💾 保存配置</button>
        </div>

        <div id="ai-test-result" style="margin-top:16px"></div>
      </div>
    `;
  }

  async saveAIConfig() {
    const providerRadio = document.querySelector('input[name="ai-provider"]:checked');
    const provider = providerRadio ? providerRadio.value : null;

    const updates = {
      provider: provider === 'auto' ? null : provider,
      dashscope: {
        api_key: document.getElementById('cfg-ds-apikey')?.value || '',
        model: document.getElementById('cfg-ds-model')?.value || 'qwen-plus',
        base_url: document.getElementById('cfg-ds-baseurl')?.value || 'https://dashscope.aliyuncs.com/compatible-mode/v1'
      },
      ollama: {
        api_key: 'ollama',
        model: document.getElementById('cfg-ol-model')?.value || 'qwen2:1.5b',
        base_url: document.getElementById('cfg-ol-baseurl')?.value || 'http://localhost:11434/v1'
      },
      params: {
        temperature: parseFloat(document.getElementById('cfg-temperature')?.value || 0.7),
        max_tokens: parseInt(document.getElementById('cfg-max-tokens')?.value || 2048),
        timeout: parseInt(document.getElementById('cfg-timeout')?.value || 60)
      },
      hallucination_rate: parseFloat(document.getElementById('cfg-hallucination')?.value || 0.15)
    };

    try {
      const resp = await this.authFetch(`${this.apiBase}/api/admin/config/ai`, {
        method: 'PUT',
        body: JSON.stringify(updates)
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || '保存失败');
      }
      this.showToast('✅ AI 配置已保存并生效');
    } catch (e) {
      this.showToast('❌ 保存失败: ' + e.message);
    }
  }

  async testAIConnection() {
    const resultDiv = document.getElementById('ai-test-result');
    if (resultDiv) resultDiv.innerHTML = '<div style="padding:12px;color:var(--text-accent)">⏳ 正在测试连接...</div>';

    try {
      const resp = await this.authFetch(`${this.apiBase}/api/admin/config/ai/test`, { method: 'POST' });
      const result = await resp.json();
      if (result.success) {
        if (resultDiv) resultDiv.innerHTML = `
          <div style="padding:12px;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.3);border-radius:8px">
            ✅ 连接成功！<br>
            <span style="font-size:12px;color:var(--text-secondary)">Provider: ${this.escapeHtml(result.provider)} | 响应: ${result.response_time_ms}ms</span><br>
            <span style="font-size:12px;color:var(--text-secondary)">回复: ${this.escapeHtml(result.test_response?.substring(0, 100) || '')}</span>
          </div>
        `;
      } else {
        if (resultDiv) resultDiv.innerHTML = `
          <div style="padding:12px;background:rgba(231,76,60,0.1);border:1px solid rgba(231,76,60,0.3);border-radius:8px">
            ❌ 连接失败: ${this.escapeHtml(result.error || '未知错误')}
          </div>
        `;
      }
    } catch (e) {
      if (resultDiv) resultDiv.innerHTML = `<div style="padding:12px;color:#e74c3c">❌ 测试失败: ${this.escapeHtml(e.message)}</div>`;
    }
  }

  // ========== 题本管理 ==========

  async renderTasksTab(body) {
    const resp = await this.authFetch(`${this.apiBase}/api/admin/config/tasks`);
    if (!resp.ok) throw new Error('获取题本列表失败');
    const data = await resp.json();
    this.tasks = data.tasks;
    const activeTask = data.active_task;

    body.innerHTML = `
      <div class="config-section">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
          <h3>题本管理</h3>
          <button class="btn btn-primary btn-sm" onclick="window.configPanel.showNewTaskForm()">+ 新建题本</button>
        </div>
        <div id="task-list">
          ${this.tasks.map(t => `
            <div class="task-card ${t.is_active ? 'task-active' : ''}">
              <div style="display:flex;align-items:center;gap:12px">
                <span style="font-size:20px">${t.is_active ? '🟢' : '📄'}</span>
                <div style="flex:1">
                  <div style="font-weight:600">${this.escapeHtml(t.name || t.filename)}</div>
                  <div style="font-size:12px;color:var(--text-muted)">
                    ${t.description ? this.escapeHtml(t.description) + ' | ' : ''}
                    ${t.duration_minutes ? t.duration_minutes + '分钟 | ' : ''}
                    ${t.stages_count ? t.stages_count + '阶段' : ''}
                    ${t.is_active ? '<span style="color:var(--success)">● 活跃</span>' : ''}
                  </div>
                  <div style="font-size:11px;color:var(--text-muted);margin-top:2px">${this.escapeHtml(t.filename)}</div>
                </div>
                <div style="display:flex;gap:6px">
                  ${!t.is_active ? `<button class="btn btn-ghost btn-sm" onclick="window.configPanel.activateTask('${this.escapeHtml(t.filename)}')">激活</button>` : ''}
                  <button class="btn btn-ghost btn-sm" onclick="window.configPanel.editTask('${this.escapeHtml(t.filename)}')">编辑</button>
                  <button class="btn btn-ghost btn-sm" onclick="window.configPanel.copyTask('${this.escapeHtml(t.filename)}')">复制</button>
                  ${!t.is_active ? `<button class="btn btn-ghost btn-sm" style="color:var(--danger)" onclick="window.configPanel.deleteTask('${this.escapeHtml(t.filename)}')">删除</button>` : ''}
                </div>
              </div>
            </div>
          `).join('')}
        </div>
        <div id="task-editor" style="display:none;margin-top:20px;position:relative;z-index:10"></div>
      </div>
    `;
  }

  async activateTask(filename) {
    try {
      const resp = await this.authFetch(`${this.apiBase}/api/admin/config/tasks/active`, {
        method: 'PUT',
        body: JSON.stringify({ filename })
      });
      if (!resp.ok) throw new Error('切换失败');
      this.showToast(`✅ 已切换到题本: ${filename}`);
      await this.renderTasksTab(document.getElementById('config-body'));
    } catch (e) {
      this.showToast('❌ 切换失败: ' + e.message);
    }
  }

  async deleteTask(filename) {
    if (!confirm(`确认删除题本 ${filename}？此操作不可恢复。`)) return;
    try {
      const resp = await this.authFetch(`${this.apiBase}/api/admin/config/tasks/${encodeURIComponent(filename)}`, {
        method: 'DELETE'
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || '删除失败');
      }
      this.showToast(`✅ 已删除题本: ${filename}`);
      await this.renderTasksTab(document.getElementById('config-body'));
    } catch (e) {
      this.showToast('❌ 删除失败: ' + e.message);
    }
  }

  async copyTask(filename) {
    const newFilename = prompt('新题本文件名:', filename.replace('.json', '_copy.json'));
    if (!newFilename) return;
    try {
      const resp = await this.authFetch(`${this.apiBase}/api/admin/config/tasks/${encodeURIComponent(filename)}/copy`, {
        method: 'POST',
        body: JSON.stringify({ filename: newFilename })
      });
      if (!resp.ok) throw new Error('复制失败');
      this.showToast(`✅ 已复制为: ${newFilename}`);
      await this.renderTasksTab(document.getElementById('config-body'));
    } catch (e) {
      this.showToast('❌ 复制失败: ' + e.message);
    }
  }

  async editTask(filename) {
    let editorDiv = document.getElementById('task-editor');
    if (!editorDiv) {
      this.activeTab = 'tasks';
      await this.loadTab();
      editorDiv = document.getElementById('task-editor');
    }
    if (!editorDiv) return;
    editorDiv.style.display = 'block';
    setTimeout(() => editorDiv.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);

    try {
      // 读取题本详情
      const resp = await this.authFetch(`${this.apiBase}/api/admin/config/tasks`);
      const data = await resp.json();
      const taskPath = `${this.apiBase}/../tasks/${filename}`;
      // 读取题本内容
      const fileResp = await this.authFetch(`${this.apiBase}/api/admin/config/tasks/${encodeURIComponent(filename)}`);
      let content = '';
      if (fileResp.ok) {
        const taskData = await fileResp.json();
        content = JSON.stringify(taskData, null, 2);
      } else {
        // fallback: 从题本列表中查找
        content = JSON.stringify(data, null, 2);
      }

      editorDiv.innerHTML = `
        <div style="border:1px solid var(--border);border-radius:8px;padding:16px">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
            <h4>编辑题本: ${this.escapeHtml(filename)}</h4>
            <button class="btn btn-ghost btn-sm" onclick="document.getElementById('task-editor').style.display='none'">取消</button>
          </div>
          <textarea class="form-input" id="task-content-editor" style="width:100%;min-height:400px;font-family:monospace;font-size:12px;resize:vertical">${this.escapeHtml(content)}</textarea>
          <div style="margin-top:12px;display:flex;gap:8px">
            <button class="btn btn-primary btn-sm" onclick="window.configPanel.saveTaskContent('${this.escapeHtml(filename)}')">保存</button>
          </div>
        </div>
      `;
    } catch (e) {
      editorDiv.innerHTML = `<div style="padding:16px;color:#e74c3c">加载失败: ${this.escapeHtml(e.message)}</div>`;
    }
  }

  async saveTaskContent(filename) {
    const content = document.getElementById('task-content-editor')?.value;
    if (!content) return;
    try {
      JSON.parse(content); // 验证 JSON
      const resp = await this.authFetch(`${this.apiBase}/api/admin/config/tasks/${encodeURIComponent(filename)}`, {
        method: 'PUT',
        body: JSON.stringify({ content })
      });
      if (!resp.ok) throw new Error('保存失败');
      this.showToast('✅ 题本已保存');
    } catch (e) {
      if (e instanceof SyntaxError) {
        this.showToast('❌ JSON 格式错误，请检查');
      } else {
        this.showToast('❌ 保存失败: ' + e.message);
      }
    }
  }

  showNewTaskForm() {
    let editorDiv = document.getElementById('task-editor');
    if (!editorDiv) {
      // task-editor 不存在，重新渲染题本Tab后再试
      this.activeTab = 'tasks';
      this.loadTab().then(() => {
        editorDiv = document.getElementById('task-editor');
        if (editorDiv) {
          this._fillNewTaskForm(editorDiv);
        } else {
          this.showToast('❌ 无法打开新建表单');
        }
      });
      return;
    }
    this._fillNewTaskForm(editorDiv);
  }

  _fillNewTaskForm(editorDiv) {
    editorDiv.style.display = 'block';
    setTimeout(() => editorDiv.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);

    const template = JSON.stringify({
      "name": "新题本",
      "description": "题本描述",
      "total_duration_minutes": 90,
      "time_warning_minutes": 2,
      "candidate_context": {
        "role": "角色名称",
        "reporting_line": "汇报线",
        "tenure": "任期",
        "company_profile": {}
      },
      "stages": [
        {
          "id": 1,
          "name": "阶段一",
          "duration_minutes": 30,
          "description": "阶段描述"
        }
      ]
    }, null, 2);

    editorDiv.innerHTML = `
      <div style="border:1px solid var(--border);border-radius:8px;padding:16px">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
          <h4>新建题本</h4>
          <button class="btn btn-ghost btn-sm" onclick="document.getElementById('task-editor').style.display='none'">取消</button>
        </div>
        <div class="config-field">
          <label>文件名</label>
          <input type="text" class="form-input config-input" id="new-task-filename" placeholder="my_task.json" value="new_task.json">
        </div>
        <textarea class="form-input" id="task-content-editor" style="width:100%;min-height:400px;font-family:monospace;font-size:12px;resize:vertical">${this.escapeHtml(template)}</textarea>
        <div style="margin-top:12px">
          <button class="btn btn-primary btn-sm" onclick="window.configPanel.createTask()">创建</button>
        </div>
      </div>
    `;
  }

  async createTask() {
    const filename = document.getElementById('new-task-filename')?.value;
    const content = document.getElementById('task-content-editor')?.value;
    if (!filename || !content) return;
    try {
      JSON.parse(content); // 验证 JSON
      const resp = await this.authFetch(`${this.apiBase}/api/admin/config/tasks`, {
        method: 'POST',
        body: JSON.stringify({ filename, content })
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || '创建失败');
      }
      this.showToast('✅ 题本已创建');
      await this.renderTasksTab(document.getElementById('config-body'));
    } catch (e) {
      if (e instanceof SyntaxError) {
        this.showToast('❌ JSON 格式错误，请检查');
      } else {
        this.showToast('❌ 创建失败: ' + e.message);
      }
    }
  }

  // ========== 评估维度 ==========

  async renderEvaluationTab(body) {
    const resp = await this.authFetch(`${this.apiBase}/api/admin/config/evaluation`);
    if (!resp.ok) throw new Error('获取评估配置失败');
    this.evaluationConfig = await resp.json();

    const c = this.evaluationConfig;
    const weights = c.dimension_weights || {};
    const thresholds = c.level_thresholds || {};
    const scoreRange = c.score_range || { min: 1.0, max: 4.0 };
    const keywords = c.keywords || {};

    const weightTotal = Object.values(weights).reduce((a, b) => a + b, 0);
    const dimLabels = {
      ai_fluency: 'AI 流利度',
      human_ai_judgment: '人机判断力',
      architecture_design: '架构设计力',
      hybrid_orchestration: '混合编排力',
      cognitive_depth: '认知深度',
      problem_modeling: '问题建模'
    };

    body.innerHTML = `
      <div class="config-section">
        <h3>评估维度配置</h3>

        <div class="config-subsection">
          <h4>维度权重 <span id="weight-total" style="font-size:13px;color:${Math.abs(weightTotal - 1) < 0.01 ? 'var(--success)' : '#e74c3c'}">（总和: ${weightTotal.toFixed(2)}）</span></h4>
          ${Object.entries(dimLabels).map(([key, label]) => `
            <div class="config-field" style="display:flex;align-items:center;gap:12px">
              <label style="min-width:100px;margin:0">${label}</label>
              <input type="range" min="0" max="0.5" step="0.01" value="${weights[key] || 0}" class="config-slider eval-weight" data-key="${key}" style="flex:1"
                oninput="document.getElementById('wval-${key}').textContent=this.value;window.configPanel.updateWeightTotal()">
              <span id="wval-${key}" style="min-width:40px;text-align:right">${weights[key] || 0}</span>
            </div>
          `).join('')}
        </div>

        <div class="config-subsection">
          <h4>级别阈值</h4>
          <div class="config-field" style="display:flex;gap:16px;flex-wrap:wrap">
            <div>
              <label>L1 (入门) < </label>
              <input type="number" class="form-input config-input eval-threshold" data-key="L1" value="${thresholds.L1 || 1.8}" step="0.1" min="0" max="4" style="width:80px">
            </div>
            <div>
              <label>L2 (进阶) < </label>
              <input type="number" class="form-input config-input eval-threshold" data-key="L2" value="${thresholds.L2 || 2.5}" step="0.1" min="0" max="4" style="width:80px">
            </div>
            <div>
              <label>L3 (熟练) < </label>
              <input type="number" class="form-input config-input eval-threshold" data-key="L3" value="${thresholds.L3 || 3.2}" step="0.1" min="0" max="4" style="width:80px">
            </div>
            <div>
              <label>L4 (专家) ≥ L3</label>
            </div>
          </div>
        </div>

        <div class="config-subsection">
          <h4>评分范围</h4>
          <div class="config-field" style="display:flex;gap:16px">
            <div>
              <label>最低分</label>
              <input type="number" class="form-input config-input" id="eval-score-min" value="${scoreRange.min || 1.0}" step="0.1" style="width:80px">
            </div>
            <div>
              <label>最高分</label>
              <input type="number" class="form-input config-input" id="eval-score-max" value="${scoreRange.max || 4.0}" step="0.1" style="width:80px">
            </div>
          </div>
        </div>

        <div class="config-subsection">
          <h4>关键词表</h4>
          <div class="config-field">
            <label>拆解关键词</label>
            <div id="kw-decomposition" class="keyword-tags">
              ${(keywords.decomposition || []).map(kw => `<span class="kw-tag">${this.escapeHtml(kw)}<span class="kw-remove" onclick="this.parentElement.remove();window.configPanel.updateWeightTotal()">×</span></span>`).join('')}
            </div>
            <div style="display:flex;gap:4px;margin-top:4px">
              <input type="text" class="form-input config-input" id="kw-add-decomposition" placeholder="添加关键词" style="width:120px">
              <button class="btn btn-ghost btn-sm" onclick="window.configPanel.addKeyword('decomposition')">+</button>
            </div>
          </div>
          <div class="config-field">
            <label>澄清关键词</label>
            <div id="kw-clarification" class="keyword-tags">
              ${(keywords.clarification || []).map(kw => `<span class="kw-tag">${this.escapeHtml(kw)}<span class="kw-remove" onclick="this.parentElement.remove();window.configPanel.updateWeightTotal()">×</span></span>`).join('')}
            </div>
            <div style="display:flex;gap:4px;margin-top:4px">
              <input type="text" class="form-input config-input" id="kw-add-clarification" placeholder="添加关键词" style="width:120px">
              <button class="btn btn-ghost btn-sm" onclick="window.configPanel.addKeyword('clarification')">+</button>
            </div>
          </div>
          <div class="config-field">
            <label>验证关键词</label>
            <div id="kw-verification" class="keyword-tags">
              ${(keywords.verification || []).map(kw => `<span class="kw-tag">${this.escapeHtml(kw)}<span class="kw-remove" onclick="this.parentElement.remove();window.configPanel.updateWeightTotal()">×</span></span>`).join('')}
            </div>
            <div style="display:flex;gap:4px;margin-top:4px">
              <input type="text" class="form-input config-input" id="kw-add-verification" placeholder="添加关键词" style="width:120px">
              <button class="btn btn-ghost btn-sm" onclick="window.configPanel.addKeyword('verification')">+</button>
            </div>
          </div>
        </div>

        <div class="config-actions">
          <button class="btn btn-ghost" onclick="window.configPanel.resetEvaluation()">🔄 恢复默认</button>
          <button class="btn btn-primary" onclick="window.configPanel.saveEvaluationConfig()">💾 保存配置</button>
        </div>

        <div style="margin-top:16px;font-size:12px;color:var(--text-muted)">
          ⚠️ 修改权重/阈值后，新评估将使用新配置。已有评估不受影响（版本化保护）。
        </div>
      </div>
    `;
  }

  updateWeightTotal() {
    const sliders = document.querySelectorAll('.eval-weight');
    let total = 0;
    sliders.forEach(s => { total += parseFloat(s.value) || 0; });
    const totalEl = document.getElementById('weight-total');
    if (totalEl) {
      totalEl.textContent = `（总和: ${total.toFixed(2)}）`;
      totalEl.style.color = Math.abs(total - 1) < 0.01 ? 'var(--success)' : '#e74c3c';
    }
  }

  addKeyword(category) {
    const input = document.getElementById(`kw-add-${category}`);
    const value = input?.value?.trim();
    if (!value) return;
    const container = document.getElementById(`kw-${category}`);
    if (!container) return;
    const tag = document.createElement('span');
    tag.className = 'kw-tag';
    tag.innerHTML = `${this.escapeHtml(value)}<span class="kw-remove" onclick="this.parentElement.remove()">×</span>`;
    container.appendChild(tag);
    input.value = '';
  }

  async saveEvaluationConfig() {
    // 收集权重
    const weights = {};
    document.querySelectorAll('.eval-weight').forEach(s => {
      weights[s.dataset.key] = parseFloat(s.value) || 0;
    });

    // 收集阈值
    const thresholds = {};
    document.querySelectorAll('.eval-threshold').forEach(s => {
      thresholds[s.dataset.key] = parseFloat(s.value) || 0;
    });

    // 收集关键词
    const keywords = {};
    ['decomposition', 'clarification', 'verification'].forEach(cat => {
      const container = document.getElementById(`kw-${cat}`);
      if (container) {
        keywords[cat] = Array.from(container.querySelectorAll('.kw-tag')).map(tag => tag.textContent.replace('×', '').trim());
      }
    });

    const updates = {
      dimension_weights: weights,
      level_thresholds: thresholds,
      score_range: {
        min: parseFloat(document.getElementById('eval-score-min')?.value || 1.0),
        max: parseFloat(document.getElementById('eval-score-max')?.value || 4.0)
      },
      keywords
    };

    try {
      const resp = await this.authFetch(`${this.apiBase}/api/admin/config/evaluation`, {
        method: 'PUT',
        body: JSON.stringify(updates)
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || '保存失败');
      }
      this.showToast('✅ 评估配置已保存并生效');
    } catch (e) {
      this.showToast('❌ 保存失败: ' + e.message);
    }
  }

  async resetEvaluation() {
    if (!confirm('确认重置评估配置为默认值？')) return;
    try {
      const resp = await this.authFetch(`${this.apiBase}/api/admin/config/evaluation/reset`, { method: 'POST' });
      if (!resp.ok) throw new Error('重置失败');
      this.showToast('✅ 已重置为默认值');
      await this.renderEvaluationTab(document.getElementById('config-body'));
    } catch (e) {
      this.showToast('❌ 重置失败: ' + e.message);
    }
  }

  // ========== 变更历史 ==========

  async renderChangelogTab(body) {
    try {
      const resp = await this.authFetch(`${this.apiBase}/api/admin/config/changelog`);
      if (!resp.ok) throw new Error('获取变更历史失败');
      const data = await resp.json();
      const logs = data.changelog || [];

      body.innerHTML = `
        <div class="config-section">
          <h3>配置变更历史</h3>
          ${logs.length === 0 ? '<div style="padding:40px;text-align:center;color:var(--text-muted)">暂无变更记录</div>' : ''}
          <div class="changelog-list">
            ${logs.map(log => `
              <div class="changelog-item">
                <div class="changelog-meta">
                  <span class="changelog-category">${this.escapeHtml(log.category)}</span>
                  <span class="changelog-key">${this.escapeHtml(log.key)}</span>
                  <span class="changelog-time">${log.created_at || ''}</span>
                </div>
                <div class="changelog-diff">
                  <span style="color:#e74c3c">- ${this.escapeHtml(log.old_value || '(无)')}</span>
                  <span style="color:#10b981">+ ${this.escapeHtml(log.new_value || '(无)')}</span>
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    } catch (e) {
      body.innerHTML = `<div style="padding:40px;color:#e74c3c">加载失败: ${this.escapeHtml(e.message)}</div>`;
    }
  }

  // ========== 工具 ==========

  escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  showToast(message) {
    if (typeof window.showToast === 'function') {
      window.showToast(message);
    } else {
      const toast = document.createElement('div');
      toast.className = 'toast';
      toast.textContent = message;
      document.body.appendChild(toast);
      setTimeout(() => toast.remove(), 3000);
    }
  }
}

// 全局单例
window.configPanel = new ConfigPanel();
