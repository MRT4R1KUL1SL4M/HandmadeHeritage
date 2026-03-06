function $(id){ return document.getElementById(id); }

/* =========================
   Small Utilities
========================= */
const prefersReducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function safeText(el, text){
  if (!el) return;
  el.textContent = text;
}

function debounce(fn, wait=250){
  let t=null;
  return (...args)=>{
    clearTimeout(t);
    t=setTimeout(()=>fn(...args), wait);
  };
}

/* =========================
   Currency conversion (instant UI)
========================= */
const FX = {
  USD: { symbol: "$", rate: 1.0 },
  BDT: { symbol: "৳", rate: 118.0 },
  EUR: { symbol: "€", rate: 0.92 },
  GBP: { symbol: "£", rate: 0.79 },
  INR: { symbol: "₹", rate: 83.0 },
  JPY: { symbol: "¥", rate: 146.0 },
};

// Try to load live FX rates from server (cached server-side).
async function loadFxRates(){
  try{
    const res = await fetch("/api/fx", { headers: { "Accept":"application/json" } });
    if(!res.ok) return;
    const data = await res.json();
    if(!data || !data.rates) return;

    Object.keys(FX).forEach((ccy)=>{
      if (data.rates[ccy] != null && !Number.isNaN(Number(data.rates[ccy]))) {
        FX[ccy].rate = Number(data.rates[ccy]);
      }
    });
  }catch(e){
    // ignore (fallback to defaults)
  }
}


function guessAutoCurrency(){
  if (localStorage.getItem("LAM_CURRENCY_MANUAL")) return;

  let tz = "";
  try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch(e){}
  const lang = (navigator.language || "").toLowerCase();
  const isBD = tz === "Asia/Dhaka" || lang.startsWith("bn");

  localStorage.setItem("LAM_CURRENCY", isBD ? "BDT" : "USD");
}

function setCurrency(cur){
  localStorage.setItem("LAM_CURRENCY", cur);
  localStorage.setItem("LAM_CURRENCY_MANUAL", "1");
  applyCurrencyUI();
}

function formatMoney(amount){
  if (!Number.isFinite(amount)) return "0";
  if (amount >= 1000) return Math.round(amount).toString();
  return amount.toFixed(0);
}

function applyCurrencyUI(){
  const cur = localStorage.getItem("LAM_CURRENCY") || "USD";
  const cfg = FX[cur] || FX.USD;

  safeText($("currencyText"), cur);
  safeText($("currencySymbol"), cfg.symbol);

  // Universal currency conversion:
  // - Supports canonical markup: .money[data-usd] or .money[data-bdt]
  // - Also supports elements that only have data-usd/data-bdt (even if class is missing)
  // - As a last resort, can parse existing text like "৳ 1200" or "$99" on nodes with class="money"
  //   and caches the USD-base in data-base-usd to avoid re-parsing after UI updates.
  function _numFromText(t){
    const m = String(t||"").replace(/\s+/g," ").match(/(-?\d[\d,]*(?:\.\d+)?)/);
    if(!m) return NaN;
    return Number(m[1].replace(/,/g,""));
  }
  function _baseCurFromText(t){
    const s = String(t||"");
    if (s.includes("৳")) return "BDT";
    if (s.includes("€")) return "EUR";
    if (s.includes("£")) return "GBP";
    if (s.includes("₹")) return "INR";
    if (s.includes("¥")) return "JPY";
    if (s.includes("$")) return "USD";
    return null;
  }

  const nodes = new Set();
  document.querySelectorAll(".money, [data-usd], [data-bdt]").forEach(n=>nodes.add(n));

  nodes.forEach(node=>{
    try{
      let usd = NaN;

      // 1) Prefer explicit base values
      const rawUsd = node.getAttribute && node.getAttribute("data-usd");
      const rawBdt = node.getAttribute && node.getAttribute("data-bdt");

      if (rawUsd !== null && rawUsd !== undefined && rawUsd !== ""){
        const v = Number(String(rawUsd).replace(/,/g,""));
        if (Number.isFinite(v)) usd = v;
      } else if (rawBdt !== null && rawBdt !== undefined && rawBdt !== ""){
        const bdt = Number(String(rawBdt).replace(/,/g,""));
        if (Number.isFinite(bdt) && FX.BDT && Number(FX.BDT.rate) > 0) usd = (bdt / Number(FX.BDT.rate));
      }

      // 2) Cached USD base
      if (!Number.isFinite(usd)){
        const cached = node.getAttribute && node.getAttribute("data-base-usd");
        const v = Number(String(cached||"").replace(/,/g,""));
        if (Number.isFinite(v)) usd = v;
      }

      // 3) Parse from visible text (only for nodes explicitly marked as money)
      if (!Number.isFinite(usd) && node.classList && node.classList.contains("money")){
        const txt = (node.textContent || "").trim();
        const baseCur = _baseCurFromText(txt) || "BDT";
        const amt = _numFromText(txt);
        if (Number.isFinite(amt) && FX[baseCur] && Number(FX[baseCur].rate) > 0){
          usd = amt / Number(FX[baseCur].rate);
        }
      }

      if (!Number.isFinite(usd)) return;

      // Cache base USD for stability across repeated UI conversions
      if (node.setAttribute) node.setAttribute("data-base-usd", String(usd));

      const converted = usd * cfg.rate;

      const sym = node.querySelector ? node.querySelector(".sym") : null;
      const amt = node.querySelector ? node.querySelector(".amt") : null;
      if (sym) sym.textContent = cfg.symbol;
      if (amt) amt.textContent = formatMoney(converted);

      // Fallback: if markup doesn't include .sym/.amt, replace entire text
      if (!sym && !amt){
        node.textContent = cfg.symbol + formatMoney(converted);
      }
    }catch(e){
      // Never let a template-specific node break currency updates site-wide
      // (silent by design)
    }
  });
}
window.applyCurrencyUI = applyCurrencyUI;

