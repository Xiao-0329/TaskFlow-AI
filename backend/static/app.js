// TaskFlow AI 前端：登录 + 角色化界面（管理员 5 页 / 员工 3 页）
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

const state = { user: null, employees: [], tasks: [], projects: [], industries: [] };

// ---------------- 鉴权 ----------------
function token() { return localStorage.getItem('tf_token') || ''; }

async function api(path, opts = {}) {
  const resp = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token() },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (resp.status === 401) { showLogin(); throw new Error('未登录'); }
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || resp.statusText);
  return data;
}

function showLogin() {
  localStorage.removeItem('tf_token');
  localStorage.removeItem('tf_user');
  state.user = null;
  $('#login-view').classList.remove('hidden');
  $('#app-view').classList.add('hidden');
}

function showApp(user) {
  state.user = user;
  $('#login-view').classList.add('hidden');
  $('#app-view').classList.remove('hidden');
  const isAdmin = user.role === 'admin';
  $('#tabs-admin').classList.toggle('hidden', !isAdmin);
  $('#tabs-employee').classList.toggle('hidden', isAdmin);
  $('#user-box').innerHTML = `${esc(user.name)} <span class="tag">${isAdmin ? '管理员' : '员工'}</span> <button class="btn small ghost" onclick="logout()">退出</button>`;
  // 切到第一个 tab
  const nav = isAdmin ? $('#tabs-admin') : $('#tabs-employee');
  nav.querySelector('button').click();
}

window.logout = () => showLogin();

$('#login-form').onsubmit = async e => {
  e.preventDefault();
  const err = $('#login-error');
  err.classList.add('hidden');
  try {
    const resp = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: $('#login-username').value.trim(), password: $('#login-password').value }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || '登录失败');
    localStorage.setItem('tf_token', data.token);
    localStorage.setItem('tf_user', JSON.stringify(data));
    showApp(data);
  } catch (ex) {
    err.textContent = ex.message;
    err.classList.remove('hidden');
  }
};

