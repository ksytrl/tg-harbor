'use strict';
const $ = (q, root=document) => root.querySelector(q);
const $$ = (q, root=document) => [...root.querySelectorAll(q)];
const fragment = new URLSearchParams(location.hash.slice(1));
const TOKEN = fragment.get('session') || sessionStorage.getItem('harbor-session') || '';
if (TOKEN) sessionStorage.setItem('harbor-session', TOKEN);
history.replaceState(null, '', location.pathname);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icons = {
  grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  download:'<path d="M12 3v11m-4-4 4 4 4-4M4 15v5h16v-5"/>',
  folder:'<path d="M3 7V5h6l2 2h10v13H3z"/>',
  spark:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>',
  settings:'<path d="m9 3-.8 3-2.8 1-2.6-.8-1.2 3 2.1 2v2l-2.1 2 1.2 3 2.6-.8 2.8 1 .8 3h4l.8-3 2.8-1 2.6.8 1.2-3-2.1-2v-2l2.1-2-1.2-3-2.6.8-2.8-1-.8-3z"/><circle cx="11" cy="12" r="3"/>',
  layers:'<path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5"/>',
  chevron:'<path d="m8 10 4 4 4-4"/>',
  search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
  link:'<path d="m10 8 3-3a4 4 0 0 1 6 6l-3 3M14 16l-3 3a4 4 0 0 1-6-6l3-3M8 16l8-8"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  pause:'<path d="M8 5v14M16 5v14"/>',
  play:'<path d="m8 4 12 8-12 8z"/>',
  file:'<path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h4"/>',
  image:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 6-6 4 4 3-3 5 5"/>',
  video:'<rect x="3" y="5" width="13" height="14" rx="2"/><path d="m16 10 5-3v10l-5-3"/>',
  audio:'<path d="M9 18V5l11-2v13M9 9l11-2"/><ellipse cx="6" cy="18" rx="3" ry="2"/><ellipse cx="17" cy="16" rx="3" ry="2"/>',
  list:'<path d="M8 5h13M8 12h13M8 19h13M3 5h.1M3 12h.1M3 19h.1"/>',
  refresh:'<path d="M20 7v5h-5M4 17v-5h5M20 12a8 8 0 0 0-14-5M4 12a8 8 0 0 0 14 5"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
  shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
  cloud:'<path d="M7 18h11a4 4 0 0 0 1-8 7 7 0 0 0-13-1 4.5 4.5 0 0 0 1 9z"/>',
};
function icon(name){return `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.file}</svg>`;}
function fillIcons(root=document){$$('[data-icon]',root).forEach(e => e.innerHTML=icon(e.dataset.icon));}
function bytes(value){let n=Number(value)||0;if(n<1024)return n+' B';for(const unit of ['KB','MB','GB','TB']){n/=1024;if(n<1024)return (n>=100?n.toFixed(0):n.toFixed(1))+' '+unit;}return n.toFixed(1)+' PB';}
function day(value){const date=new Date(value);return Number.isNaN(+date)?'—':date.toLocaleDateString('zh-CN',{month:'2-digit',day:'2-digit'});}
function kindName(value){return {image:'图片',video:'视频',audio:'音频',file:'文件',all:'全部'}[value] || '文件';}
const labels={queued:'排队中',downloading:'下载中',completed:'已完成',paused:'已暂停',error:'失败',cancelled:'已取消',resolving:'读取中',waiting:'等待中'};
const app={view:'media',data:null,chats:[],chat:null,items:[],selected:new Set(),kind:'all',search:'',layout:'grid',taskFilter:'all',loading:false,nextOffset:0,scanned:0,modal:null,lastFocus:null,requestId:0};
async function api(path,body){
  const res=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:{'X-Harbor-Token':TOKEN,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await res.json();if(!res.ok)throw Error(data.error || '操作未完成');return data;
}
function assetUrl(item,thumb=false){
  if(item.source==='demo') return '/assets/'+encodeURIComponent(thumb?item.thumb:item.asset);
  return '/api/thumb?'+new URLSearchParams({chat_id:item.chat_id,id:item.id,token:TOKEN});
}
function fileUrl(job){return '/api/file?'+new URLSearchParams({id:job.id,token:TOKEN});}
function toast(message,error=false){const e=document.createElement('div');e.className='toast'+(error?' error':'');e.innerHTML=icon(error?'info':'check')+`<span>${esc(message)}</span>`;$('#toast-stack').append(e);setTimeout(()=>e.remove(),6500);}
function heading(title,description,actions=''){return `<div class="page-heading"><div><h1>${title}</h1><p>${description}</p></div><div class="actions">${actions}</div></div>`;}
function button(text,action,style='',symbol){return `<button class="btn ${style}" data-action="${action}">${symbol?icon(symbol):''}${text}</button>`;}
function empty(title,description,symbol='folder',action=''){return `<div class="empty"><div class="empty-icon">${icon(symbol)}</div><h3>${title}</h3><p>${description}</p>${action}</div>`;}
function stats(){
  const s=app.data?.stats || {active:0,completed:0,bytes:0,speed:0};
  return `<div class="stats-grid">${[['正在进行',s.active,'个任务','download',''],['已归档',s.completed,'个文件','check','teal'],['本地收藏',bytes(s.bytes),'','folder','orange'],['实时速度',bytes(s.speed),'/s','cloud','blue']].map(([label,val,unit,symbol,color])=>`<div class="stat-card"><div><span class="label">${label}</span><div class="stat-number">${val}<small>${unit}</small></div></div><span class="stat-icon ${color}">${icon(symbol)}</span></div>`).join('')}</div>`;
}
function demoBanner(){return app.data?.mode==='demo'?`<div class="hint-banner"><span>${icon('info')}</span>你正在体验本地演示。随附素材可真实下载；连接 Telegram 后即可浏览你的资源。<button class="text-button" data-action="connect">连接账号 ↗</button></div>`:'';}
function render(){
  const views={media:renderMedia,tasks:renderTasks,library:renderLibrary,automation:renderAutomation,settings:renderSettings};
  $('#main').innerHTML=views[app.view]();
  $$('[data-view]').forEach(e=>e.classList.toggle('active',e.dataset.view===app.view));
  $('#breadcrumb-current').textContent={media:'资源浏览',tasks:'下载工作台',library:'本地资源库',automation:'自动归档',settings:'设置与连接'}[app.view];
  fillIcons();if(app.view==='media'){renderChats();renderCards();}
}
function renderMedia(){
  return heading('资源浏览','从喜欢的对话开始，把每一份灵感妥善收藏。',button('链接下载','links','','link')+button('批量下载','bulk','primary','plus'))+stats()+
  `<section class="panel browser-panel"><aside class="chat-pane"><div class="panel-title">我的对话 <span>${app.chats.length} 个</span></div><div class="search-box">${icon('search')}<input id="chat-search" placeholder="查找对话…" aria-label="查找对话"></div><div class="chat-list" id="chat-list"></div><p class="chat-note">${app.data?.mode==='demo'?'本地演示工作空间<br>示例频道不会读取真实账号。':'仅展示当前账号可访问的对话。<br>历史媒体按需加载。'}</p></aside><div class="media-pane"><div class="media-heading"><div><h3 id="media-chat-title">${esc(app.chat?.title || '选择一个对话')}</h3><p id="media-scan-note">${app.data?.mode==='demo'?'原创演示素材 · 保存在你的电脑':'扫描最近 200 条消息中的媒体'}</p></div><div class="search-box">${icon('search')}<input id="media-search" placeholder="搜索文件名或文字…" value="${esc(app.search)}" aria-label="搜索文件名或文字"></div></div><div class="filter-row"><div class="tabs">${['all','video','image','audio','file'].map(k=>`<button class="tab ${app.kind===k?'active':''}" data-kind="${k}">${kindName(k)}</button>`).join('')}</div><div class="layout-toggle"><button class="${app.layout==='grid'?'active':''}" data-layout="grid" aria-label="网格视图">${icon('grid')}</button><button class="${app.layout==='list'?'active':''}" data-layout="list" aria-label="列表视图">${icon('list')}</button><button data-action="refresh-media" aria-label="刷新媒体">${icon('refresh')}</button></div></div><div class="selection-bar"><label><input type="checkbox" id="select-all">全选 <span id="selected-count"></span></label><button class="text-button" data-action="download-selected">下载所选 ${icon('download')}</button></div><div id="media-cards"></div><div id="media-more"></div></div></section>`;
}
function renderChats(query=''){
  const chats=app.chats.filter(c=>c.title.toLowerCase().includes(query.toLowerCase()));
  $('#chat-list').innerHTML=chats.map(c=>`<button class="chat-item ${String(c.id)===String(app.chat?.id)?'selected':''}" data-chat="${esc(c.id)}"><span class="chat-avatar" style="--avatar-color:${esc(c.color)}">${esc(c.letter)}</span><span class="chat-info"><strong>${esc(c.title)}</strong><small>${esc(c.subtitle)}</small></span></button>`).join('') || `<div class="chat-note">${query?'没有匹配的对话':'连接账号后载入对话'}</div>`;
}
function renderCards(){
  if(!$('#media-cards')) return;
  const items=app.items.filter(i=>(app.kind==='all'||i.kind===app.kind)&&(!app.search||(i.name+' '+i.caption).toLowerCase().includes(app.search.toLowerCase())));
  if(app.loading){$('#media-cards').innerHTML='<div class="loading-line"><span class="spinner"></span>正在载入媒体…</div>';return;}
  if(!app.chat){$('#media-cards').innerHTML=empty('你的收藏，从这里开始','连接 Telegram，选择频道或群组，浏览并下载其中的媒体。','cloud',button('连接 Telegram','connect','primary','plus'));return;}
  $('#media-cards').className=app.layout==='list'?'media-list':'media-grid';
  $('#media-cards').innerHTML=items.map(item=>`<article class="media-card ${app.selected.has(item.id)?'chosen':''}"><label class="media-check"><input type="checkbox" data-select="${item.id}" aria-label="选择 ${esc(item.name)}" ${app.selected.has(item.id)?'checked':''}></label><div class="media-thumb" data-preview="${item.id}">${['image','video'].includes(item.kind)?`<img src="${esc(assetUrl(item,true))}" alt="${esc(item.name)}" loading="lazy" data-fallback>`:`<div class="media-placeholder">${icon(item.kind)}<span>${kindName(item.kind)}</span></div>`}<span class="type-tag">${item.kind==='video'?icon('play')+' '+Math.floor(item.duration/60)+':'+String(item.duration%60).padStart(2,'0'):kindName(item.kind)}</span></div><div class="card-body"><strong title="${esc(item.name)}">${esc(item.name)}</strong><div class="card-meta"><span>${bytes(item.size)}</span><span>${day(item.date)}</span></div></div><button class="card-download" data-download="${item.id}" aria-label="下载 ${esc(item.name)}">${icon('download')}</button></article>`).join('') || empty('暂时没有匹配的媒体','试试其他类型或关键词，也可以继续扫描更早的消息。','search');
  $('#selected-count').textContent=app.selected.size?'· 已选 '+app.selected.size+' 项':'';
  const all=$('#select-all');all.checked=items.length>0&&items.every(i=>app.selected.has(i.id));all.indeterminate=app.selected.size>0&&!all.checked;
  $('#media-more').innerHTML=app.nextOffset?`<div class="shortcut-note">已扫描 ${app.scanned} 条消息 · <button class="text-button" data-action="load-more">载入更早的消息</button></div>`:`<div class="shortcut-note">${items.length} 个媒体文件${app.data?.mode==='demo'?' · 本地演示素材':''}</div>`;
  $$('img[data-fallback]',$('#media-cards')).forEach(img=>img.addEventListener('error',()=>{const div=document.createElement('div');div.className='media-placeholder';div.innerHTML=icon('image')+'<span>暂无缩略图</span>';img.replaceWith(div);},{once:true}));
}
function taskRows(jobs){
  return jobs.map(job=>{const progress=job.status==='completed'?100:job.size?Math.min(100,job.downloaded/job.size*100):0;return `<tr><td><div class="file-cell"><span class="file-icon ${job.kind==='image'?'teal':''}">${icon(job.kind)}</span><div><strong title="${esc(job.name)}">${esc(job.name)}</strong><small>${esc(job.chat_title)} · ${job.source==='demo'?'本地演示':'Telegram'}</small></div></div></td><td>${bytes(job.size)}</td><td><div class="progress-label"><span>${bytes(job.downloaded)} / ${bytes(job.size)}</span><span>${Math.floor(progress)}%</span></div><div class="progress-track ${job.status==='completed'?'complete':''}"><span style="width:${progress}%"></span></div>${job.error?`<div class="error-line">${esc(job.error)}</div>`:''}</td><td><span class="status-tag ${esc(job.status)}">${labels[job.status]||job.status}</span>${job.status==='downloading'?`<small style="display:block;font-size:9px;margin-top:8px">${bytes(job.speed)}/s</small>`:''}</td><td><div class="row-actions">${job.status==='completed'?`<button class="row-action" data-open-job="${job.id}" title="打开所在文件夹">${icon('folder')}</button>`:`<button class="row-action" data-job="${job.id}" data-job-action="${['downloading','queued','resolving','waiting'].includes(job.status)?'pause':'resume'}" title="${['downloading','queued','resolving','waiting'].includes(job.status)?'暂停':'继续或重试'}">${icon(['downloading','queued','resolving','waiting'].includes(job.status)?'pause':'play')}</button><button class="row-action" data-job="${job.id}" data-job-action="cancel" title="取消任务，保留临时文件">${icon('close')}</button>`}</div></td></tr>`;}).join('');
}
function filteredJobs(){return (app.data?.jobs||[]).filter(j=>app.taskFilter==='all'||(app.taskFilter==='active'?['queued','downloading','paused','waiting'].includes(j.status):j.status===app.taskFilter));}
function renderTasks(){const jobs=filteredJobs();return heading('下载工作台','每一个任务，都有清晰的来处与进度。',button('链接下载','links','','link')+button('新建下载','bulk','primary','plus'))+stats()+demoBanner()+`<section class="panel task-panel"><div class="task-toolbar"><div class="tabs">${[['all','全部任务'],['active','进行中'],['completed','已完成'],['error','失败']].map(([id,name])=>`<button class="tab ${app.taskFilter===id?'active':''}" data-task-filter="${id}">${name}</button>`).join('')}</div><div class="actions">${button('全部暂停','pause-all','small','pause')}${button('全部继续','resume-all','small','play')}</div></div><div id="task-table">${jobs.length?`<table class="task-list"><thead><tr><th>文件 / 来源</th><th>大小</th><th>下载进度</th><th>状态</th><th>操作</th></tr></thead><tbody>${taskRows(jobs)}</tbody></table><div class="table-bottom"><span>${jobs.length} 个任务</span><span>文件校验后归档 · 临时文件保留至续传</span></div>`:empty('准备好，收下一份好内容','从资源浏览中选择媒体，或粘贴消息链接，建立你的第一个下载任务。','download',button('浏览资源','view-media','light','grid'))}</div></section>`;}
function updateTasks(){if(app.view!=='tasks')return;const jobs=filteredJobs();if(!$('.task-list')||!jobs.length){render();return;}$('.task-list tbody').innerHTML=taskRows(jobs);$('.table-bottom span').textContent=jobs.length+' 个任务';}
function renderLibrary(){const jobs=(app.data?.jobs||[]).filter(j=>j.status==='completed');return heading('本地资源库','已经保存的文件，都在这里。',button('打开下载目录','folder','','folder'))+stats()+`<section class="panel" style="padding:24px">${jobs.length?`<div class="media-grid library-grid">${jobs.map(j=>`<article class="media-card"><div class="media-thumb" data-library-preview="${j.id}">${j.kind==='image'?`<img src="${esc(fileUrl(j))}" alt="${esc(j.name)}" loading="lazy">`:j.kind==='video'?`<div class="media-placeholder">${icon('video')}<span>点击预览视频</span></div>`:`<div class="media-placeholder">${icon(j.kind)}<span>${kindName(j.kind)}</span></div>`}<span class="type-tag">已归档</span></div><div class="card-body"><strong>${esc(j.name)}</strong><div class="card-meta"><span>${bytes(j.size)}</span><span>${day(j.created)}</span></div></div><button class="card-download" data-open-job="${j.id}" aria-label="打开所在文件夹">${icon('folder')}</button></article>`).join('')}</div>`:empty('留住的内容，会在这里相遇','完成下载后，文件会自动归档到本地资源库。你可以预览图片与视频，或打开所在文件夹。','folder',button('浏览资源','view-media','light','grid'))}</section>`;}
function renderAutomation(){const rules=app.data?.rules||[];return heading('自动归档','为常看的频道设一条规则，让新内容自动入库。',button('新建规则','rule','primary','plus'))+`<div class="hint-banner"><span>${icon('clock')}</span>软件运行且 Telegram 已连接时生效。仅监听你选择的对话，按类型与关键词自动下载新媒体。</div>`+`<div class="rules-grid">${rules.map(r=>`<section class="panel rule-card"><div class="rule-heading"><h3>${esc(r.name||r.chat_title)}</h3><button class="toggle ${r.enabled?'on':''}" data-rule-toggle="${r.id}" data-enabled="${r.enabled?'0':'1'}" aria-label="${r.enabled?'暂停':'启用'}规则"></button></div><p>${esc(r.chat_title)}</p><div class="rule-tags"><span>${kindName(r.kind||'all')}</span><span>${r.keyword?'包含 '+esc(r.keyword):'全部新媒体'}</span><span>${r.enabled?'监听已启用':'已暂停'}</span></div></section>`).join('')}</div>`+(!rules.length?`<section class="panel">${empty('把重复的收藏，交给规则','选择一个已加入的对话，设置媒体类型和关键词。新消息出现时，匹配的媒体会自动进入下载队列。','spark',button('创建归档规则','rule','light','plus'))}</section>`:'');}
function renderSettings(){const s=app.data?.settings||{};const connected=app.data?.auth.state==='connected';return heading('设置与连接','一个安静、独立的本地资源工作空间。')+`<div class="setup-grid"><section class="panel settings-card"><span class="section-eyebrow">TELEGRAM CONNECTION</span><h3>你的 Telegram 账号</h3><p>使用你自己的 API 设置连接，扫码登录后开始浏览与下载。</p><div class="settings-list"><div class="settings-row"><div><strong>连接状态</strong><small>${esc(app.data?.auth.message)}</small></div><span class="tag">${connected?'已连接':'未授权'}</span></div><div class="settings-row"><div><strong>本地会话</strong><small>API Hash 通过 Windows 用户加密保存；登录密码不保存。</small></div>${icon('shield')}</div><div class="settings-row"><div><strong>网络代理</strong><small>${s.proxy_enabled?'SOCKS5 · '+esc(s.proxy_host)+':'+esc(s.proxy_port):'直连 · 可在连接设置中启用 SOCKS5 代理'}</small></div></div></div>${button(connected?'查看连接设置':'连接 Telegram','connect','primary','cloud')}${connected?button('断开连接','disconnect','','pause'):''}<div class="shortcut-note"><a href="https://my.telegram.org/apps" target="_blank" rel="noopener noreferrer">获取自己的 API ID 与 API Hash ↗</a></div></section><section class="panel settings-card"><span class="section-eyebrow">LOCAL STORAGE</span><h3>下载与归档</h3><p>队列、断点和文件保存在当前电脑，不上传到第三方存储。</p><div class="settings-list"><div class="settings-row"><div><strong>下载目录</strong><small>${esc(s.download_root)}</small></div></div><div class="settings-row"><div><strong>工作模式</strong><small>${app.data?.mode==='demo'?'本地演示 · 不读取 Telegram 对话':'Telegram · 真实对话与媒体'}</small></div><button class="text-button" data-action="toggle-mode">切换</button></div><div class="settings-row"><div><strong>任务恢复</strong><small>重新启动后，未完成的任务暂停，点击继续即可续传。</small></div><span class="tag">断点保留</span></div></div>${button('修改下载目录','directory','','folder')}${button('打开文件夹','folder','','arrow')}</section><section class="panel settings-card" style="grid-column:1/-1"><span class="section-eyebrow">BUILT FOR YOUR COLLECTION</span><h3>星港 · TG Harbor 1.0</h3><ul class="feature-list"><li>${icon('check')}对话浏览、消息链接下载、按类型 / 日期 / 关键词批量筛选</li><li>${icon('check')}本地持久队列、暂停续传、失败重试、图片与视频预览</li><li>${icon('check')}指定对话的新媒体自动归档，Telegram 访问权限与限流照常生效</li></ul><p>参考 <a href="https://tg-ff.com/v4/" target="_blank" rel="noopener noreferrer">TG-FF 的公开工作流程</a>，界面与程序独立实现。</p></section></div>`;}
async function loadChats(){
  try{const data=await api('dialogs');app.chats=data.items;if(!app.chats.some(c=>String(c.id)===String(app.chat?.id)))app.chat=app.chats[0]||null;app.items=[];app.selected.clear();render();if(app.chat)await loadMedia();}
  catch(e){app.chats=[];app.chat=null;app.items=[];render();toast(e.message,true);}
}
async function loadMedia(more=false){
  if(!app.chat)return;const req=++app.requestId;app.loading=true;renderCards();
  try{const data=await api('media?'+new URLSearchParams({chat_id:app.chat.id,offset:more?app.nextOffset:0}));if(req!==app.requestId)return;app.items=more?[...app.items,...data.items.filter(i=>!app.items.some(old=>old.id===i.id))]:data.items;app.nextOffset=data.next_offset;app.scanned=more?app.scanned+data.scanned:data.scanned;}
  catch(e){if(req===app.requestId)toast(e.message,true);}
  finally{if(req===app.requestId){app.loading=false;renderCards();}}
}
function openModal(title,content,eyebrow='NEW TASK',wide=false,type=null){app.lastFocus=document.activeElement;app.modal=type;$('#modal-title').textContent=title;$('#modal-eyebrow').textContent=eyebrow;$('#modal-content').innerHTML=content;$('.modal').classList.toggle('wide',wide);$('#modal-root').hidden=false;setTimeout(()=>{const first=$('input:not([type=checkbox]),textarea,button', $('#modal-content'));(first||$('#modal-close')).focus();},30);}
function closeModal(){app.modal=null;$('#modal-root').hidden=true;$('#modal-content').innerHTML='';app.lastFocus?.focus?.();}
function formError(message){const e=$('.inline-error');if(e){e.textContent=message;e.classList.add('show');}else toast(message,true);}
function footerActions(label='创建任务'){return `<div class="inline-error" role="alert"></div><div class="modal-actions"><button type="button" class="btn" data-action="close-modal">取消</button><button type="submit" class="btn primary">${icon('plus')}${label}</button></div>`;}
function chatOptions(){return app.chats.map(c=>`<option value="${esc(c.id)}" ${String(app.chat?.id)===String(c.id)?'selected':''}>${esc(c.title)}</option>`).join('');}
function filterFields(){return `<div class="field-row"><label class="field"><span>媒体类型</span><select name="kind">${['all','video','image','audio','file'].map(k=>`<option value="${k}">${kindName(k)}</option>`).join('')}</select></label><label class="field"><span>最大文件大小（MB）</span><input name="max_size" type="number" min="0" max="100000" value="0"><small>0 表示不限大小</small></label></div><label class="field"><span>包含关键词</span><input name="keyword" placeholder="可选：文件名或消息文字"></label>`;}
function requireConnection(){if(app.data?.auth.state==='connected')return true;toast('真实 Telegram 任务需要先连接账号。');connectModal();return false;}
function linksModal(){if(!requireConnection())return;openModal('添加消息链接',`<form id="links-form"><p class="form-note">粘贴 Telegram 消息链接，每行一条。支持公开消息和你已加入的私有对话，最多 100 条。</p><label class="field"><span>消息链接</span><textarea name="links" rows="6" placeholder="https://t.me/channel/123&#10;https://t.me/c/1234567890/456" required></textarea></label>${footerActions('加入下载队列')}</form>`);}
function bulkModal(){if(app.data.mode!=='demo'&&!requireConnection())return;openModal('批量下载',`<form id="bulk-form"><p class="form-note">扫描选定对话的近期消息，把符合条件的媒体加入队列。重复的消息会自动跳过。</p><label class="field"><span>来源对话</span><select name="chat_id" required>${chatOptions()}</select></label><label class="field"><span>扫描最近多少条消息</span><input name="limit" type="number" min="1" max="1000" value="200" required><small>扫描范围 1–1000 条，结果按筛选条件匹配。</small></label>${filterFields()}<div class="field-row"><label class="field"><span>起始日期（可选）</span><input name="date_from" type="date"></label><label class="field"><span>结束日期（可选）</span><input name="date_to" type="date"></label></div>${footerActions('扫描并创建任务')}</form>`);}
function ruleModal(){if(!requireConnection())return;openModal('新建自动归档规则',`<form id="rule-form"><p class="form-note">仅在软件运行且已登录时监听所选对话的新消息。匹配的新媒体会自动加入下载队列。</p><label class="field"><span>规则名称</span><input name="name" placeholder="例如：城市影像每日归档" required maxlength="80"></label><label class="field"><span>监听对话</span><select name="chat_id" required>${chatOptions()}</select></label>${filterFields()}${footerActions('启用归档规则')}</form>`);}
function connectModal(){const s=app.data?.settings||{};openModal('连接你的 Telegram',`<form id="connect-form"><p class="form-note">使用 <a href="https://my.telegram.org/apps" target="_blank" rel="noopener noreferrer">my.telegram.org/apps</a> 获取自己的 API 设置。填写后连接，再用手机扫码授权。</p><div class="field-row"><label class="field"><span>API ID</span><input name="api_id" inputmode="numeric" value="${esc(s.api_id)}" placeholder="填写 API ID" required autocomplete="off"></label><label class="field"><span>API Hash</span><input name="api_hash" type="password" placeholder="${s.has_api_hash?'已加密保存，留空沿用':'填写 32 位 API Hash'}" autocomplete="off" ${s.has_api_hash?'':'required'}></label></div><label class="check-field"><input type="checkbox" name="proxy_enabled" ${s.proxy_enabled?'checked':''}>使用 SOCKS5 代理</label><div class="field-row"><label class="field"><span>代理地址</span><input name="proxy_host" value="${esc(s.proxy_host||'127.0.0.1')}" required></label><label class="field"><span>代理端口</span><input name="proxy_port" type="number" min="1" max="65535" value="${s.proxy_port||7890}" required></label></div><small class="form-note" style="display:block;margin-top:17px;font-size:10px">API Hash 使用 Windows 本地加密。两步验证密码只用于本次授权，不保存。</small><div class="inline-error" role="alert"></div><div class="modal-actions"><button type="button" class="btn" data-action="close-modal">关闭</button><button type="submit" class="btn primary">${icon('cloud')}连接并显示二维码</button></div></form><div id="auth-area"></div>`,'ACCOUNT CONNECTION',false,'connect');updateAuthArea();}
function updateAuthArea(){if(app.modal!=='connect')return;const a=app.data?.auth||{};const area=$('#auth-area');if(!area)return;const signature=a.state+'|'+(a.qr||'')+'|'+a.message;if(area.dataset.signature===signature)return;area.dataset.signature=signature;
  if(a.state==='qr'){area.innerHTML=`<div class="qr-block"><img src="${a.qr}" alt="Telegram 登录二维码"><div class="qr-message">${esc(a.message)}<br>二维码会在短时间后过期。<br>${button('刷新二维码','refresh-qr','small','refresh')}</div></div>`;}
  else if(a.state==='password'){area.innerHTML=`<form id="password-form"><label class="field"><span>Telegram 两步验证密码</span><input name="password" type="password" required autocomplete="off"></label><div class="modal-actions"><button class="btn primary" type="submit">完成授权</button></div></form>`;}
  else if(a.state==='connected'){area.innerHTML=`<div class="auth-pill">${icon('check')} 已连接 · ${esc(a.user?.name||'Telegram 账号')}</div><div class="modal-actions">${button('浏览我的资源','real-mode','primary','arrow')}${button('退出账号','logout','danger')}</div>`;}
  else if(a.state!=='disconnected'){area.innerHTML=`<div class="auth-pill">${esc(a.message)}</div>${['expired','ready','error'].includes(a.state)?`<div class="modal-actions">${button('生成二维码','refresh-qr','small','refresh')}</div>`:''}`;}
  else area.innerHTML='';
}
function directoryModal(){openModal('下载目录',`<form id="directory-form"><p class="form-note">新任务保存在此目录。已有断点仍沿用原来的任务目录。</p><label class="field"><span>完整目录路径</span><input name="download_root" id="download-root-input" value="${esc(app.data.settings.download_root)}" required></label><div style="margin-top:13px">${button('选择文件夹','choose-folder','small','folder')}</div>${footerActions('保存目录')}</form>`,'LOCAL STORAGE');}
async function previewItem(id){const item=app.items.find(i=>i.id===id);if(!item)return;let content;
  if(item.source==='demo'&&item.kind==='video')content=`<video class="preview-media" src="${esc(assetUrl(item))}" controls autoplay muted playsinline></video>`;
  else if(item.kind==='image'||item.kind==='video')content=`<img class="preview-media" src="${esc(assetUrl(item,item.source!=='demo'))}" alt="${esc(item.name)}">`;
  else content=`<div class="empty small"><div class="empty-icon">${icon(item.kind)}</div><h3>${esc(item.name)}</h3><p>下载完成后，可在本地资源库或文件夹中查看。</p></div>`;
  openModal(item.name,content+`<p class="preview-caption">${esc(item.caption)}${item.source==='telegram'?'<br>当前为缩略图预览，完整原文件请下载后查看。':''}</p><div class="modal-actions"><button class="btn primary" data-download="${item.id}">${icon('download')}下载原文件</button></div>`,'MEDIA PREVIEW',true);
}
function previewJob(id){const job=app.data.jobs.find(j=>j.id===id);if(!job)return;let body=job.kind==='image'?`<img class="preview-media" src="${esc(fileUrl(job))}" alt="${esc(job.name)}">`:job.kind==='video'?`<video class="preview-media" src="${esc(fileUrl(job))}" controls autoplay muted playsinline></video>`:job.kind==='audio'?`<audio src="${esc(fileUrl(job))}" controls style="width:100%"></audio>`:empty(job.name,'此文件已保存，可在文件夹中用对应的软件打开。','file');openModal(job.name,body+`<p class="preview-caption">${bytes(job.size)} · ${esc(job.chat_title)}</p><div class="modal-actions"><button class="btn" data-open-job="${job.id}">${icon('folder')}打开所在文件夹</button></div>`,'LOCAL PREVIEW',true);}
async function download(ids){if(!ids.length){toast('请先选择要下载的媒体。');return;}try{const result=await api('selected',{chat_id:app.chat.id,ids});toast(`已加入 ${result.added} 个下载任务${result.skipped?'，跳过 '+result.skipped+' 个重复文件':''}`);await refreshState();}catch(e){toast(e.message,true);}}
async function refreshState(initial=false){
  try{const data=await api('state');const oldMode=app.data?.mode;const oldAuth=app.data?.auth.state;const oldLibrary=(app.data?.jobs||[]).filter(j=>j.status==='completed').length;app.data=data;updateHeader();updateAuthArea();
    if(initial){render();await loadChats();return;}
    if(oldMode!==data.mode || (oldAuth!=='connected'&&data.auth.state==='connected')){app.chat=null;app.chats=[];app.items=[];await loadChats();if(data.auth.state==='connected')toast('Telegram 已连接，可以浏览真实资源。');}
    else if(app.view==='tasks')updateTasks();else if(app.view==='library'&&oldLibrary!==data.stats.completed)render();
    $$('.stat-card .stat-number').forEach((e,index)=>{const s=data.stats;const values=[`${s.active}<small>个任务</small>`,`${s.completed}<small>个文件</small>`,bytes(s.bytes),`${bytes(s.speed)}<small>/s</small>`];e.innerHTML=values[index];});
  }catch(e){if(initial){$('#main').innerHTML=empty('工作空间暂时无法载入',esc(e.message),'info');}else if(!app.offline){toast('本地服务连接中断，请重新打开软件。',true);}app.offline=true;}
}
function updateHeader(){const d=app.data;const connected=d.auth.state==='connected';$('#connection-text').textContent=connected?'Telegram 已连接':'连接 Telegram';$('#connect-top').classList.toggle('connected',connected);$('#mode-badge').textContent=d.mode==='demo'?'本地演示':'Telegram';$('#mode-badge').classList.toggle('real',d.mode==='telegram');$('#queue-count').textContent=d.stats.active;$('#footer-status').innerHTML=`<i style="background:${connected?'#72b496':'#a2a6b5'}"></i>${d.mode==='demo'?'本地演示 · 示例素材可真实保存':connected?'Telegram 已连接 · 任务保存在本机':'Telegram 未连接 · 请完成授权'}`;$('#footer-path').textContent=d.settings.download_root;$('#account-button').textContent=connected?(d.auth.user?.name||'T')[0]:'H';}
async function action(name){try{switch(name){
  case 'connect':connectModal();break;case 'links':linksModal();break;case 'bulk':bulkModal();break;case 'rule':ruleModal();break;case 'directory':directoryModal();break;case 'close-modal':closeModal();break;
  case 'view-media':app.view='media';render();break;case 'refresh-media':await loadMedia();break;case 'load-more':await loadMedia(true);break;
  case 'download-selected':await download([...app.selected]);break;case 'folder':await api('open-folder',{});break;
  case 'pause-all':await api('jobs/action',{action:'pause'});await refreshState();break;case 'resume-all':await api('jobs/action',{action:'resume'});await refreshState();break;
  case 'refresh-qr':await api('qr',{});await refreshState();break;
  case 'real-mode':await api('settings',{mode:'telegram'});closeModal();await refreshState();break;
  case 'toggle-mode':if(app.data.mode==='demo'&&!requireConnection())break;await api('settings',{mode:app.data.mode==='demo'?'telegram':'demo'});await refreshState();render();break;
  case 'disconnect':await api('disconnect',{});await refreshState();render();toast('连接已断开，会话保留在本机。');break;
  case 'logout':if(confirm('退出 Telegram 账号？本地下载文件保留，重新连接需要再次扫码。')){await api('logout',{});closeModal();await refreshState();}break;
  case 'choose-folder':if(window.pywebview?.api){const folder=await window.pywebview.api.choose_folder();if(folder)$('#download-root-input').value=folder;}else toast('浏览器预览中，请直接填写完整目录路径。');break;
}}catch(e){toast(e.message,true);}}
document.addEventListener('click',async event=>{
  const target=event.target.closest('button,[data-preview],[data-library-preview]');if(!target)return;
  if(target.dataset.view){app.view=target.dataset.view;render();return;}
  if(target.dataset.action){await action(target.dataset.action);return;}
  if(target.dataset.chat!==undefined){app.chat=app.chats.find(c=>String(c.id)===target.dataset.chat);app.selected.clear();app.search='';app.nextOffset=0;app.scanned=0;render();await loadMedia();return;}
  if(target.dataset.kind){app.kind=target.dataset.kind;$$('[data-kind]').forEach(e=>e.classList.toggle('active',e===target));renderCards();return;}
  if(target.dataset.layout){app.layout=target.dataset.layout;$$('[data-layout]').forEach(e=>e.classList.toggle('active',e===target));renderCards();return;}
  if(target.dataset.preview){await previewItem(Number(target.dataset.preview));return;}
  if(target.dataset.libraryPreview){previewJob(target.dataset.libraryPreview);return;}
  if(target.dataset.download){await download([Number(target.dataset.download)]);return;}
  if(target.dataset.taskFilter){app.taskFilter=target.dataset.taskFilter;render();return;}
  try{if(target.dataset.job){await api('jobs/action',{id:target.dataset.job,action:target.dataset.jobAction});await refreshState();}
    if(target.dataset.openJob){await api('open-folder',{id:target.dataset.openJob});}
    if(target.dataset.ruleToggle){await api('rules/toggle',{id:target.dataset.ruleToggle,enabled:target.dataset.enabled==='1'});await refreshState();render();}
  }catch(e){toast(e.message,true);}
});
document.addEventListener('change',event=>{
  if(event.target.dataset.select){const id=Number(event.target.dataset.select);event.target.checked?app.selected.add(id):app.selected.delete(id);renderCards();}
  if(event.target.id==='select-all'){const items=app.items.filter(i=>(app.kind==='all'||i.kind===app.kind)&&(!app.search||(i.name+' '+i.caption).toLowerCase().includes(app.search.toLowerCase())));items.forEach(i=>event.target.checked?app.selected.add(i.id):app.selected.delete(i.id));renderCards();}
});
document.addEventListener('input',event=>{if(event.target.id==='chat-search')renderChats(event.target.value);if(event.target.id==='media-search'){app.search=event.target.value;renderCards();}});
document.addEventListener('submit',async event=>{
  event.preventDefault();const form=event.target;const data=Object.fromEntries(new FormData(form));const submit=$('[type=submit]',form);if(!submit)return;const text=submit.innerHTML;submit.disabled=true;submit.innerHTML='<span class="spinner"></span>正在处理';
  $('.inline-error',form)?.classList.remove('show');
  try{const route={'links-form':'links','bulk-form':'bulk','rule-form':'rules','connect-form':'connect','password-form':'password','directory-form':'settings'}[form.id];if(!route)return;
    if(form.id==='connect-form')data.proxy_enabled=$('[name=proxy_enabled]',form).checked;
    if(form.id==='bulk-form'&&data.date_from&&data.date_to&&data.date_from>data.date_to)throw Error('起始日期不能晚于结束日期。');
    const result=await api(route,data);
    if(form.id==='connect-form'){await refreshState();if(result.state!=='connected')await api('qr',{});await refreshState();}
    else if(form.id==='password-form'){await refreshState();}
    else{closeModal();await refreshState();if(route==='rules'||route==='settings')render();else{app.view='tasks';render();}toast(route==='settings'?'下载目录已保存':route==='rules'?'自动归档规则已启用':`已加入 ${result.added} 个任务${result.skipped?'，跳过 '+result.skipped+' 个重复文件':''}`);if(result.failures?.length)toast(result.failures.join(' '),true);}
  }catch(e){formError(e.message);}finally{if(submit.isConnected){submit.disabled=false;submit.innerHTML=text;}}
});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('#modal-root').hidden)closeModal();if(event.ctrlKey&&event.key.toLowerCase()==='k'){event.preventDefault();linksModal();}if(event.key==='Tab'&&!$('#modal-root').hidden){const focusable=$$('button,input,textarea,select,a[href]',$('.modal')).filter(e=>!e.disabled&&e.offsetParent!==null);const first=focusable[0],last=focusable.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}});
$('#modal-close').addEventListener('click',closeModal);$('.modal-backdrop').addEventListener('click',closeModal);$('#connect-top').addEventListener('click',connectModal);$('#account-button').addEventListener('click',()=>{app.view='settings';render();});$('#tip-link').addEventListener('click',linksModal);$('#folder-footer').addEventListener('click',()=>action('folder'));
fillIcons();$('#main').innerHTML='<div class="loading-line"><span class="spinner"></span>正在打开你的资源工作空间…</div>';
refreshState(true).then(()=>{setInterval(()=>{if(!app.polling){app.polling=true;refreshState().finally(()=>app.polling=false);}},1500);});