/* =========================
   Currency dropdown (robust)
========================= */
function closeCurrency(){
  const menu = $("currencyMenu");
  const sw = $("currencySwitch");
  if (menu) menu.classList.remove("open");
  if (sw) sw.setAttribute("aria-expanded", "false");
}
function openCurrency(){
  const sw = $("currencySwitch");
  const menu = $("currencyMenu");
  if (!sw || !menu) return;

  const isOpen = menu.classList.contains("open");
  closeCurrency();
  if (isOpen) return;

  const r = sw.getBoundingClientRect();
  menu.style.left = Math.max(12, Math.min(r.left, window.innerWidth - 280)) + "px";
  menu.style.top = (r.bottom + 10) + "px";
  menu.classList.add("open");
  sw.setAttribute("aria-expanded", "true");
}
function setupCurrency(){
  const sw = $("currencySwitch");
  if (sw) sw.addEventListener("click",(e)=>{ e.stopPropagation(); openCurrencyModal(); });

  // Backward compatibility: if old dropdown exists, keep it working (but prefer modal)
  const menu = $("currencyMenu");
  if (menu) menu.addEventListener("click",(e)=>{
    const item = e.target.closest("[data-currency]");
    if (!item) return;
    setCurrency(item.dataset.currency);
    closeCurrency();
  });

  document.addEventListener("keydown",(e)=>{ if (e.key==="Escape") { closeCurrency(); closeCurrencyModal(); } });
}



