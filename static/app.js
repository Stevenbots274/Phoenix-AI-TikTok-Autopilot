const state = { dashboard: null, content: [], settings: null, user: null };

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

async function request(url, options = {}) {
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Something went wrong');
  return data;
}

function formatDate(value) {
  if (!value) return 'Not scheduled';
  return new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function formatName(value) { return value.replaceAll('_', ' ').toLowerCase().replace(/\b\w/g, (char) => char.toUpperCase()); }

function showToast(message) {
  const toast = $('#toast'); toast.textContent = message; toast.classList.remove('hidden');
  window.clearTimeout(showToast.timer); showToast.timer = window.setTimeout(() => toast.classList.add('hidden'), 3200);
}

function contentCard(item) {
  const ready = ['READY', 'WAITING_APPROVAL'].includes(item.status);
  return `<article class="content-card"><div class="content-card-top"><span class="format-label">${formatName(item.format)}</span><span class="content-status ${ready ? 'ready' : ''}">${formatName(item.status)}</span></div><h3>${escapeHtml(item.topic)}</h3><p>${escapeHtml(item.hook)}</p><div class="content-footer"><span>${formatDate(item.created_at)}</span><span>${item.duration_seconds}s</span></div></article>`;
}

function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[char])); }

function renderDashboard() {
  const dashboard = state.dashboard; if (!dashboard) return;
  const { counts, automation_enabled: active } = dashboard;
  $('#stat-automation').textContent = active ? 'Active' : 'Paused';
  $('#stat-automation-meta').textContent = active ? 'Generating on schedule' : 'Ready to configure';
  $('#stat-scheduled').textContent = counts.scheduled;
  $('#stat-ready').textContent = counts.ready;
  $('#stat-published').textContent = counts.published;
  $('#automation-toggle').checked = active;
  $('#automation-title').textContent = active ? 'Your studio is in motion.' : 'Your studio is waiting.';
  $('#recent-content').innerHTML = dashboard.recent.length ? dashboard.recent.map(contentCard).join('') : emptyContent('Your first content plan will appear here.');
  if (dashboard.next_post) {
    $('#next-post').innerHTML = `<div class="empty-orb">◷</div><strong>${escapeHtml(dashboard.next_post.topic)}</strong><p>${formatName(dashboard.next_post.format)} · ${formatDate(dashboard.next_post.scheduled_at)}</p><button class="button button-outline" data-view="calendar">View queue</button>`;
  }
  renderHealth(dashboard.health);
}

function renderStudio() { $('#studio-content').innerHTML = state.content.length ? state.content.map(contentCard).join('') : emptyContent('Generate a plan to start your studio.'); }

function renderQueue() {
  const scheduled = state.content.filter((item) => item.status === 'SCHEDULED');
  $('#queue-count').textContent = `${scheduled.length} post${scheduled.length === 1 ? '' : 's'}`;
  $('#queue-content').innerHTML = scheduled.length ? scheduled.map((item) => `<div class="queue-row"><div><strong>${escapeHtml(item.topic)}</strong><span>${formatName(item.format)}</span></div><span>${formatDate(item.scheduled_at)}</span><span class="content-status ready">Scheduled</span></div>`).join('') : '<div class="empty-state">Nothing scheduled yet. Create a plan, then add it to the queue.</div>';
}

function renderHealth(health) {
  $('#health-items').innerHTML = Object.entries(health).map(([name, value]) => `<div class="health-item">${formatName(name)} <b>${formatName(value)}</b></div>`).join('');
}

function emptyContent(message) { return `<div class="empty-state">${message}</div>`; }

async function load() {
  const auth = await request('/api/auth/me');
  if (!auth.authenticated) { window.location.href = '/login'; return; }
  state.user = auth.user;
  renderUser();
  const [dashboard, content, settings, tiktok, notifications] = await Promise.all([
    request('/api/dashboard'), request('/api/content'), request('/api/settings'), request('/api/tiktok/status'), request('/api/notifications'),
  ]);
  state.dashboard = dashboard; state.content = content.items; state.settings = settings;
  renderDashboard(); renderStudio(); renderQueue(); renderSettings(settings); renderTikTok(tiktok);
  $('#notification-count').style.display = notifications.items.some((item) => !item.read_at) ? 'block' : 'none';
}

