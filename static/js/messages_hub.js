(function(){
  function qs(sel){ return document.querySelector(sel); }
  function qsa(sel){ return Array.from(document.querySelectorAll(sel)); }

  const state = {
    threads: [],
    activeId: null,
    viewerRole: null,
    tab: null
  };

  async function jsonFetch(url, opts){
    opts = opts || {};
    // Ensure session cookies are included for same-origin API calls.
    // Without this, some deployments may not send the session cookie and the API may return 401.
    if(!opts.credentials) opts.credentials = 'same-origin';
    const res = await fetch(url, opts);
    const ct = res.headers.get('content-type') || '';
    let data = null;
    if(ct.includes('application/json')){
      data = await res.json();
    } else {
      data = await res.text();
    }
    if(!res.ok){
      const msg = (data && data.error) ? data.error : ('HTTP '+res.status);
      throw new Error(msg);
    }
    return data;
  }


  function initials(name){
    name = (name || '').trim();
    if(!name) return '';
    const parts = name.split(/\s+/).filter(Boolean);
    const first = parts[0] ? parts[0][0] : '';
    const last  = parts.length>1 ? parts[parts.length-1][0] : (parts[0][1] || '');
    return (first + last).toUpperCase();
  }

  function colorKey(s){
    s = String(s||'');
    let h=0;
    for(let i=0;i<s.length;i++){ h = (h*31 + s.charCodeAt(i)) >>> 0; }
    return h;
  }

  function isMe(msg){
    const role = state.viewerRole || '';
    const meId = window.__HH_VIEWER_ID || 0;
    return (msg.sender_role === role && Number(msg.sender_id) === Number(meId)) ||
      ((role === 'superadmin' || role === 'admin') && msg.sender_role === 'admin' && Number(msg.sender_id) === Number(meId));
  }

  function renderThreads(){
    const box = qs('#hhThreads');
    if(!box) return;
    box.innerHTML = '';
    state.threads.forEach(t => {
      const item = document.createElement('div');
      item.className = 'hh-msg-item' + (state.activeId === t.id ? ' active' : '');
      item.dataset.id = t.id;
      const pill = t.unread > 0 ? `<span class="hh-pill">${t.unread}</span>` : '';
      item.innerHTML = `
        <div class="hh-row">
          <div class="hh-avatar" data-k="${colorKey(t.title||t.subtitle||t.type||t.id)}">${escapeHtml(initials(t.title||'Chat'))}</div>
          <div class="hh-col">
            <div class="hh-msg-title">
              <span>${escapeHtml(t.title || 'Chat')}</span>
              ${pill}
            </div>
            <div class="hh-msg-sub">${escapeHtml(t.subtitle || (t.type || ''))}</div>
            <div class="hh-msg-preview">${escapeHtml(t.last_message || '')}</div>
          </div>
        </div>
      `;
      item.addEventListener('click', () => openThread(t.id));
      box.appendChild(item);
    });
  }

  function renderHeader(meta){
    const t = qs('#hhChatTitle');
    const s = qs('#hhChatSub');
    if(!t || !s) return;
    t.textContent = meta.title || 'Messages';
    s.textContent = meta.subtitle || '';
  }

  function renderMessages(messages){
    const body = qs('#hhChatBody');
    if(!body) return;
    body.innerHTML = '';
    messages.forEach(m => {
      const wrap = document.createElement('div');
      const me = isMe(m);
      wrap.className = 'hh-bubble' + (me ? ' me' : '');
      wrap.innerHTML = `
        <div>${escapeHtml(m.text || '')}</div>
        <div class="hh-bubble-meta">${escapeHtml(m.created_at || '')}</div>
      `;
      body.appendChild(wrap);
    });
    body.scrollTop = body.scrollHeight;
  }

  async function loadThreads(){
    const url = state.tab ? `/api/messages/threads?tab=${encodeURIComponent(state.tab)}` : '/api/messages/threads';
    const data = await jsonFetch(url);
    state.threads = data.threads || [];
    renderThreads();

    if(state.activeId){
      const found = state.threads.find(x => x.id === state.activeId);
      if(found) renderHeader(found);
    }
  }

  async function openThread(id){
    state.activeId = id;
    try{ localStorage.setItem("HH_LAST_CONV", String(id)); }catch(e){}
    renderThreads();
    const meta = state.threads.find(x => x.id === id) || {};
    renderHeader(meta);

    const data = await jsonFetch(`/api/messages/thread/${id}`);
    renderMessages(data.messages || []);

    // read-only enforcement (superadmin buyer<->seller)
    const roEl = qs('#hhReadOnly');
    const inputEl = qs('#hhMsgInput');
    const sendEl = qs('#hhSendBtn');
    const isReadOnly = ((state.viewerRole === 'superadmin' || state.viewerRole === 'admin') && (data.type === 'buyer_seller' || data.type === 'order'));
    if(roEl) roEl.style.display = isReadOnly ? 'block' : 'none';
    if(inputEl) inputEl.disabled = isReadOnly;
    if(sendEl) sendEl.disabled = isReadOnly;

    // superadmin meta (buyer/seller identities)
    const metaEl = qs('#hhSuperMeta');
    if(metaEl){
      if(data.meta && data.meta.buyer && data.meta.seller){
        const b = data.meta.buyer;
        const s = data.meta.seller;
        metaEl.innerHTML = `<div><b>Buyer</b>: ${escapeHtml(b.name||'')} • ${escapeHtml(b.email||'')} • ID: ${escapeHtml(b.user_id||'')}</div>` +
                          `<div><b>Seller</b>: ${escapeHtml(s.name||'')} • ${escapeHtml(s.email||'')} • ID: ${escapeHtml(s.user_id||'')}</div>`;
      } else {
        metaEl.innerHTML = '';
      }
    }

    // refresh threads to clear unread
    loadThreads().catch(()=>{});
    // refresh badge
    if(window.hhRefreshMsgBadge) window.hhRefreshMsgBadge();
  }

  async function sendMessage(){
    const input = qs('#hhMsgInput');
    if(!input) return;
    const text = (input.value || '').trim();
    if(!text || !state.activeId) return;

    input.value = '';
    try{
      await jsonFetch(`/api/messages/thread/${state.activeId}/send`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({text})
      });
      await openThread(state.activeId);
    } catch(err){
      alert('Send failed: '+ err.message);
      input.value = text;
    }
  }

  function bindSend(){
    const btn = qs('#hhSendBtn');
    const input = qs('#hhMsgInput');
    if(btn) btn.addEventListener('click', sendMessage);
    if(input) input.addEventListener('keydown', (e)=>{
      if(e.key === 'Enter'){
        e.preventDefault();
        sendMessage();
      }
    });
  }

  async function maybeAutoStart(){
    const start = window.__HH_START || '';
    const sellerId = Number(window.__HH_SELLER_ID || 0);
    const orderCode = window.__HH_ORDER_CODE || '';
    const openConv = Number(window.__HH_OPEN_CONV || 0);

    if(openConv > 0){
      state.activeId = openConv;
      return;
    }

    if(start === 'seller' && sellerId > 0){
      const d = await jsonFetch('/api/messages/start', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({kind:'seller', seller_id: sellerId})
      });
      state.activeId = Number(d.conversation_id || 0) || null;
      return;
    }

    if(start === 'support'){
      const d = await jsonFetch('/api/messages/start', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({kind:'support'})
      });
      state.activeId = Number(d.conversation_id || 0) || null;
      return;
    }

    if(start === 'order' && orderCode && sellerId > 0){
      const d = await jsonFetch('/api/messages/start', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({kind:'order', order_code: orderCode, seller_id: sellerId})
      });
      state.activeId = Number(d.conversation_id || 0) || null;
      return;
    }

    // If nothing explicitly requested, reopen last active conversation for this browser
    try{
      const last = Number(localStorage.getItem("HH_LAST_CONV") || 0);
      if(!state.activeId && last > 0) state.activeId = last;
    }catch(e){}
  }

  function escapeHtml(s){
    s = (s === null || s === undefined) ? '' : String(s);
    return s.replace(/[&<>"']/g, function(c){
      return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]);
    });
  }

  async function init(){
    const root = qs('[data-hh-messages-hub="1"]');
    if(!root) return;

    state.viewerRole = window.__HH_VIEWER_ROLE || '';
    state.tab = window.__HH_TAB || null;

    bindSend();
    await maybeAutoStart();
    await loadThreads();

    if(state.activeId){
      await openThread(state.activeId);
    } else if(state.threads.length){
      await openThread(state.threads[0].id);
    }

    // light polling for new messages/unreads
    setInterval(() => {
      loadThreads().catch(()=>{});
    }, 15000);
  }

  document.addEventListener('DOMContentLoaded', init);
})();
