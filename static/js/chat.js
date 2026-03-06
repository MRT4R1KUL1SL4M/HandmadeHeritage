(function(){
  const cfg = window.__CHAT__;
  if(!cfg) return;

  const log = document.getElementById('chatLog');
  const form = document.getElementById('chatForm');
  const input = document.getElementById('chatText');
  let afterId = 0; // Better than full HTML re-render for performance

  // --- Utility: Fluid Scroll ---
  function scrollBottom(){
    if(log) {
      log.scrollTo({
        top: log.scrollHeight,
        behavior: 'smooth'
      });
    }
  }

  // --- Utility: Secure Sanitization ---
  function escapeHtml(str){
    return (str||'').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[m]));
  }

  // --- Render Engine: Elite Nodes ---
  function render(messages){
    if(!messages || messages.length === 0) return;
    
    // Purono redundant placeholder thakle muche fela
    if(log.querySelector('[style*="margin:auto"]')) log.innerHTML = '';

    messages.forEach(m => {
      // Check if message is already in view (jodi afterId use koren)
      const isMe = (m.sender_id == cfg.meId) && (m.sender_role == cfg.meRole);
      
      const node = document.createElement('div');
      node.className = `msg-node ${isMe ? 'me' : 'them'}`;
      
      // Formatting timestamp
      const timeStr = m.created_at || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

      node.innerHTML = `
        <div class="bubble">
          ${escapeHtml(m.message_text)}
        </div>
        <div class="meta-node">
          <span>${timeStr}</span>
          <span style="color:var(--c-indigo);">•</span>
          <span>${(m.status || 'delivered').toUpperCase()}</span>
        </div>
      `;
      
      log.appendChild(node);
    });
    
    scrollBottom();
  }

  // --- Sync Engine: Smart Polling ---
  let isSyncing = false;
  async function poll(){
    if(isSyncing) return;
    isSyncing = true;
    
    try {
      // Note: backend e after_id support korle optimal hoy, nahole loop delete kora lagbe
      const res = await fetch(`/api/chat/${cfg.convId}/messages`, {credentials:'same-origin'});
      const data = await res.json();
      
      if(data && data.messages){
        // Existing messages muche fela jate duplicate na hoy (full re-render mode)
        log.innerHTML = ''; 
        render(data.messages);
      }
    } catch(e) {
      console.warn("Transmission Sync Interrupted. Reconnecting...");
    } finally {
      isSyncing = false;
    }
  }

  // --- Action: Transmit Manifest ---
  form.addEventListener('submit', async (e)=>{
    e.preventDefault();
    const text = (input.value||'').trim();
    if(!text) return;
    
    input.value = '';
    const fd = new FormData();
    fd.append('text', text);
    
    try {
      // Visual feedback: Instant rendering of 'sending' state optional
      await fetch(`/api/chat/${cfg.convId}/send`, {
        method:'POST', 
        body:fd, 
        credentials:'same-origin'
      });
      await poll();
    } catch(e) {
      alert("Critical: Manifest Transmission Failure.");
    }
  });

  // --- Lifecycle: Precision Intervals ---
  scrollBottom();
  // Standard sync cycle
  setInterval(poll, 2500);
  
  // Initial sync call
  poll();
})();