// ---------------- 基础 ----------------
function toast(msg, ok = true) {
  const t = $('#toast');
  t.textContent = msg;
  t.style.background = ok ? '#1a1d24' : '#e8463a';
  t.classList.remove('hidden');
  setTimeout(() => t.classList.add('hidden'), 2600);
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function openModal(title, bodyHtml) {
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = bodyHtml;
  $('#modal').classList.remove('hidden');
}
$('#modal-close').onclick = () => $('#modal').classList.add('hidden');
$('#modal').addEventListener('click', e => { if (e.target.id === 'modal') $('#modal').classList.add('hidden'); });

function statusText(s) {
  return { pending: '待分配', assigned: '进行中', submitted: '已提交', reviewed: '已完成' }[s] || s;
}

// 评估明细：逐条验收标准判定 + 防作弊标记（管理员/员工端共用）
function criteriaHtml(ev) {
  if (!ev) return '';
  const verdictIcon = { pass: '✅', partial: '⚠️', fail: '❌' };
  const verdictClass = { pass: 'vd-pass', partial: 'vd-partial', fail: 'vd-fail' };
  const rows = (ev.criteria || []).map(c => `
    <div class="crit-row ${verdictClass[c.verdict] || 'vd-partial'}">
      <span class="crit-verdict">${verdictIcon[c.verdict] || '⚠️'}</span>
      <div>
        <div class="crit-text">${esc(c.criterion)}</div>
        ${c.comment ? `<div class="crit-comment">${esc(c.comment)}</div>` : ''}
      </div>
    </div>`).join('');
  const flags = (ev.flags || []).map(f => `<div class="crit-flag">🚩 ${esc(f)}</div>`).join('');
  return `${flags}${rows}`;
}

// ---------------- Tab 切换（管理员与员工共用逻辑） ----------------
function bindTabs(navEl) {
  $$('button', navEl).forEach(btn => btn.onclick = () => {
    $$('.tab').forEach(s => s.classList.remove('active'));
    $$('nav button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    $('#tab-' + btn.dataset.tab).classList.add('active');
    refreshAll();
  });
}

async function refreshAll() {
  if (!state.user) return;
  try {
    if (state.user.role === 'admin') {
      await Promise.all([loadDashboard(), loadEmployees(), loadProjects(), loadReview(), loadPool(), loadWorkbench(), loadAttendance()]);
    } else {
      await Promise.all([loadClockPanel(), loadMyTasks(), loadMyRecords(), loadMyProfile()]);
    }
  } catch (e) { console.error(e); }
}

// ================================================================ 管理员：总览仪表盘
async function loadDashboard() {
  const ov = await api('/overview');

  // 团队负载
  const tb = $('#load-table tbody');
  tb.innerHTML = ov.loads.map(l => {
    const pct = Math.min(100, l.utilization);
    const barColor = l.utilization > 100 ? 'var(--danger)' : l.utilization >= 80 ? 'var(--warning)' : 'var(--brand)';
    return `
    <tr>
      <td><b>${esc(l.name)}</b></td>
      <td>${esc(l.role)}</td>
      <td>${l.load_hours}h / ${l.capacity}h</td>
      <td><span class="bar" style="width:100px"><span style="width:${pct}%;background:${barColor}"></span></span> <span class="score">${l.utilization}%</span></td>
      <td>${l.active_tasks}</td>
      <td>${l.overdue_count ? `<span class="status-pill st-draft">${l.overdue_count}</span>` : '0'}</td>
      <td style="max-width:220px;font-size:12px">${(l.projects || []).map(esc).join('、') || '—'}</td>
      <td>${l.on_leave ? '<span class="status-pill st-draft">请假</span>' : '<span class="status-pill st-reviewed">在岗</span>'}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="8" class="empty">暂无员工</td></tr>';

  // 僵尸任务
  const stale = ov.stale_tasks || [];
  $('#stale-list').innerHTML = stale.length ? stale.map(s => `
    <div class="card" style="border-left:3px solid var(--danger)">
      <b>${esc(s.title)}</b> → ${esc(s.assigned_to)}
      <span class="meta">分配于 ${s.assigned_at.replace('T', ' ').slice(0, 16)}，${s.est_hours}h</span>
      <span class="tag" style="background:#fdecea;color:var(--danger)">占用容量中</span>
    </div>`).join('') : '<div class="empty">没有超时未提交的任务</div>';

  // 项目紧急度
  $('#urgency-list').innerHTML = (ov.projects || []).map(p => {
    const u = p.urgency;
    const color = u >= 80 ? 'var(--danger)' : u >= 50 ? 'var(--warning)' : 'var(--brand)';
    return `
    <div style="display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid var(--border)">
      <span class="bar" style="width:120px"><span style="width:${u}%;background:${color}"></span></span>
      <span class="score">${u}</span>
      <b>${esc(p.name)}</b>
      <span class="tag">${p.deadline ? `截止 ${p.deadline}` : '无截止日期'}</span>
      <span class="meta">${p.pending} 待分配 · ${p.done} 已完成</span>
    </div>`;
  }).join('') || '<div class="empty">暂无进行中的项目</div>';

  // 全局任务池
  const pt = $('#global-pool-table tbody');
  pt.innerHTML = (ov.pool || []).map((t, i) => `
    <tr>
      <td>${i + 1}</td>
      <td><b>${esc(t.title)}</b>${t.phase ? `<div style="font-size:12px;color:var(--brand)">🏷 ${esc(t.phase)}</div>` : ''}</td>
      <td>${esc(t.project)}</td>
      <td>${t.project_deadline || '—'}</td>
      <td><span class="score">${t.urgency}</span></td>
      <td>${esc(t.priority)}</td>
      <td>D${t.difficulty}</td>
      <td>${t.est_hours}h</td>
    </tr>`).join('') || '<tr><td colspan="8" class="empty">任务池为空</td></tr>';
}

window.recycleStale = async () => {
  if (!confirm('回收所有超时未提交的任务？回收后释放对应员工的容量，任务重新进入任务池。')) return;
  try {
    const r = await api('/recycle-stale', { method: 'POST' });
    toast(`已回收 ${r.recycled} 个僵尸任务`);
    refreshAll();
  } catch (err) { toast(err.message, false); }
};

// ================================================================ 管理员：员工
async function loadEmployees() {
  state.employees = await api('/employees');
  const tb = $('#employee-table tbody');
  tb.innerHTML = state.employees.map(e => `
    <tr>
      <td><b>${esc(e.name)}</b><div style="font-size:12px;color:var(--muted)">@${esc(e.username)}</div></td>
      <td>${esc(e.role)}</td>
      <td>${(e.skills || []).map(s => `<span class="tag">${esc(s)}</span>`).join('')}</td>
      <td><span class="bar"><span style="width:${e.capability}%"></span></span><span class="score">${e.capability}</span></td>
      <td>D${e.difficulty_cap}</td>
      <td>${e.current_load}</td>
      <td>${e.task_count}</td>
      <td>${e.on_leave ? '是' : '否'}</td>
      <td>
        <button class="btn small" onclick="toggleLeave(${e.id}, ${!e.on_leave})">${e.on_leave ? '销假' : '请假'}</button>
        <button class="btn small" onclick="bindExternalModal(${e.id})">🔗 绑定考勤</button>
        <button class="btn small danger" onclick="delEmployee(${e.id})">删除</button>
      </td>
    </tr>`).join('') || '<tr><td colspan="9" class="empty">暂无员工</td></tr>';
}

window.bindExternalModal = id => {
  const e = state.employees.find(x => x.id === id);
  if (!e) return;
  const ids = e.external_ids || {};
  openModal(`绑定考勤账号 —— ${e.name}`, `
    <label>飞书 user/open_id（考勤事件匹配用）</label>
    <input id="ext-feishu" value="${esc(ids.feishu || '')}" placeholder="ou_xxxxxxxx">
    <label>钉钉 userid</label>
    <input id="ext-dingtalk" value="${esc(ids.dingtalk || '')}" placeholder="钉钉成员 userid">
    <label>企业微信 userid</label>
    <input id="ext-wecom" value="${esc(ids.wecom || '')}" placeholder="企微成员 userid">
    <div class="hint" style="margin:8px 0">在对应平台管理后台可查到成员 ID；绑定后，该平台推送的打卡事件会自动匹配到此员工并触发任务派发。</div>
    <button class="btn primary" onclick="saveExternal(${id})" style="width:100%">保存绑定</button>
  `);
};

window.saveExternal = async id => {
  const platforms = { feishu: $('#ext-feishu').value.trim(), dingtalk: $('#ext-dingtalk').value.trim(), wecom: $('#ext-wecom').value.trim() };
  try {
    for (const [platform, external_id] of Object.entries(platforms)) {
      await api(`/employees/${id}/external-id`, { method: 'PUT', body: { platform, external_id } });
    }
    toast('考勤账号已绑定'); $('#modal').classList.add('hidden'); loadEmployees();
  } catch (err) { toast(err.message, false); }
};

window.toggleLeave = async (id, onLeave) => {
  const e = state.employees.find(x => x.id === id);
  await api(`/employees/${id}`, { method: 'PUT', body: { name: e.name, role: e.role, skills: e.skills, on_leave: onLeave, username: e.username } });
  loadEmployees();
};
window.delEmployee = async id => {
  if (!confirm('确定删除该员工？')) return;
  try { await api(`/employees/${id}`, { method: 'DELETE' }); toast('已删除'); loadEmployees(); }
  catch (err) { toast(err.message, false); }
};

$('#employee-form').onsubmit = async e => {
  e.preventDefault();
  const f = e.target;
  const body = {
    name: f.name.value.trim(),
    role: f.role.value.trim(),
    skills: f.skills.value.split(/[,，]/).map(s => s.trim()).filter(Boolean),
    username: f.username.value.trim(),
    password: f.password.value || '123456',
  };
  if (!body.name) return;
  try {
    await api('/employees', { method: 'POST', body });
    f.reset(); toast('员工已添加，默认密码见表单占位'); loadEmployees();
  } catch (err) { toast(err.message, false); }
};

// ================================================================ 管理员：项目
async function loadProjects() {
  state.projects = await api('/projects');
  const tb = $('#project-table tbody');
  tb.innerHTML = state.projects.map(p => {
    // 阶段进度条
    const phases = p.phases || [];
    const phaseHtml = phases.length ? `
      <div class="phase-row">
        ${phases.map(ph => `<span class="phase-chip ${ph.decomposed ? (ph.task_pending === 0 && ph.task_total > 0 ? 'ph-done' : 'ph-active') : ''}" title="${esc(ph.title)}：${ph.task_done}/${ph.task_total} 完成${ph.task_pending ? `，${ph.task_pending} 待分配` : ''}">${esc(ph.title)}</span>`).join('<span class="phase-arrow">→</span>')}
      </div>` : '';
    // 按钮：未规划→AI拆解；有阶段且可滚动→拆下一阶段；全拆完→无
    const canNext = p.has_milestones && phases.some(ph => !ph.decomposed);
    const allDone = p.has_milestones && phases.length && phases.every(ph => ph.decomposed);
    return `
    <tr>
      <td>${p.id}</td>
      <td><b>${esc(p.name)}</b><div style="color:var(--muted);font-size:12px">${esc(p.goal)}</div>${phaseHtml}</td>
      <td><span class="tag ind-${esc(p.industry)}">${esc(p.industry_name || p.industry)}</span>${p.deadline ? `<div style="font-size:11px;color:var(--muted);margin-top:2px">⏰ ${esc(p.deadline)}</div>` : ''}</td>
      <td>${p.task_draft}</td>
      <td>${p.task_pending}</td>
      <td>${p.task_done}</td>
      <td>
        ${!p.has_milestones || !phases.length || !phases.some(ph => ph.decomposed)
          ? `<button class="btn small primary" onclick="decompose(${p.id})">AI 拆解</button>`
          : ''}
        ${canNext ? `<button class="btn small" onclick="decomposeNext(${p.id})">拆下一阶段</button>` : ''}
        ${allDone ? '<span class="hint">已全部拆解</span>' : ''}
        ${p.task_draft ? `<button class="btn small" onclick="bulkReview(${p.id},'approve')">通过草稿</button>` : ''}
        <button class="btn small danger" onclick="delProject(${p.id})">删除</button>
      </td>
    </tr>`;
  }).join('') || '<tr><td colspan="7" class="empty">暂无项目，先在上方创建</td></tr>';
}

$('#project-form').onsubmit = async e => {
  e.preventDefault();
  const f = e.target;
  if (!f.name.value.trim() || !f.goal.value.trim()) return toast('名称和目的必填', false);
  await api('/projects', { method: 'POST', body: {
    name: f.name.value.trim(), goal: f.goal.value.trim(), description: f.description.value.trim(),
    industry: f.industry.value,
  }});
  f.reset(); renderIndustryDesc(); toast('项目已创建，点击「AI 拆解」生成任务'); loadProjects();
};

// 行业包选择器
async function initIndustries() {
  state.industries = await fetch('/api/industries').then(r => r.json());
  const sel = $('#industry-select');
  sel.innerHTML = state.industries.map(i => `<option value="${i.key}">${esc(i.name)}</option>`).join('');
  sel.onchange = renderIndustryDesc;
  renderIndustryDesc();
}

function renderIndustryDesc() {
  const i = state.industries.find(x => x.key === $('#industry-select').value);
  if (!i) return;
  const capPct = Math.round(i.dispatch_capacity_ratio * 100);
  $('#industry-desc').innerHTML =
    `${esc(i.description)} —— 评分权重（质量 ${Math.round(i.quality_weight * 100)}% / 效率 ${Math.round(i.efficiency_weight * 100)}%），` +
    `自动派发容量 ${capPct}%${capPct < 100 ? '（预留事件处理余量）' : ''}`;
}

window.decompose = async id => {
  toast('LLM 拆解中：先规划里程碑，再拆第一阶段（1-2 分钟）…');
  try {
    const r = await api(`/projects/${id}/decompose`, { method: 'POST' });
    toast(r.summary);
    loadProjects();
  } catch (err) { toast('拆解失败: ' + err.message, false); }
};
window.decomposeNext = async id => {
  toast('LLM 滚动拆解下一阶段中…');
  try {
    const r = await api(`/projects/${id}/decompose-next`, { method: 'POST' });
    toast(r.summary);
    loadProjects();
  } catch (err) { toast(err.message, false); }
};
window.delProject = async id => {
  if (!confirm('删除项目及其所有任务？')) return;
  await api(`/projects/${id}`, { method: 'DELETE' });
  toast('已删除'); loadProjects();
};
window.bulkReview = async (id, action) => {
  const r = await api(`/tasks/bulk-review?project_id=${id}&action=${action}`, { method: 'POST' });
  toast(`已${action === 'approve' ? '通过' : '丢弃'} ${r.approved ?? r.rejected} 个任务`);
  loadProjects(); loadReview(); loadPool();
};

// ================================================================ 管理员：拆解审核
async function loadReview() {
  const tasks = await api('/tasks?review_status=draft');
  const box = $('#review-list');
  box.innerHTML = tasks.map(t => `
    <div class="card" data-task="${t.id}">
      <div class="card-head">
        <div>
          <b>${esc(t.title)}</b>
          ${t.phase ? `<span class="tag">🏷 ${esc(t.phase)}</span>` : ''}
          <span class="tag brand">${esc(t.deliverable_type)}</span>
          <span class="tag">D${t.difficulty}</span>
          <span class="tag">${esc(t.priority)}</span>
          <span class="tag">${t.est_hours}h</span>
        </div>
        <span class="meta">来自项目：${esc(t.project_name)}</span>
      </div>
      <div class="meta">${esc(t.description)}</div>
      <div class="meta">验收标准：${(t.acceptance || []).map(a => `✓ ${esc(a)}`).join('　')}</div>
      <div class="meta">技能：${(t.skill_tags || []).map(s => `<span class="tag">${esc(s)}</span>`).join('')}
        ${t.depends_on?.length ? `　依赖：${t.depends_on.map(esc).join(' → ')}` : ''}</div>
      <div class="actions">
        <button class="btn small primary" onclick="reviewTask(${t.id},'approve')">✓ 通过</button>
        <button class="btn small" onclick="editTask(${t.id})">编辑</button>
        <button class="btn small danger" onclick="reviewTask(${t.id},'reject')">✕ 丢弃</button>
      </div>
    </div>`).join('') || '<div class="empty">没有待审核的拆解任务</div>';
}

window.reviewTask = async (id, action) => {
  await api(`/tasks/${id}/review?action=${action}`, { method: 'POST' });
  toast(action === 'approve' ? '已通过，进入任务池' : '已丢弃');
  loadReview(); loadPool(); loadProjects();
};

window.editTask = async id => {
  const t = (await api('/tasks?review_status=draft')).find(x => x.id === id);
  if (!t) return;
  openModal('编辑任务', `
    <label>标题</label><input id="et-title" value="${esc(t.title)}">
    <label>说明</label><textarea id="et-desc">${esc(t.description)}</textarea>
    <label>交付物类型</label>
    <select id="et-type">${['code','document','data','image'].map(x =>
      `<option value="${x}" ${x === t.deliverable_type ? 'selected' : ''}>${x}</option>`).join('')}</select>
    <label>验收标准（每行一条）</label><textarea id="et-acc">${esc((t.acceptance || []).join('\n'))}</textarea>
    <label>技能标签（逗号分隔）</label><input id="et-skills" value="${esc((t.skill_tags || []).join(','))}">
    <div style="display:flex;gap:8px">
      <div style="flex:1"><label>预估工时(h)</label><input id="et-hours" type="number" step="0.5" value="${t.est_hours}"></div>
      <div style="flex:1"><label>难度 1-5</label><input id="et-diff" type="number" min="1" max="5" value="${t.difficulty}"></div>
      <div style="flex:1"><label>优先级</label><select id="et-pri">${['P0','P1','P2','P3'].map(x =>
        `<option ${x === t.priority ? 'selected' : ''}>${x}</option>`).join('')}</select></div>
    </div>
    <button class="btn primary" onclick="saveTask(${t.id})" style="width:100%">保存</button>
  `);
};

window.saveTask = async id => {
  const body = {
    title: $('#et-title').value, description: $('#et-desc').value,
    deliverable_type: $('#et-type').value,
    acceptance: $('#et-acc').value.split('\n').map(s => s.trim()).filter(Boolean),
    skill_tags: $('#et-skills').value.split(/[,，]/).map(s => s.trim()).filter(Boolean),
    est_hours: parseFloat($('#et-hours').value) || 6,
    difficulty: parseInt($('#et-diff').value) || 3,
    priority: $('#et-pri').value, due_date: null,
  };
  try {
    await api(`/tasks/${id}`, { method: 'PUT', body });
    toast('已保存'); $('#modal').classList.add('hidden'); loadReview();
  } catch (err) { toast(err.message, false); }
};

// ================================================================ 管理员：任务池
async function loadPool() {
  const tasks = await api('/tasks?review_status=approved');
  const tb = $('#pool-table tbody');
  tb.innerHTML = tasks.map(t => `
    <tr>
      <td><b>${esc(t.title)}</b>${t.phase ? `<div style="font-size:12px;color:var(--brand)">🏷 ${esc(t.phase)}</div>` : ''}</td>
      <td>${esc(t.project_name)}</td>
      <td>D${t.difficulty}</td>
      <td>${t.est_hours}h</td>
      <td>${(t.skill_tags || []).map(s => `<span class="tag">${esc(s)}</span>`).join('')}</td>
      <td><span class="status-pill st-${t.status}">${statusText(t.status)}</span>${t.assigned_to ? `<div style="font-size:12px;color:var(--muted)">${esc(t.assigned_to)}</div>` : ''}</td>
      <td>${t.status === 'pending' ? `<button class="btn small primary" onclick="assignModal(${t.id})">分配</button>` : ''}</td>
    </tr>`).join('') || '<tr><td colspan="7" class="empty">任务池为空</td></tr>';
}

window.assignModal = async id => {
  const cands = await api(`/tasks/${id}/candidates`);
  const top = cands.slice(0, 5);
  openModal('分配任务 —— 系统推荐人选', `
    ${top.map((c, i) => `
      <div class="card cand" style="${i === 0 ? 'border-color:var(--brand)' : ''}">
        <div class="card-head">
          <div>
            <b>${i + 1}. ${esc(c.employee_name)}</b>
            <span class="tag">${esc(c.role || '未填岗位')}</span>
            <span class="tag brand">能力 ${c.capability}</span>
            <span class="tag">负载 ${c.current_load}</span>
            ${i === 0 ? '<span class="tag brand">★ 最佳推荐</span>' : ''}
          </div>
          <button class="btn small primary" onclick="doAssign(${id}, ${c.employee_id})">分配给 TA</button>
        </div>
        <div class="reasons">理由：${c.reasons.map(esc).join('；') || '—'}</div>
      </div>`).join('') || '<div class="empty">没有可用员工（都在请假？）</div>'}
  `);
};

window.doAssign = async (taskId, employeeId) => {
  await api(`/tasks/${taskId}/assign?employee_id=${employeeId}`, { method: 'POST' });
  toast('已分配，员工登录后即可看到'); $('#modal').classList.add('hidden');
  loadPool(); loadWorkbench();
};

// ================================================================ 管理员：执行与评估
async function loadWorkbench() {
  const tasks = await api('/tasks?review_status=approved');
  const active = tasks.filter(t => t.status === 'assigned' || t.status === 'submitted');
  const tb = $('#workbench-table tbody');
  tb.innerHTML = active.map(t => `
    <tr>
      <td><b>${esc(t.title)}</b><div style="font-size:12px;color:var(--muted)">${esc(t.description)}</div></td>
      <td>${esc(t.assigned_to)}</td>
      <td>D${t.difficulty}</td>
      <td>${t.est_hours}h</td>
      <td style="max-width:260px">${(t.acceptance || []).map(a => `<div>✓ ${esc(a)}</div>`).join('')}</td>
      <td><span class="status-pill st-${t.status}">${statusText(t.status)}</span></td>
    </tr>`).join('') || '<tr><td colspan="6" class="empty">没有进行中的任务，去任务池分配</td></tr>';

  const submissions = await api('/submissions');
  const box = $('#submission-list');
  box.innerHTML = submissions.map(s => `
    <div class="card">
      <div class="card-head">
        <div><b>${esc(s.task_title)}</b>
          <span class="tag">${esc(s.employee)}</span>
          <span class="tag">${s.spent_hours}h 自报工时</span>
          <span class="meta">${s.submitted_at.replace('T', ' ').slice(0, 16)}</span>
        </div>
        ${s.evaluation ? `<span class="score">${s.evaluation.total_score}</span>` : `<button class="btn small primary" onclick="doEvaluate(${s.id})">AI 评估</button>`}
      </div>
      <div class="meta" style="white-space:pre-wrap;max-height:100px;overflow:auto">${esc(s.content)}</div>
      ${s.evaluation ? `
        <div class="eval-box">
          质量 <span class="score">${s.evaluation.quality_score}</span> ·
          效率 <span class="score">${s.evaluation.efficiency_score}</span> ·
          总分 <span class="score" style="color:var(--brand)">${s.evaluation.total_score}</span>
          ${criteriaHtml(s.evaluation)}
          <div class="fb">${esc(s.evaluation.feedback)}</div>
        </div>` : ''}
    </div>`).join('') || '<div class="empty">暂无提交记录</div>';
}

window.doEvaluate = async id => {
  toast('评估引擎运行中…');
  try {
    const ev = await api(`/submissions/${id}/evaluate`, { method: 'POST' });
    toast(`评估完成：总分 ${ev.total_score}${(ev.flags || []).length ? '（含可疑标记）' : ''}`);
    loadWorkbench(); loadEmployees();
  } catch (err) { toast('评估失败: ' + err.message, false); }
};

// ================================================================ 员工：打卡面板
async function loadClockPanel() {
  const att = await api('/me/attendance');
  const box = $('#clock-panel');
  const patternText = att.work_pattern === '2on2off' ? '上二休二' : '标准工作日';
  const dutyText = att.on_duty_today ? '今日排班上班' : '今日休息';
  const inTime = att.clock_in ? att.clock_in.replace('T', ' ').slice(0, 16) : null;
  const outTime = att.clock_out ? att.clock_out.replace('T', ' ').slice(0, 16) : null;
  box.innerHTML = `
    <div class="clock-row">
      <div>
        <b>${dutyText}</b> <span class="tag">${patternText}</span>
        ${inTime ? `<span class="tag brand">上班 ${inTime}</span>` : ''}
        ${outTime ? `<span class="tag brand">下班 ${outTime}</span>` : ''}
      </div>
      <div class="clock-actions">
        ${!inTime ? `<button class="btn primary" onclick="doClockIn()">🕘 上班打卡 · 自动领取今日任务</button>` : ''}
        ${inTime && !outTime ? `<button class="btn primary" onclick="doClockOut()">🏁 下班打卡 · 生成当日汇总</button>` : ''}
        ${inTime && outTime ? '<span class="hint">今日打卡已完成</span>' : ''}
      </div>
    </div>`;
}

window.doClockIn = async () => {
  try {
    const r = await api('/me/clock-in', { method: 'POST' });
    if (r.on_duty_note) toast(r.on_duty_note, false);
    toast(r.dispatch_note);
    await refreshAll();
  } catch (err) { toast(err.message, false); }
};

window.doClockOut = async () => {
  try {
    const s = await api('/me/clock-out', { method: 'POST' });
    let msg = `今日汇总：${s.submitted_count}/${s.assigned_count} 已提交，共 ${s.total_hours}h`;
    if (s.avg_score !== null) msg += `，均分 ${s.avg_score}`;
    toast(s.warning ? s.warning : msg, !s.warning);
    await refreshAll();
  } catch (err) { toast(err.message, false); }
};

// ================================================================ 管理员：考勤与排班
async function loadAttendance() {
  const records = await api('/attendance/today');
  const tb = $('#attendance-table tbody');
  tb.innerHTML = records.map(r => `
    <tr>
      <td><b>${esc(r.name)}</b></td>
      <td>${esc(r.role)}</td>
      <td><button class="btn small" onclick="cyclePattern(${r.employee_id}, '${r.work_pattern}')">${r.work_pattern === '2on2off' ? '上二休二' : '标准工作日'}</button></td>
      <td>${r.on_duty ? '<span class="status-pill st-reviewed">上班</span>' : '<span class="status-pill st-draft">休息</span>'}</td>
      <td>${r.clock_in ? r.clock_in.replace('T', ' ').slice(11, 16) : '—'}</td>
      <td>${r.clock_out ? r.clock_out.replace('T', ' ').slice(11, 16) : '—'}</td>
    </tr>`).join('');

  const schedule = await api('/schedule');
  const box = $('#schedule-list');
  box.innerHTML = schedule.map(s => `
    <div class="card">
      <div class="card-head">
        <div><b>${esc(s.name)}</b>
          <span class="tag">${s.work_pattern === '2on2off' ? `上二休二（周期起点 ${s.anchor || '未设置'}）` : '标准工作日'}</span>
          <button class="btn small" onclick="cyclePattern(${s.employee_id}, '${s.work_pattern}')">切换模式</button>
        </div>
        <span class="meta">今天：${s.on_duty_today ? '上班' : '休息'}</span>
      </div>
      <div class="cal-row">
        ${s.calendar.map(d => `
          <div class="cal-cell ${d.on_duty ? 'cal-on' : 'cal-off'}" title="${d.date} 周${d.weekday}">
            <div class="cal-date">${d.date.slice(5)}</div>
            <div class="cal-day">周${d.weekday}</div>
          </div>`).join('')}
      </div>
    </div>`).join('') || '<div class="empty">暂无员工</div>';
}

window.cyclePattern = async (id, current) => {
  // 标准 → 上二休二（以今天为周期起点）→ 标准
  const next = current === '2on2off' ? 'standard' : '2on2off';
  const label = next === '2on2off' ? '上二休二（今天为周期第 1 个工作日）' : '标准工作日';
  if (!confirm(`切换为「${label}」？`)) return;
  try {
    await api(`/employees/${id}/pattern`, { method: 'POST', body: { pattern: next, anchor: null } });
    toast('排班已更新'); loadAttendance();
  } catch (err) { toast(err.message, false); }
};

// ================================================================ 员工：我的任务
async function loadMyTasks() {
  const tasks = await api('/me/tasks');
  const box = $('#mytasks-list');
  box.innerHTML = tasks.map(t => `
    <div class="card">
      <div class="card-head">
        <div>
          <b>${esc(t.title)}</b>
          ${t.phase ? `<span class="tag">🏷 ${esc(t.phase)}</span>` : ''}
          <span class="tag brand">${esc(t.deliverable_type)}</span>
          <span class="tag">D${t.difficulty}</span>
          <span class="tag">${t.est_hours}h</span>
          <span class="tag">${esc(t.priority)}</span>
          <span class="status-pill st-${t.status}">${statusText(t.status)}</span>
        </div>
        ${t.status === 'assigned' ? `<button class="btn small primary" onclick="submitModal(${t.id})">提交交付物</button>` : ''}
      </div>
      <div class="meta">${esc(t.description)}</div>
      <div class="meta">验收标准：</div>
      ${(t.acceptance || []).map(a => `<div class="meta" style="margin-left:12px">✓ ${esc(a)}</div>`).join('')}
      ${t.depends_on?.length ? `<div class="meta">前置：${t.depends_on.map(esc).join(' → ')}</div>` : ''}
    </div>`).join('') || '<div class="empty">暂无任务。管理员分配后会出现在这里。</div>';
}

window.submitModal = id => {
  openModal('提交任务交付物', `
    <label>交付物内容（代码/文档/数据粘贴于此）</label>
    <textarea id="sub-content" style="min-height:180px"></textarea>
    <label>实际耗时（小时）</label>
    <input id="sub-hours" type="number" step="0.5" min="0" value="6">
    <button class="btn primary" onclick="doSubmit(${id})" style="width:100%">提交（下班前）</button>
  `);
};

window.doSubmit = async id => {
  const body = { content: $('#sub-content').value, spent_hours: parseFloat($('#sub-hours').value) || 0 };
  try {
    await api(`/me/tasks/${id}/submit`, { method: 'POST', body });
    toast('已提交，等待评估'); $('#modal').classList.add('hidden');
    loadMyTasks();
  } catch (err) { toast(err.message, false); }
};

// ================================================================ 员工：我的记录
async function loadMyRecords() {
  const submissions = await api('/me/submissions');
  const box = $('#myrecords-list');
  box.innerHTML = submissions.map(s => `
    <div class="card">
      <div class="card-head">
        <div><b>${esc(s.task_title)}</b>
          <span class="tag">${s.spent_hours}h 工时</span>
          <span class="meta">${s.submitted_at.replace('T', ' ').slice(0, 16)}</span>
        </div>
        ${s.evaluation ? `<span class="score">${s.evaluation.total_score}</span>` : '<span class="meta">评估中…</span>'}
      </div>
      ${s.evaluation ? `
        <div class="eval-box">
          质量 <span class="score">${s.evaluation.quality_score}</span> ·
          效率 <span class="score">${s.evaluation.efficiency_score}</span> ·
          总分 <span class="score" style="color:var(--brand)">${s.evaluation.total_score}</span>
          ${criteriaHtml(s.evaluation)}
          <div class="fb">${esc(s.evaluation.feedback)}</div>
        </div>` : ''}
    </div>`).join('') || '<div class="empty">暂无提交记录</div>';
}

// ================================================================ 员工：我的画像
async function loadMyProfile() {
  const p = await api('/me');
  $('#myprofile-box').innerHTML = `
    <h3>我的画像</h3>
    <div class="profile-grid">
      <div class="profile-item">
        <div class="profile-label">能力分</div>
        <div class="profile-value"><span class="bar" style="width:140px"><span style="width:${p.capability}%"></span></span> <span class="score">${p.capability}</span></div>
        <div class="profile-hint">由评估引擎按任务完成质量持续更新</div>
      </div>
      <div class="profile-item">
        <div class="profile-label">建议任务难度上限</div>
        <div class="profile-value">D${p.difficulty_cap}</div>
        <div class="profile-hint">系统下次分配任务时的难度参考</div>
      </div>
      <div class="profile-item">
        <div class="profile-label">当前任务负载</div>
        <div class="profile-value">${p.current_load}</div>
        <div class="profile-hint">进行中的任务数量</div>
      </div>
      <div class="profile-item">
        <div class="profile-label">已评估任务</div>
        <div class="profile-value">${p.task_count}</div>
        <div class="profile-hint">累计完成并评分的任务数</div>
      </div>
    </div>
    <div style="margin-top:16px">
      ${p.on_leave
        ? '<span class="status-pill st-draft">请假中</span> <button class="btn small" onclick="toggleMyLeave(false)">销假复工</button>'
        : '<button class="btn small" onclick="toggleMyLeave(true)">申请请假</button>'}
      <span class="hint">请假后管理员端分配建议会自动避开你</span>
    </div>`;
}

window.toggleMyLeave = async onLeave => {
  await api('/me/leave', { method: 'POST', body: { on_leave: onLeave } });
  toast(onLeave ? '已请假' : '已销假');
  loadMyProfile();
};

// ---------------- 启动 ----------------
bindTabs($('#tabs-admin'));
bindTabs($('#tabs-employee'));

(async () => {
  const info = await fetch('/api/llm-info').then(r => r.json());
  $('#llm-badge').textContent = `LLM: ${info.provider} / ${info.model}`;
  initIndustries().catch(() => {});
  // 已登录则直接进入
  const cached = localStorage.getItem('tf_user');
  if (token() && cached) {
    try {
      const me = await api('/me');  // 验证 token 有效性
      const u = JSON.parse(cached);
      showApp({ ...u, name: me.name, role: u.role });
      return;
    } catch { /* token 失效，回登录页 */ }
  }
  showLogin();
})();