/* =========================
   Premium Currency Modal
========================= */
function ensureCurrencyModal(){
  if (document.getElementById("ccyModal")) return;
  const wrap = document.createElement("div");
  wrap.id = "ccyModal";
  wrap.className = "ccy-modal";
  wrap.innerHTML = `
    <div class="ccy-backdrop" data-ccy-close="1"></div>
    <div class="ccy-panel" role="dialog" aria-modal="true" aria-label="Currency selector">
      <div class="ccy-head">
        <div>
          <div class="ccy-title">Choose currency</div>
          <div class="ccy-sub">Prices update instantly across the site.</div>
        </div>
        <button class="ccy-x" type="button" data-ccy-close="1" aria-label="Close">✕</button>
      </div>

      <div class="ccy-search">
        <input id="ccySearch" placeholder="Search (USD, BDT, EUR…)" autocomplete="off" />
      </div>

      <div class="ccy-grid" id="ccyGrid"></div>

      <div class="ccy-foot">
        <div class="ccy-note">Tip: We remember your choice on this device.</div>
        <button class="ccy-auto" type="button" id="ccyAutoBtn">Auto</button>
      </div>
    </div>
  `;
  document.body.appendChild(wrap);

  wrap.addEventListener("click", (e)=>{
    const close = e.target && e.target.getAttribute && e.target.getAttribute("data-ccy-close");
    if (close) closeCurrencyModal();
  });

  const autoBtn = document.getElementById("ccyAutoBtn");
  if (autoBtn) autoBtn.addEventListener("click", ()=>{
    localStorage.removeItem("LAM_CURRENCY_MANUAL");
    localStorage.removeItem("LAM_CURRENCY");
    guessAutoCurrency();
    applyCurrencyUI();
    toast("Currency set to Auto");
    closeCurrencyModal();
  });

  const search = document.getElementById("ccySearch");
  if (search) search.addEventListener("input", debounce(()=>renderCurrencyGrid(search.value), 80));
}

function renderCurrencyGrid(q=""){
  const grid = document.getElementById("ccyGrid");
  if (!grid) return;
  const cur = localStorage.getItem("LAM_CURRENCY") || "USD";
  const query = (q||"").trim().toUpperCase();

  const entries = Object.keys(FX).map(k=>({ code:k, symbol:FX[k].symbol, rate:FX[k].rate }));
  // Popular first
  const popular = ["BDT","USD","EUR","GBP","INR","JPY"];
  entries.sort((a,b)=>{
    const ai = popular.indexOf(a.code); const bi = popular.indexOf(b.code);
    if (ai !== -1 || bi !== -1){
      return (ai===-1?999:ai) - (bi===-1?999:bi);
    }
    return a.code.localeCompare(b.code);
  });

  grid.innerHTML = "";
  for (const e of entries){
    if (query && !(e.code.includes(query) || e.symbol.includes(query))) continue;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ccy-item" + (e.code===cur ? " active" : "");
    btn.innerHTML = `
      <div class="ccy-left">
        <div class="ccy-code">${e.code}</div>
        <div class="ccy-small">${e.symbol} • rate ${Number(e.rate).toFixed(2)}</div>
      </div>
      <div class="ccy-pill">${e.code===cur ? "Selected" : "Select"}</div>
    `;
    btn.addEventListener("click", ()=>{
      setCurrency(e.code);
      toast(`Currency set to ${e.code}`);
      closeCurrencyModal();
    });
    grid.appendChild(btn);
  }
}

function openCurrencyModal(){
  ensureCurrencyModal();
  renderCurrencyGrid("");
  const modal = document.getElementById("ccyModal");
  if (!modal) return;
  modal.classList.add("open");
  const s = document.getElementById("ccySearch");
  if (s){ s.value=""; setTimeout(()=>s.focus(), 20); }
}
function closeCurrencyModal(){
  const modal = document.getElementById("ccyModal");
  if (!modal) return;
  modal.classList.remove("open");
}

