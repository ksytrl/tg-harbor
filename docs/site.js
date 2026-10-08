'use strict';
const copy = document.getElementById('copy-home');
const state = document.getElementById('copy-state');
const local = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname) || location.protocol === 'file:';
if (local) {
  copy.disabled = true;
  state.textContent = '当前是本地预览。发布后可复制公开主页地址。';
}
copy.addEventListener('click', async () => {
  const home = new URL('./', location.href).href;
  try {
    await navigator.clipboard.writeText(home);
    state.textContent = '已复制，可粘贴到 Telegram 应用申请表的 URL。';
  } catch {
    state.textContent = `请复制浏览器地址栏中的主页地址：${home}`;
  }
});
fetch('site.json').then(response => response.ok ? response.json() : null).then(config => {
  if (!config || !config.repository) return;
  const repository = new URL(config.repository);
  if (repository.protocol !== 'https:' || repository.hostname !== 'github.com') return;
  const link = document.getElementById('repository-link');
  link.href = repository.href;
  link.hidden = false;
}).catch(() => {});
