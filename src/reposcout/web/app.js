const state = { data: null, tab: 'trending' };
const byId = id => document.getElementById(id);
const text = value => document.createTextNode(String(value ?? ''));
const element = (tag, className = '', content = '') => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.append(text(content));
  return node;
};
const empty = (title, detail) => {
  const node = element('div', 'empty');
  node.append(element('strong', '', title), element('p', '', detail));
  return node;
};
const repoLink = slug => {
  const link = element('a', 'repo-name', slug);
  link.href = `https://github.com/${slug}`;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  return link;
};
const reportLink = (path, label) => {
  const link = element('a', 'text-link', label);
  link.href = `/reports/${path}`;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  return link;
};
const button = (label, action, value, subtle = false) => {
  const node = element('button', subtle ? 'subtle' : 'secondary', label);
  node.type = 'button';
  node.dataset.action = action;
  node.dataset.value = value;
  node.addEventListener('click', () => act({ action, value }, node));
  return node;
};
const badge = (label, tone = '') => element('span', `badge ${tone}`, label);
const runLabel = run => ({ completed: '已完成', partial: '部分完成', running: '审查中', failed: '失败', incomplete: '未完成', pending: '待审查' })[run?.state] || '尚未审查';

function showNotice(message, error = false) {
  const notice = byId('notice');
  notice.textContent = message;
  notice.className = error ? 'notice error' : 'notice';
  notice.setAttribute('role', error ? 'alert' : 'status');
  notice.hidden = false;
}
function focusAfterAction(payload) {
  let target;
  if (payload.action === 'opportunity_status') {
    target = [...document.querySelectorAll('[data-item-id]')].find(node => node.dataset.itemId === payload.value);
  } else if (payload.action === 'follow' && state.tab === 'following') {
    target = [...document.querySelectorAll('#following-list .row')].find(node => node.dataset.slug?.toLowerCase() === payload.value.replace(/^https:\/\/github\.com\//, '').replace(/\.git$/, '').toLowerCase())?.querySelector('button');
  } else if (payload.action === 'unfollow') {
    target = byId('repo-url');
  } else {
    target = state.tab === 'trending'
      ? document.querySelector('#trending-list button, #sent-pending-list button, #ignored-list button')
      : document.querySelector('#following-list button');
  }
  (target || byId('notice')).focus();
}
function successMessage(payload) {
  return ({follow:'已关注仓库',unfollow:'已取消关注',ignore:'已标记不感兴趣',undo_ignore:'已撤销不感兴趣',opportunity_status:'机会状态已保存'})[payload.action] || '已保存';
}
async function load() {
  try {
    const response = await fetch('/api/state');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();
    render();
  } catch (error) { showNotice(`无法读取本机数据：${error.message}`, true); }
}
async function act(payload, trigger) {
  trigger.disabled = true;
  try {
    const response = await fetch('/api/action', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    state.data = result;
    render();
    showNotice(successMessage(payload));
    focusAfterAction(payload);
    return true;
  } catch (error) {
    showNotice(`操作未保存：${error.message}`, true);
    trigger.disabled = false;
    return false;
  }
}
function render() {
  const data = state.data;
  if (!data) return;
  byId('date-label').textContent = data.day;
  const scan = data.scan || data.latest_scan;
  byId('page-subtitle').textContent = scan
    ? `最近扫描 ${scan.day} · ${scan.catch_up ? '开机补跑' : '日常扫描'} · ${runLabel(scan)}${data.scan ? '' : ' · 今天尚未运行'}`
    : '还没有每日扫描；13:00 后运行任务即可看到今日推荐。';
  const mail = data.delivery;
  byId('mail-subtitle').textContent = mail
    ? ({sent:'今日邮件已发送',pending:'今日邮件待发送',sending:'今日邮件发送中',failed:'今日邮件发送失败',uncertain:'邮件投递状态待核对'}[mail.status] || '今日邮件状态未知') + (mail.error ? ` · ${mail.error}` : '')
    : !data.scan ? '今日尚未扫描'
    : data.scan.state === 'running' ? '今日审查中；有新内容会在 18:00 后发送'
    : data.pending_mail_items ? `待推送 ${data.pending_mail_items} 项新内容 · 18:00 后发送`
    : '今日无新仓库或已核验机会，不发送邮件';
  byId('scan-indicator').replaceChildren(badge(runLabel(scan), scan?.state === 'completed' ? 'good' : scan?.state === 'partial' ? 'warn' : 'neutral'));
  byId('trending-count').textContent = data.trending.length + data.sent_pending.length;
  byId('following-count').textContent = data.repositories.length;
  byId('opportunity-count').textContent = data.opportunities.length;
  for (const tab of document.querySelectorAll('[data-tab]')) {
    const active = tab.dataset.tab === state.tab;
    if (active) tab.setAttribute('aria-current', 'page'); else tab.removeAttribute('aria-current');
  }
  for (const view of document.querySelectorAll('.view')) view.hidden = view.id !== `${state.tab}-view`;
  renderTrending(data);
  renderFollowing(data);
  renderOpportunities(data);
}
function renderTrending(data) {
  const list = byId('trending-list');
  list.replaceChildren();
  if (data.scan?.trending_state === 'failed') {
    list.append(empty('今天的 Trending 获取失败', data.scan.trending_error || '请稍后运行任务重试；旧榜单不会冒充今日结果。'));
  } else if (!data.scan) {
    list.append(empty('等待今天的榜单', '每日扫描完成后，尚未处理的仓库会出现在这里。'));
  } else if (!data.trending.length) {
    list.append(empty('今天没有新的仓库推荐', '当前榜单的仓库都已关注、忽略或推送过。'));
  } else {
    for (const row of data.trending) {
      const item = element('article', 'row');
      item.dataset.slug = row.slug;
      const body = element('div', 'row-main');
      body.append(element('div', 'ordinal', String(row.position + 1).padStart(2, '0')), repoLink(row.slug), element('p', 'description', row.description || 'GitHub 今日 Trending 仓库'));
      const actions = element('div', 'actions');
      actions.append(button('关注', 'follow', row.slug), button('不感兴趣', 'ignore', row.slug, true));
      item.append(body, actions); list.append(item);
    }
  }
  const pendingSection = byId('sent-pending-section');
  pendingSection.hidden = !data.sent_pending.length;
  const pendingList = byId('sent-pending-list'); pendingList.replaceChildren();
  for (const row of data.sent_pending) {
    const item = element('article', 'row'); item.dataset.slug = row.slug;
    const body = element('div', 'row-main');
    body.append(repoLink(row.slug), element('p', 'description', row.description || 'GitHub Trending 仓库'),
      element('p', 'opportunity-meta', `邮件推送 ${row.sent_day}`));
    const actions = element('div', 'actions');
    actions.append(button('关注', 'follow', row.slug), button('不感兴趣', 'ignore', row.slug, true));
    item.append(body, actions); pendingList.append(item);
  }
  const ignored = byId('ignored-list'); ignored.replaceChildren();
  if (!data.ignored.length) ignored.append(element('p', 'quiet', '暂无已忽略仓库。'));
  for (const row of data.ignored) {
    const item = element('div', 'compact-row');
    item.append(repoLink(row.slug), button('撤销', 'undo_ignore', row.slug, true));
    ignored.append(item);
  }
}
function renderFollowing(data) {
  const list = byId('following-list'); list.replaceChildren();
  if (!data.repositories.length) list.append(empty('还没有关注仓库', '粘贴 GitHub 仓库 URL，明天会进入完整审查。'));
  for (const row of data.repositories) {
    const run = data.runs.find(item => item.slug === row.slug);
    const history = data.history.find(item => item.slug === row.slug);
    const item = element('article', 'row');
    item.dataset.slug = row.slug;
    const body = element('div', 'row-main');
    const headline = element('div', 'row-headline');
    headline.append(repoLink(row.slug), badge(runLabel(run), run?.state === 'completed' ? 'good' : run?.state === 'failed' || run?.state === 'incomplete' ? 'warn' : 'neutral'));
    body.append(headline);
    const details = element('div', 'detail-line');
    if (run?.cutoff) details.append(element('span', '', `截止 ${run.cutoff}`));
    if (run?.report_path) details.append(reportLink(run.report_path, run.state === 'completed' ? '本轮完整报告' : '本轮未完成报告'));
    if (run?.progress_path) details.append(reportLink(run.progress_path, '调研进度'));
    if (history) details.append(reportLink(history.report_path, `历史报告 · ${history.report_day}`));
    if (run?.error) details.append(element('span', 'error-text', run.error));
    if (!details.childNodes.length) details.append(element('span', 'quiet', '等待下一次完整审查'));
    body.append(details);
    const actions = element('div', 'actions'); actions.append(button('取消关注', 'unfollow', row.slug, true));
    item.append(body, actions); list.append(item);
  }
  renderScanHistory(data);
}
function renderScanHistory(data) {
  const target = byId('scan-history'); target.replaceChildren();
  const entries = [
    ...data.scan_history.map(scan => ({ day: scan.day, scan })),
    ...data.missing_days.map(day => ({ day, scan: null }))
  ].sort((a, b) => b.day.localeCompare(a.day));
  if (!entries.length) { target.append(element('p', 'quiet', '尚无扫描记录。')); return; }
  const displayTime = (timestamp, day) => timestamp
    ? (timestamp.startsWith(day) ? timestamp.slice(11, 16) : timestamp.slice(0, 16).replace('T', ' '))
    : '';
  for (const entry of entries) {
    if (!entry.scan) {
      const missing = element('div', 'scan-day scan-missing');
      const summary = element('div', 'scan-summary');
      summary.append(element('span', 'scan-date', entry.day), badge('未运行', 'neutral'),
        element('span', 'meta', '本机未执行；历史 Trending 无法补取'));
      missing.append(summary); target.append(missing);
      continue;
    }
    const scan = entry.scan;
    const details = element('details', 'scan-day');
    const summary = element('summary', 'scan-summary');
    summary.append(element('span', 'scan-date', scan.day), badge(runLabel(scan), scan.state === 'completed' ? 'good' : 'warn'));
    if (scan.catch_up) summary.append(element('span', 'meta', '开机补跑'));
    summary.append(element('span', 'meta', `开始 ${displayTime(scan.started_at, scan.day)}`));
    if (scan.finished_at) summary.append(element('span', 'meta', `结束 ${displayTime(scan.finished_at, scan.day)}`));
    details.append(summary);
    const runs = data.run_history.filter(run => run.day === scan.day);
    const content = element('div', 'scan-runs');
    content.append(element('p', 'quiet', `Trending：${scan.trending_state === 'completed' ? '已获取' : scan.trending_state === 'failed' ? '获取失败' : '待获取'}${scan.trending_error ? ` · ${scan.trending_error}` : ''}`));
    for (const run of runs) {
      const row = element('div', 'scan-run');
      row.append(element('span', 'scan-run-name', run.slug), badge(runLabel(run), run.state === 'completed' ? 'good' : run.state === 'failed' || run.state === 'incomplete' ? 'warn' : 'neutral'));
      if (run.report_path) row.append(reportLink(run.report_path, run.state === 'completed' ? '完整报告' : '未完成报告'));
      if (run.progress_path) row.append(reportLink(run.progress_path, '进度'));
      if (run.error) row.append(element('span', 'error-text', run.error));
      content.append(row);
    }
    details.append(content); target.append(details);
  }
}
function renderOpportunities(data) {
  const target = byId('opportunity-list'); target.replaceChildren();
  if (!data.opportunities.length) { target.append(empty('还没有机会记录', '完成一次调研或导入旧报告后，机会会按仓库显示。')); return; }
  const groups = new Map();
  for (const item of data.opportunities) {
    if (!groups.has(item.slug)) groups.set(item.slug, []);
    groups.get(item.slug).push(item);
  }
  for (const [slug, items] of groups) {
    const group = element('section', 'opportunity-group');
    const head = element('div', 'group-head');
    const headMain = element('div', 'group-head-main');
    headMain.append(repoLink(slug));
    const currentReport = data.runs.find(run => run.slug === slug && run.report_path);
    const latestReport = data.run_history.find(run => run.slug === slug && run.report_path);
    const historyReport = data.history.find(report => report.slug === slug);
    if (currentReport) headMain.append(reportLink(currentReport.report_path, currentReport.state === 'completed' ? '本轮完整报告' : '本轮未完成报告'));
    else if (latestReport) headMain.append(reportLink(latestReport.report_path, `过往报告 · ${latestReport.day}`));
    if (historyReport) headMain.append(reportLink(historyReport.report_path, `历史报告 · ${historyReport.report_day}`));
    head.append(headMain, element('span', 'meta', `${items.length} 条记录`));
    group.append(head);
    for (const item of items) {
      const card = element('article', 'opportunity');
      const top = element('div', 'opportunity-top');
      const link = element('a', 'opportunity-title', item.title); link.href = item.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      top.append(link, badge(item.status === 'ignored' ? '已忽略' : item.status === 'invalid' ? '已失效' : item.pending_recheck ? '待复核' : '当前有效', item.status === 'current' && !item.pending_recheck ? 'good' : 'neutral'));
      card.append(top, element('p', 'description', item.reason), element('p', 'opportunity-meta', `首次记录 ${item.first_seen} · 最近出现 ${item.last_seen}`));
      const actions = element('div', 'actions');
      if (item.status === 'current') {
        actions.append(statusButton(item, 'ignored', '忽略机会'));
        actions.append(statusButton(item, 'invalid', '标为失效'));
      } else {
        actions.append(statusButton(item, 'current', '恢复显示'));
      }
      card.append(actions); group.append(card);
    }
    target.append(group);
  }
}
function statusButton(item, next, label) {
  const node = element('button', 'subtle', label);
  node.type = 'button';
  node.dataset.itemId = item.id;
  node.addEventListener('click', () => act({ action: 'opportunity_status', value: item.id, status: next }, node));
  return node;
}
for (const tab of document.querySelectorAll('[data-tab]')) tab.addEventListener('click', () => { state.tab = tab.dataset.tab; render(); });
byId('add-form').addEventListener('submit', async event => {
  event.preventDefault();
  const input = byId('repo-url');
  if (await act({ action: 'follow', value: input.value }, event.submitter)) input.value = '';
});
load();