/* simple toast */
function toast(msg){
  let t = document.getElementById("hhToast");
  if(!t){
    t = document.createElement("div");
    t.id="hhToast";
    t.className="hh-toast";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(window.__toastT);
  window.__toastT = setTimeout(()=>t.classList.remove("show"), 1800);
}

/* =========================
   Search (clean) + Hotkey (Ctrl/⌘+K)
========================= */
function setupSearch(){
  const input = $("globalSearchInput");
  const btn = $("globalSearchBtn");

  const go = ()=>{
    const q = encodeURIComponent((input && input.value) || "");
    window.location.href = `/shop?q=${q}`;
  };

  if (btn) btn.addEventListener("click", go);
  if (input) input.addEventListener("keydown",(e)=>{ if (e.key==="Enter") go(); });

  // Global hotkey: Ctrl/⌘ + K focuses search
  document.addEventListener("keydown",(e)=>{
    const isMac = navigator.platform.toUpperCase().includes("MAC");
    const mod = isMac ? e.metaKey : e.ctrlKey;
    if (mod && (e.key === "k" || e.key === "K")){
      if (!input) return;
      e.preventDefault();
      input.focus();
      input.select();
    }
  });

  // tiny, local-only suggestions (no backend required)
  const SUG = ["Jamdani", "Nakshi Kantha", "Terracotta", "Jute Bag", "Handmade Jewelry", "Pottery"];
  if (input){
    const wrap = document.createElement("div");
    wrap.className = "suggest";
    wrap.setAttribute("role","listbox");
    wrap.style.display = "none";
    input.parentElement && input.parentElement.appendChild(wrap);

    const render = (q)=>{
      const v = (q||"").trim().toLowerCase();
      if (!v) { wrap.style.display="none"; wrap.innerHTML=""; return; }
      const hits = SUG.filter(s=>s.toLowerCase().includes(v)).slice(0,5);
      if (!hits.length) { wrap.style.display="none"; wrap.innerHTML=""; return; }

      wrap.innerHTML = hits.map(s=>`<button type="button" class="suggest-item">${s}</button>`).join("");
      wrap.style.display = "block";
    };

    const REC_KEY = "LAM_RECENT_SEARCHES";
    const TRENDING = ["Jamdani", "Nakshi Kantha", "Jute Bag", "Terracotta", "Brass Jewelry", "Pottery"];

    function getRecents(){
      try{ return JSON.parse(localStorage.getItem(REC_KEY) || "[]") || []; }catch(e){ return []; }
    }
    function addRecent(q){
      const v = (q||"").trim();
      if(!v) return;
      const cur = getRecents().filter(x=>x && x.toLowerCase() !== v.toLowerCase());
      cur.unshift(v);
      localStorage.setItem(REC_KEY, JSON.stringify(cur.slice(0,8)));
    }

    let activeIndex = -1;
    function setActive(i){
      const items = Array.from(wrap.querySelectorAll(".suggest-item"));
      items.forEach(el=>el.classList.remove("active"));
      if(!items.length){ activeIndex = -1; return; }
      activeIndex = Math.max(0, Math.min(i, items.length-1));
      items[activeIndex].classList.add("active");
      items[activeIndex].scrollIntoView({block:"nearest"});
    }

    function renderRecentsAndTrending(){
      const rec = getRecents();
      const chips = [
        ...(rec.length ? [`<div class="suggest-title">Recent</div>`] : []),
        ...rec.map(s=>`<button type="button" class="suggest-item">${s}</button>`),
        `<div class="suggest-title">Trending</div>`,
        ...TRENDING.map(s=>`<button type="button" class="suggest-item">${s}</button>`)
      ].join("");
      wrap.innerHTML = chips;
      wrap.style.display = "block";
      activeIndex = -1;
    }

    input.addEventListener("input", debounce(()=>{
      activeIndex = -1;
      render(input.value);
    }, 120));

    input.addEventListener("focus", ()=>{
      const v = (input.value||"").trim();
      if(!v) renderRecentsAndTrending();
    });

    input.addEventListener("keydown",(e)=>{
      const items = Array.from(wrap.querySelectorAll(".suggest-item"));
      if(!items.length || wrap.style.display === "none") return;

      if(e.key === "ArrowDown"){
        e.preventDefault();
        setActive(activeIndex + 1);
      }else if(e.key === "ArrowUp"){
        e.preventDefault();
        setActive(activeIndex - 1);
      }else if(e.key === "Enter"){
        const el = items[activeIndex];
        if(el){
          e.preventDefault();
          input.value = el.textContent || "";
          wrap.style.display="none";
          addRecent(input.value);
          go();
        }
      }else if(e.key === "Escape"){
        wrap.style.display="none";
      }
    });

    wrap.addEventListener("click",(e)=>{
      const b = e.target.closest(".suggest-item");
      if (!b) return;
      input.value = b.textContent || "";
      wrap.style.display="none";
      addRecent(input.value);
      go();
    });

    document.addEventListener("click",(e)=>{
      if (!wrap.contains(e.target) && e.target !== input){
        wrap.style.display="none";
      }
    });
  }
}

/* =========================
   Newsletter
========================= */
function setupNewsletter(){
  const email = $("newsletterEmail");
  const btn = $("newsletterBtn");
  const msg = $("newsletterMsg");
  if (!email || !btn || !msg) return;

  btn.addEventListener("click", ()=>{
    const v = (email.value || "").trim();
    if (!v || !v.includes("@")){
      msg.textContent = "Please enter a valid email / সঠিক ইমেইল দিন।";
      msg.classList.add("err");
      return;
    }
    msg.classList.remove("err");
    msg.textContent = "Subscribed • সাবস্ক্রাইব হয়েছে";
    email.value = "";
  });
}

/* =========================
   Micro-interactions (tilt on tiles)
========================= */
function setupTilt(){
  if (prefersReducedMotion) return;

  const cards = document.querySelectorAll(".tile, .pcard, .catcard, .shop-card");
  cards.forEach(card=>{
    card.addEventListener("mousemove",(e)=>{
      const r = card.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width;
      const y = (e.clientY - r.top) / r.height;
      const rx = (0.5 - y) * 6;   // rotateX
      const ry = (x - 0.5) * 8;   // rotateY
      card.style.transform = `translateY(-2px) rotateX(${rx}deg) rotateY(${ry}deg)`;
    });
    card.addEventListener("mouseleave",()=>{
      card.style.transform = "";
    });
  });
}

/* =========================
   Toast (small UX polish)
========================= */
function toast(text){
  let t = document.querySelector(".toast");
  if (!t){
    t = document.createElement("div");
    t.className = "toast";
    document.body.appendChild(t);
  }
  t.textContent = text;
  t.classList.add("show");
  clearTimeout(window.__toastT);
  window.__toastT = setTimeout(()=>t.classList.remove("show"), 2200);
}

/* =========================
   Header scroll (premium glass)
========================= */
function setupHeaderFX(){
  const hdr = document.querySelector(".hdr");
  if (!hdr) return;

  const onScroll = ()=>{
    if (window.scrollY > 8) hdr.classList.add("hdr-scrolled");
    else hdr.classList.remove("hdr-scrolled");
  };
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });
}