function renderUser() {
  const name = state.user.display_name || 'Creator';
  $('#user-name').textContent = name;
  $('#user-email').textContent = state.user.email;
  $('#user-avatar').textContent = name.slice(0, 1).toUpperCase();
  $('#page-title').textContent = `Good morning, ${name}`;
}

function renderSettings(data) {
  const form = $('#settings-form'); const values = { ...data.profile, ...data.settings };
  Object.entries(values).forEach(([key, value]) => { if (form.elements[key]) form.elements[key].value = value; });
}

function renderTikTok(data) {
  $('#tiktok-name').textContent = data.account?.username ? `@${data.account.username}` : 'Not connected';
  $('#tiktok-message').textContent = data.account ? 'Account connected' : data.message;
  $('#connect-tiktok').textContent = data.account ? 'Manage account' : 'Connect TikTok';
  $('.tiktok-card .status-dot').classList.toggle('muted', !data.account);
}

function switchView(view) {
  $$('.view').forEach((item) => item.classList.toggle('hidden', item.id !== `view-${view}`));
  $$('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.view === view));
  const title = { dashboard:`Good morning, ${state.user?.display_name || 'Creator'}`, studio:'Content studio', calendar:'Publishing queue', settings:'Workspace settings' }[view];
  const kicker = { dashboard:'Workspace overview', studio:'Create and refine', calendar:'Plan ahead', settings:'Make it yours' }[view];
  $('#page-title').textContent = title; $('#page-kicker').textContent = kicker;
}

function openModal() { $('#generate-modal').classList.remove('hidden'); $('#generate-form input[name="topic"]').focus(); }
function closeModal() { $('#generate-modal').classList.add('hidden'); }

async function generate(event) {
  event.preventDefault(); const form = event.currentTarget; const formData = new FormData(form); const button = $('#generate-label'); const spinner = $('#generate-spinner');
  button.classList.add('hidden'); spinner.classList.remove('hidden');
  try {
    await request('/api/content/generate', { method:'POST', body: JSON.stringify({ topic:formData.get('topic'), niche:formData.get('niche'), format:formData.get('format'), duration_seconds:Number(formData.get('duration_seconds')), research:formData.get('research') === 'on' }) });
    closeModal(); form.reset(); showToast('Content plan created'); await load(); switchView('studio');
  } catch (error) { showToast(error.message); } finally { button.classList.remove('hidden'); spinner.classList.add('hidden'); }
}

async function saveSettings() {
  const formData = new FormData($('#settings-form')); const data = Object.fromEntries(formData.entries()); data.default_duration = Number(data.default_duration);
  try { await request('/api/settings', { method:'POST', body:JSON.stringify(data) }); showToast('Settings saved'); await load(); } catch (error) { showToast(error.message); }
}

async function toggleAutomation(event) {
  try { await request('/api/automation/toggle', { method:'POST', body:JSON.stringify({ enabled:event.target.checked }) }); showToast(event.target.checked ? 'Autopilot activated' : 'Autopilot paused'); await load(); } catch (error) { event.target.checked = !event.target.checked; showToast(error.message); }
}

async function connectTikTok() {
  try { const data = await request('/api/tiktok/oauth/start', { method:'POST', body:'{}' }); window.location.href = data.url; } catch (error) { showToast('TikTok setup needs developer credentials first'); }
}

$$('.nav-item').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.view)));
$$('[data-view]').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.view)));
['#open-generate','#open-generate-secondary','#open-generate-studio','#open-generate-calendar'].forEach((selector) => $(selector)?.addEventListener('click', openModal));
$('#close-generate').addEventListener('click', closeModal); $('#generate-modal').addEventListener('click', (event) => { if (event.target.id === 'generate-modal') closeModal(); });
$('#generate-form').addEventListener('submit', generate); $('#save-settings').addEventListener('click', saveSettings); $('#automation-toggle').addEventListener('change', toggleAutomation); $('#connect-tiktok').addEventListener('click', connectTikTok);
$('#logout').addEventListener('click', async () => { await request('/api/auth/logout', { method:'POST', body:'{}' }); window.location.href = '/'; });
$('#today').textContent = new Date().toLocaleDateString(undefined, { weekday:'short', month:'short', day:'numeric' });
load().catch((error) => { if (error.message === 'Sign in is required') window.location.href = '/login'; else showToast(error.message); });