/* =========================
   Back to top
========================= */
function setupBackTop(){
  const btn = $("backTop");
  if (!btn) return;

  const onScroll = ()=>{
    if (window.scrollY > 420) btn.classList.add("show");
    else btn.classList.remove("show");
  };
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  btn.addEventListener("click", ()=>{
    window.scrollTo({ top: 0, behavior: prefersReducedMotion ? "auto" : "smooth" });
  });
}

/* =========================
   Boot
========================= */
document.addEventListener("DOMContentLoaded", ()=>{
  setupCurrency();
  setupSearch();
  setupNewsletter();
  setupTilt();

  setupHeaderFX();
  setupBackTop();

  guessAutoCurrency();
  applyCurrencyUI();

  // Refresh rates in background, then re-render converted amounts
  loadFxRates().then(()=>{ applyCurrencyUI(); });
});

/* =========================================================
   ADD: Home Auto Sections (Featured / Trending / Categories)
   - Nothing above is removed.
========================================================= */

function escHtml(s){
  return String(s ?? "")
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;")
    .replaceAll('"',"&quot;")
    .replaceAll("'","&#039;");
}

async function fetchJSON(url){
  const res = await fetch(url, { headers: { "Accept": "application/json" } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// Support multiple possible key names from backend
function normalizeProduct(p){
  const title = p.title ?? p.name ?? "";
  const bn = p.bn ?? p.title_bn ?? p.name_bn ?? "";
  const usd = Number(p.usd ?? p.price_usd ?? p.price ?? 0) || 0;

  const img =
    p.img ??
    p.image_url ??
    p.image ??
    "";

  const rating = Number(p.rating ?? p.avg_rating ?? 0) || 0;

  const badge =
    p.badge ??
    p.label ??
    "";

  const cat =
    p.cat ??
    p.category_slug ??
    p.category ??
    "";

  return { title, bn, usd, img, rating, badge, cat };
}

function renderProductCards(containerId, products, labelClass="gold"){
  const el = document.getElementById(containerId);
  if (!el) return;

  if (!Array.isArray(products) || products.length === 0){
    // keep fallback HTML already in page
    return;
  }

  el.innerHTML = products.map(raw=>{
    const p = normalizeProduct(raw);

    const title = escHtml(p.title);
    const bn = escHtml(p.bn);
    const img = escHtml(p.img || "https://picsum.photos/seed/hh-prod/1200/900");
    const badge = escHtml(p.badge || (p.cat ? String(p.cat).replaceAll("_"," ").replaceAll("-"," ").toUpperCase() : ""));
    const rating = (Number(p.rating || 0)).toFixed(1);

    // Currency UI expects .money[data-usd] with .sym and .amt
    const usd = Number(p.usd || 0);
    const priceHtml = `
      <span class="money" data-usd="${usd}">
        <span class="sym">$</span><span class="amt">${usd ? Math.round(usd) : 0}</span>
      </span>
    `;

    return `
      <a class="pcard" href="/shop">
        <div class="pimg" style="background-image:url('${img}');"></div>
        ${badge ? `<div class="plabel ${labelClass}">${badge}</div>` : ``}
        <div class="ptitle">${title}</div>
        <div class="ptitle bn">${bn || ""}</div>
        <div class="pmeta">
          <span class="pprice">${priceHtml}</span>
          <span class="prating">★ ${rating}</span>
        </div>
      </a>
    `;
  }).join("");

  // Make sure newly injected .money nodes get converted
  try { applyCurrencyUI(); } catch(e){}
}

function renderCategoryCards(containerId, categories){
  const el = document.getElementById(containerId);
  if (!el) return;

  if (!Array.isArray(categories) || categories.length === 0){
    return; // keep fallback categories
  }

  const top = categories.slice(0, 6);

  el.innerHTML = top.map((c, i)=>{
    const slug = escHtml(c.slug || c.category_slug || c.name || "");
    const name = escHtml(c.name || slug.replaceAll("-", " ").replaceAll("_"," ").toUpperCase());
    const seed = escHtml(slug || ("cat"+i));

    return `
      <a class="catcard" href="/shop?cat=${slug}">
        <div class="catimg" style="background-image:url('https://picsum.photos/seed/${seed}/900/700');"></div>
        <div class="catname">${name}</div>
      </a>
    `;
  }).join("");
}

async function initHomeAutoSections(){
  const hasCats = document.getElementById("categoryGrid");
  const hasFeatured = document.getElementById("featuredGrid");
  const hasTrending = document.getElementById("trendingGrid");

  // If not on home (or ids absent), do nothing
  if (!hasCats && !hasFeatured && !hasTrending) return;

  // Categories
  if (hasCats){
    try{
      const cats = await fetchJSON("/api/categories");
      renderCategoryCards("categoryGrid", cats);
    }catch(e){}
  }

  // Featured
  if (hasFeatured){
    try{
      const featured = await fetchJSON("/api/products/featured?limit=8");
      renderProductCards("featuredGrid", featured, "gold");
    }catch(e){}
  }

  // Trending
  if (hasTrending){
    try{
      const trending = await fetchJSON("/api/products/trending?limit=8");
      renderProductCards("trendingGrid", trending, "gold");
    }catch(e){}
  }
}

document.addEventListener("DOMContentLoaded", initHomeAutoSections);


/* =========================================================
   ADD: Home Hero + Best of Bangladesh images (REAL-TIME)
   - No existing code removed.
   - Requires these IDs in home.html:
     heroBestPickImg, heroTerracottaImg, heroPremiumImg
     featEditorsImg, featEcoImg, featHeritageHomeImg, featPremiumImg
   - Uses existing API:
     /api/products/by-category/<slug>?limit=1
     /api/products/trending?limit=3
========================================================= */

async function setBgImageByProduct(elId, product){
  const el = document.getElementById(elId);
  if (!el || !product) return;

  const img = product.img || product.image_url || product.image || "";
  if (!img) return;

  el.style.backgroundImage = `url('${img}')`;
}
