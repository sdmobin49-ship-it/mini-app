/* Spider VPN Mini App — vanilla JS، بدون build */
(() => {
'use strict';
const tg = window.Telegram && window.Telegram.WebApp;
const $ = (s, r = document) => r.querySelector(s);
const S = { token: null, haptic: localStorage.getItem('haptic') !== '0', busy: false };

// ───── ابزارها ─────
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (n) => Number(n).toLocaleString('en-US');
const toman = (n) => `${num(n)} <small>تومان</small>`;
const gb = (b) => b == null ? '—' : b >= 1073741824 ? (b / 1073741824).toFixed(2) + ' GB' : (b / 1048576).toFixed(1) + ' MB';
const jd = (ts) => ts ? new Intl.DateTimeFormat('fa-IR-u-ca-persian-nu-latn', { year: 'numeric', month: 'long', day: 'numeric' }).format(new Date(ts * 1000)) : '—';
const jdt = (ts) => ts ? new Intl.DateTimeFormat('fa-IR-u-ca-persian-nu-latn', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(ts * 1000)) : '—';
const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now() + '-' + Math.random().toString(16).slice(2)).replace(/[^A-Za-z0-9_-]/g, '');
const buzz = (t = 'light') => { if (S.haptic && tg && tg.HapticFeedback) try { tg.HapticFeedback.impactOccurred(t); } catch (e) {} };
const STATUS = { active: ['فعال', 'ok'], expired: ['منقضی', 'bad'], limited: ['حجم تمام شده', 'bad'], disabled: ['غیرفعال', 'bad'], on_hold: ['در انتظار', 'warn'], unknown: ['نامشخص', 'warn'] };
const TYPE_ICON = { cdn: '🟢', tunnel: '⚡️', unlimited: '♾️' };

function toast(msg, err) {
  const t = $('#toast'); t.textContent = msg; t.className = 'toast show' + (err ? ' err' : '');
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.className = 'toast'), 3200);
}
class ApiErr extends Error { constructor(code, msg, status) { super(msg); this.code = code; this.status = status; } }

// ───── API ─────
async function login() {
  const initData = tg && tg.initData;
  if (!initData) throw new ApiErr('no_telegram', 'این صفحه فقط داخل تلگرام کار می‌کند.', 0);
  const r = await raw('/api/v1/auth/telegram', { method: 'POST', body: { init_data: initData } }, false);
  S.token = r.token; return r;
}
async function raw(path, o = {}, auth = true) {
  const h = { ...(o.headers || {}) };
  let body;
  if (o.form) body = o.form; else if (o.body) { body = JSON.stringify(o.body); h['Content-Type'] = 'application/json'; }
  if (auth && S.token) h.Authorization = 'Bearer ' + S.token;
  let res;
  try { res = await fetch(path, { method: o.method || 'GET', headers: h, body }); }
  catch (e) { throw new ApiErr('network', 'ارتباط با سرور برقرار نشد؛ اینترنت را بررسی کن.', 0); }
  let j = null; try { j = await res.json(); } catch (e) {}
  if (!res.ok || !j || !j.ok) {
    const er = (j && j.error) || {};
    throw new ApiErr(er.code || 'http_' + res.status, er.message || 'خطای ناشناخته', res.status);
  }
  return j.data;
}
async function api(path, o = {}) {
  try { return await raw(path, o); }
  catch (e) {
    if (e.status === 401 && e.code !== 'no_telegram') { await login(); return raw(path, o); }   // نشست منقضی → ورود مجدد خودکار
    throw e;
  }
}
const fail = (e) => { toast(e.message || 'خطا', true); if (e.code !== 'network') buzz('heavy'); };

// ───── UI پایه ─────
const view = $('#view');
const skeleton = (n = 3) => view.innerHTML = Array.from({ length: n }, () => '<div class="sk"></div>').join('');
function header(name, balance) {
  $('#top').innerHTML = `<div class="avatar">${esc((name || 'S').trim()[0] || 'S')}</div>
    <div class="who"><b>${esc(name || 'کاربر')}</b><small>Spider VPN</small></div>
    ${balance != null ? `<a href="#/account" class="chip">💰 <span class="ltr">${num(balance)}</span> ت</a>` : ''}`;
}
function sheet(html) {
  closeSheet();
  const root = $('#sheet-root');
  root.innerHTML = `<div class="back"></div><div class="sheet"><div class="grab"></div>${html}</div>`;
  $('.back', root).onclick = closeSheet;
  return $('.sheet', root);
}
const closeSheet = () => { $('#sheet-root').innerHTML = ''; };
function copy(text) {
  const done = () => { toast('کپی شد ✅'); buzz('light'); };
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, () => fallback());
  else fallback();
  function fallback() { const t = document.createElement('textarea'); t.value = text; document.body.appendChild(t); t.select(); try { document.execCommand('copy'); done(); } catch (e) { toast('کپی نشد', true); } t.remove(); }
}
async function busy(btn, fn) {          // جلوگیری از کلیک تکراری روی دکمه‌های حساس
  if (S.busy) return; S.busy = true; const t = btn.textContent; btn.disabled = true; btn.textContent = 'کمی صبر کن…';
  try { return await fn(); } catch (e) { fail(e); } finally { S.busy = false; btn.disabled = false; btn.textContent = t; }
}
function usageBlock(u) {
  if (!u || !u.available) return '<div class="mut small">اطلاعات مصرف فعلاً در دسترس نیست.</div>';
  const unl = u.limit_bytes == null;
  const pct = unl ? 100 : Math.min(100, Math.round(u.used_bytes / u.limit_bytes * 100));
  return `<div class="bar ${unl ? 'inf' : pct >= 90 ? 'hot' : ''}"><i style="width:${pct}%"></i></div>
    <div class="row sp small"><span>مصرف: <b class="ltr">${gb(u.used_bytes)}</b></span>
    <span class="mut">${unl ? '∞ نامحدود' : 'باقی‌مانده: <b class="ltr">' + gb(u.remaining_bytes) + '</b>'}</span></div>
    ${u.stale ? `<div class="small" style="color:var(--warn)">⚠️ پنل پاسخ نداد؛ آخرین اطلاعات ذخیره‌شده (${jdt(u.fetched_at)})</div>` : `<div class="small mut">به‌روزرسانی: ${jdt(u.fetched_at)}</div>`}`;
}
function serviceCard(s) {
  const u = s.usage || {}; const st = STATUS[u.status] || STATUS.unknown;
  return `<a class="card" href="#/service/${s.id}" style="display:block">
    <div class="row sp"><div><b>${TYPE_ICON[s.service_type] || ''} ${esc(s.plan_name)}</b><div class="small mut">${esc(s.type_title)}</div></div>
    <span class="chip ${st[1]}">${st[0]}</span></div>
    ${u.available ? `<div class="small mut" style="margin-top:6px">${u.days_left != null ? `${u.days_left} روز تا انقضا • ` : ''}${u.expire_ts ? jd(u.expire_ts) : 'بدون انقضا'}</div>` : ''}
    ${s.usage ? usageBlock(u) : ''}</a>`;
}
const empty = (ic, t, btn) => `<div class="card empty"><div class="ic">${ic}</div><p class="mut">${t}</p>${btn || ''}</div>`;

// ───── صفحات ─────
async function pageHome() {
  skeleton(3);
  const d = await api('/api/v1/dashboard');
  header(d.user.name, d.balance);
  const p = d.primary_service;
  let h = `<div class="card hero"><div class="small mut">موجودی کیف پول</div><div class="big ltr" style="text-align:right">${num(d.balance)} <small style="font-size:14px">تومان</small></div>
    <div class="grid2" style="margin-top:12px"><div><div class="small mut">سرویس فعال</div><b>${d.services_active}</b> <span class="mut small">از ${d.services_total}</span></div>
    <div><div class="small mut">سفارش در انتظار</div><b>${d.pending_orders}</b></div></div></div>`;
  h += d.alerts.map((a) => {
    const m = { expiring: `⏰ سرویست ${a.days_left} روز دیگر منقضی می‌شود.`, expired: '⛔️ یکی از سرویس‌هایت منقضی شده.', limited: '⛔️ حجم یکی از سرویس‌هایت تمام شده.', disabled: '⛔️ یکی از سرویس‌هایت غیرفعال است.', low_data: '📉 حجم باقی‌مانده یکی از سرویس‌هایت کم است.' }[a.type];
    return `<a class="card" href="#/service/${a.service_id}" style="display:block;border-color:rgba(251,191,36,.45)">${m}</a>`;
  }).join('');
  if (!p) h += empty('🕸', 'هنوز سرویسی نداری.', '<a class="btn" href="#/shop">خرید اولین سرویس</a>');
  else h += `<h2>سرویس اصلی</h2>${serviceCard(p)}
    <div class="grid2"><a class="btn ghost" href="#/service/${p.id}">جزئیات</a><button class="btn" id="cfg">دریافت کانفیگ</button></div>`;
  h += `<div style="margin-top:12px"><a class="btn block ok" href="#/shop">🛒 خرید سرویس جدید</a></div>`;
  view.innerHTML = h;
  if (p) $('#cfg').onclick = (e) => showConfig(p.id, e.target);
}

async function showConfig(id, btn) {
  await busy(btn, async () => {
    const c = await api(`/api/v1/services/${id}/config`, { method: 'POST' });
    const s = sheet(`<h3>لینک اشتراک</h3><div class="code" id="sub">${esc(c.subscription_url)}</div>
      <div class="grid2" style="margin-top:10px"><button class="btn" id="cp">کپی لینک</button><button class="btn ghost" id="cl">بستن</button></div>
      <p class="small mut">این لینک را در کانال/گروه یا پیام‌رسان‌های ایرانی به اشتراک نگذار.</p>
      ${c.links && c.links.length ? `<details><summary>کانفیگ‌های تکی (${c.links.length})</summary>${c.links.map((l, i) => `<div class="code" style="margin:6px 0" data-l="${i}">${esc(l)}</div>`).join('')}</details>` : ''}`);
    $('#cp', s).onclick = () => copy(c.subscription_url); $('#cl', s).onclick = closeSheet;
    s.querySelectorAll('[data-l]').forEach((el) => (el.onclick = () => copy(c.links[el.dataset.l])));
  });
}

let PLANS = null;
async function pageShop() {
  skeleton(3);
  if (!PLANS) PLANS = await api('/api/v1/plans');
  const types = PLANS.types; let cur = sessionStorage.getItem('shopType') || types[0].id;
  const draw = () => {
    const list = PLANS.plans.filter((p) => p.service_type === cur);
    view.innerHTML = `<h2>خرید سرویس</h2>
      <div class="seg">${types.map((t) => `<button data-t="${t.id}" class="${t.id === cur ? 'on' : ''}">${TYPE_ICON[t.id]} ${esc(t.kind === 'unlimited' ? 'نامحدود' : t.id === 'cdn' ? 'حجمی CDN' : 'حجمی Tunnel')}</button>`).join('')}</div>
      <p class="small mut">${esc(types.find((t) => t.id === cur).title)} • پروتکل: <b class="ltr">${esc(types.find((t) => t.id === cur).protocols.join(' / '))}</b></p>
      ${list.length ? list.map((p) => `<div class="card plan" data-p="${esc(p.id)}"><div class="row sp"><div><b>${esc(p.name)}</b>
        <div class="small mut">${p.data_limit_gb ? p.data_limit_gb + ' گیگابایت' : 'ترافیک نامحدود'} • ${p.duration_days} روز${p.users ? ' • ' + p.users + ' کاربر' : ''}</div></div>
        <div class="price">${toman(p.price)}</div></div></div>`).join('') : empty('📭', 'فعلاً پلنی برای این نوع تنظیم نشده است.')}`;
    view.querySelectorAll('.seg button').forEach((b) => (b.onclick = () => { cur = b.dataset.t; sessionStorage.setItem('shopType', cur); draw(); }));
    view.querySelectorAll('.plan').forEach((c) => (c.onclick = () => { buzz(); const p = list.find((x) => x.id === c.dataset.p); checkout({ kind: 'purchase', service_type: p.service_type, plan_id: p.id, title: p.name, base: p.price }); }));
  };
  draw();
}

const RULES = '🚫 اشتراک‌گذاری لینک یا کانفیگ در کانال/گروه عمومی، اپ‌های ایرانی (بله، ایتا، روبیکا) یا SMS، و فروش/واگذاری سرویس ممنوع است. تبعات: بن کامل و دائمی بدون بازگشت وجه.';

// ───── خرید / تمدید / شارژ ─────
async function checkout(it) {
  const me = await api('/api/v1/me').catch(() => ({ balance: 0 }));
  let q = { amount: it.base, discount_percent: 0, discount_code: null };
  const s = sheet('');
  const draw = () => {
    const canBal = it.kind !== 'topup' && me.balance >= q.amount;
    s.innerHTML = `<div class="grab"></div><h3>${esc(it.title)}</h3>
      <div class="card" style="margin:8px 0"><div class="kv"><span class="mut">قیمت</span><span>${toman(it.base)}</span></div>
      ${q.discount_percent ? `<div class="kv"><span class="mut">تخفیف (${esc(q.discount_code)})</span><span style="color:var(--ok)">${q.discount_percent}٪</span></div>` : ''}
      <div class="kv"><b>مبلغ نهایی</b><b>${toman(q.amount)}</b></div>
      ${it.kind !== 'topup' ? `<div class="kv"><span class="mut">موجودی شما</span><span>${toman(me.balance)}</span></div>` : ''}</div>
      ${it.kind !== 'topup' ? `<div class="row"><input id="dc" class="ltr" placeholder="کد تخفیف (اختیاری)" value="${esc(q.discount_code || '')}"><button class="btn ghost sm" id="dcb">اعمال</button></div>
      <label class="row" style="gap:8px;margin-top:12px"><input type="checkbox" id="rules" style="width:20px;height:20px"> <span class="small">قوانین استفاده را می‌پذیرم: ${esc(RULES)}</span></label>` : ''}
      <label>روش پرداخت</label>
      <div class="seg" id="pm"><button data-m="balance" class="${canBal ? 'on' : ''}" ${canBal ? '' : 'disabled style="opacity:.4"'}>💰 کیف پول</button><button data-m="card" class="${canBal ? '' : 'on'}" ${it.kind === 'topup' ? 'disabled' : ''}>💳 کارت‌به‌کارت</button></div>
      <button class="btn block" id="go">ادامه</button>`;
    let method = canBal && it.kind !== 'topup' ? 'balance' : 'card';
    s.querySelectorAll('#pm button').forEach((b) => (b.onclick = () => { if (b.disabled) return; method = b.dataset.m; s.querySelectorAll('#pm button').forEach((x) => x.classList.toggle('on', x === b)); }));
    const dcb = $('#dcb', s);
    if (dcb) dcb.onclick = () => busy(dcb, async () => {
      const code = $('#dc', s).value.trim();
      q = code ? await api('/api/v1/quote', { method: 'POST', body: { ...payload(it), discount_code: code } }) : { amount: it.base, discount_percent: 0, discount_code: null };
      toast(code ? 'کد تخفیف اعمال شد ✅' : 'کد تخفیف حذف شد'); draw();
    });
    $('#go', s).onclick = (e) => busy(e.target, async () => {
      if (it.kind !== 'topup' && !$('#rules', s).checked) return toast('برای ادامه باید قوانین را بپذیری.', true);
      const order = await createOrder(it, q);
      if (method === 'balance') { const o = await api(`/api/v1/orders/${order.id}/payment`, { method: 'POST', body: { method: 'balance' } }); closeSheet(); location.hash = `#/order/${o.id}`; }
      else cardStep(order);
    });
  };
  draw();
}
const payload = (it) => it.kind === 'topup' ? { kind: 'topup', amount: it.base } : it.kind === 'renew' ? { kind: 'renew', service_id: it.service_id, plan_id: it.plan_id } : { kind: 'purchase', service_type: it.service_type, plan_id: it.plan_id };
async function createOrder(it, q) {
  // کلید idempotency پایدار برای یک «قصد» مشخص: کلیک/تلاش مجدد، سفارش تکراری نمی‌سازد
  const sig = 'idem:' + JSON.stringify([payload(it), q.discount_code]); let key = sessionStorage.getItem(sig);
  if (!key) { key = uuid(); sessionStorage.setItem(sig, key); }
  const o = await api('/api/v1/orders', { method: 'POST', body: { ...payload(it), discount_code: q.discount_code }, headers: { 'Idempotency-Key': key } });
  return o;
}
function cardStep(order) {
  const s = sheet(`<h3>پرداخت کارت‌به‌کارت</h3>
    <div class="card" style="margin:8px 0"><div class="kv"><span class="mut">مبلغ</span><b>${toman(order.amount)}</b></div>
    <div class="kv"><span class="mut">شماره کارت</span><b class="ltr" id="cn">${esc(order.card.number)}</b></div>
    <div class="kv"><span class="mut">به نام</span><b>${esc(order.card.owner)}</b></div></div>
    <button class="btn ghost block" id="cpc">کپی شماره کارت</button>
    <label>تصویر رسید واریز</label><input type="file" id="rc" accept="image/jpeg,image/png,image/webp">
    <p class="small mut">بعد از ارسال رسید، سفارش پس از تأیید ادمین فعال می‌شود.</p>
    <button class="btn block ok" id="sd">ارسال رسید</button>`);
  $('#cpc', s).onclick = () => copy(order.card.number.replace(/\D/g, ''));
  $('#sd', s).onclick = (e) => busy(e.target, async () => {
    const f = $('#rc', s).files[0];
    if (!f) return toast('تصویر رسید را انتخاب کن.', true);
    if (f.size > 5 * 1024 * 1024) return toast('حجم تصویر باید کمتر از ۵ مگابایت باشد.', true);
    const fd = new FormData(); fd.append('method', 'card'); fd.append('receipt', f);
    const o = await api(`/api/v1/orders/${order.id}/payment`, { method: 'POST', form: fd });
    closeSheet(); toast('رسید ارسال شد ✅'); location.hash = `#/order/${o.id}`;
  });
}

let poll = null;
async function pageOrder(id) {
  skeleton(2);
  const draw = (o) => {
    const st = o.status, pay = o.payment_status;
    const stage = st === 'completed' ? 3 : (st === 'paid' || st === 'provisioning' || st === 'failed') ? 2 : pay === 'awaiting_review' ? 1 : 0;
    const bad = st === 'rejected' || st === 'refunded' || st === 'cancelled';
    const steps = [['ثبت سفارش', 0], ['در انتظار تأیید پرداخت', 1], ['فعال‌سازی سرویس', 2], ['تکمیل شد', 3]]
      .map(([t, i]) => `<div class="step ${i < stage || stage === 3 ? 'done' : i === stage && !bad ? 'on' : ''}"><span class="dot"></span>${t}</div>`).join('');
    const title = bad ? (st === 'refunded' ? '↩️ مبلغ به کیف پول برگشت' : '❌ سفارش رد شد') : st === 'completed' ? '✅ انجام شد' : st === 'failed' ? '⏳ فعال‌سازی با تأخیر' : st === 'pending_payment' && pay === 'unpaid' ? '💳 در انتظار پرداخت' : '⏳ در حال پردازش';
    view.innerHTML = `<h2>${title}</h2><div class="card"><div class="kv"><span class="mut">سفارش</span><span>${esc(o.plan_name || (o.kind === 'topup' ? 'شارژ کیف پول' : ''))}</span></div>
      <div class="kv"><span class="mut">مبلغ</span><b>${toman(o.amount)}</b></div>${bad ? '' : `<div class="steps">${steps}</div>`}
      ${o.error ? `<p class="small" style="color:var(--warn)">${esc(o.error)}</p>` : ''}
      ${st === 'pending_payment' && pay === 'awaiting_review' ? '<p class="small mut">رسید دریافت شد؛ منتظر تأیید ادمین هستیم.</p>' : ''}</div>
      ${st === 'completed' && o.service_id ? `<a class="btn block" href="#/service/${o.service_id}">مشاهده سرویس و کانفیگ</a>` : ''}
      ${st === 'completed' && o.kind === 'topup' ? '<a class="btn block" href="#/account">بازگشت به حساب</a>' : ''}
      ${st === 'pending_payment' && pay === 'unpaid' ? '<button class="btn block" id="res">ادامه پرداخت</button>' : ''}
      ${bad ? '<a class="btn ghost block" href="#/support">پشتیبانی</a>' : ''}`;
    const r = $('#res'); if (r) r.onclick = () => cardStep(o);
    return !['completed', 'rejected', 'refunded', 'cancelled'].includes(st) && !(st === 'pending_payment' && pay === 'unpaid');
  };
  const tick = async () => {
    try { const o = await api(`/api/v1/orders/${id}`); if (draw(o)) poll = setTimeout(tick, 3000); }
    catch (e) { fail(e); if (e.code === 'network') poll = setTimeout(tick, 5000); }
  };
  await tick();
}

async function pageServices() {
  skeleton(3);
  const d = await api('/api/v1/services?usage=1&limit=50');
  view.innerHTML = `<h2>سرویس‌های من</h2>` + (d.items.length ? d.items.map(serviceCard).join('') : empty('🕸', 'هنوز سرویسی نداری.', '<a class="btn" href="#/shop">خرید سرویس</a>'));
}

async function pageService(id) {
  skeleton(3);
  const [s, orders] = await Promise.all([api(`/api/v1/services/${id}`), api('/api/v1/orders?limit=50')]);
  const u = s.usage, st = STATUS[u.status] || STATUS.unknown;
  const mine = orders.items.filter((o) => String(o.service_id) === String(id));
  view.innerHTML = `<h2>${TYPE_ICON[s.service_type]} ${esc(s.plan_name)}</h2><div class="card">
    <div class="row sp"><span class="mut">وضعیت</span><span class="chip ${st[1]}">${st[0]}</span></div>${usageBlock(u)}
    <div class="kv"><span class="mut">نوع</span><span>${esc(s.type_title)}</span></div>
    <div class="kv"><span class="mut">انقضا</span><span>${u.expire_ts ? jd(u.expire_ts) + (u.days_left != null ? ` (${u.days_left} روز)` : '') : 'بدون انقضا'}</span></div>
    <div class="kv"><span class="mut">پروتکل</span><span class="ltr">${esc((u.protocols || []).join(' / ') || '—')}</span></div>
    <div class="kv"><span class="mut">شناسه</span><span class="ltr">${esc(s.panel_username)}</span></div></div>
    <div class="grid2"><button class="btn" id="cfg">دریافت کانفیگ</button><button class="btn ghost" id="rn">تمدید</button></div>
    <button class="btn ghost block sm" id="rf" style="margin-top:10px">🔄 به‌روزرسانی مصرف</button>
    ${mine.length ? `<h2>سفارش‌های این سرویس</h2>${mine.map(orderRow).join('')}` : ''}`;
  $('#cfg').onclick = (e) => showConfig(id, e.target);
  $('#rf').onclick = (e) => busy(e.target, async () => { await api(`/api/v1/services/${id}/usage?fresh=1`); pageService(id); });
  $('#rn').onclick = (e) => busy(e.target, async () => {
    const r = await api(`/api/v1/services/${id}/renew-plans`);
    const sh = sheet(`<h3>انتخاب پلن تمدید</h3>${r.plans.map((p) => `<div class="card plan" data-p="${esc(p.id)}"><div class="row sp"><div><b>${esc(p.name)}</b>
      <div class="small mut">${p.data_limit_gb ? p.data_limit_gb + ' گیگ' : 'نامحدود'} • ${p.duration_days} روز</div></div><div class="price">${toman(p.price)}</div></div></div>`).join('')}
      <p class="small mut">${s.kind === 'volume' ? 'در تمدید حجمی، مصرف صفر و حجم پلن جدید اعمال می‌شود و زمان به انقضای فعلی اضافه می‌شود.' : 'زمان پلن به انقضای فعلی اضافه می‌شود.'}</p>`);
    sh.querySelectorAll('.plan').forEach((c) => (c.onclick = () => { const p = r.plans.find((x) => x.id === c.dataset.p); checkout({ kind: 'renew', service_id: Number(id), plan_id: p.id, title: 'تمدید: ' + p.name, base: p.price }); }));
  });
}
const KIND = { purchase: 'خرید سرویس', renew: 'تمدید', topup: 'شارژ کیف پول' };
const OST = { completed: ['تکمیل', 'ok'], pending_payment: ['در انتظار پرداخت', 'warn'], paid: ['پرداخت‌شده', 'warn'], provisioning: ['در حال فعال‌سازی', 'warn'], failed: ['در حال تلاش مجدد', 'warn'], rejected: ['رد شده', 'bad'], refunded: ['برگشت‌خورده', 'bad'], cancelled: ['لغو', 'bad'] };
const orderRow = (o) => `<a class="card" href="#/order/${esc(o.id)}" style="display:block"><div class="row sp"><div><b>${KIND[o.kind]}${o.plan_name ? ' • ' + esc(o.plan_name) : ''}</b>
  <div class="small mut">${jdt(o.created_at)}</div></div><div style="text-align:left"><div>${toman(o.amount)}</div><span class="chip ${(OST[o.status] || OST.failed)[1]}">${(OST[o.status] || ['—'])[0]}</span></div></div></a>`;

async function pageAccount() {
  skeleton(3);
  const [a, os, tx] = await Promise.all([api('/api/v1/me'), api('/api/v1/orders?limit=20'), api('/api/v1/transactions?limit=20')]);
  header(a.user.name, a.balance);
  const guide = [['🤖 اندروید', 'اپ v2rayNG را نصب کن ← منو ← Subscription settings ← + و لینک اشتراک را وارد کن ← Update subscription ← یک سرور را انتخاب و وصل شو.'],
    ['🍎 iOS', 'اپ Streisand یا Shadowrocket را نصب کن ← + ← Subscribe ← لینک را وارد کن ← Connect.'],
    ['🪟 ویندوز', 'نرم‌افزار v2rayN ← Subscription → Subscription settings ← لینک را اضافه کن ← Update subscription ← Connect.'],
    ['🍏 مک', 'اپ V2Box یا Streisand ← Add Config → Add Subscription ← لینک را وارد کن و وصل شو.']];
  view.innerHTML = `<h2>حساب کاربری</h2><div class="card"><div class="kv"><span class="mut">نام</span><span>${esc(a.user.name || '—')}</span></div>
    <div class="kv"><span class="mut">نام کاربری</span><span class="ltr">${a.user.username ? '@' + esc(a.user.username) : '—'}</span></div>
    <div class="kv"><span class="mut">شناسه</span><span class="ltr">${a.user.id}</span></div>
    <div class="kv"><span class="mut">موجودی</span><b>${toman(a.balance)}</b></div></div>
    <button class="btn block ok" id="tp">💳 شارژ کیف پول</button>
    <h2>معرفی دوستان</h2><div class="card"><div class="grid2"><div><div class="small mut">دعوت موفق</div><b>${a.referral.count}</b></div><div><div class="small mut">امتیاز</div><b>${a.referral.points}</b></div></div>
    ${a.referral.link ? `<div class="code" style="margin-top:10px">${esc(a.referral.link)}</div><button class="btn ghost block sm" id="rl" style="margin-top:8px">کپی لینک دعوت</button>` : ''}</div>
    <h2>تاریخچه سفارش‌ها</h2>${os.items.length ? os.items.map(orderRow).join('') : empty('🧾', 'سفارشی ثبت نشده (سفارش‌های ربات اینجا نمایش داده نمی‌شوند).')}
    <h2>تاریخچه پرداخت‌ها</h2>${tx.items.length ? tx.items.map(orderRow).join('') : empty('💸', 'پرداختی ثبت نشده.')}
    <h2>راهنمای استفاده</h2><div class="card">${guide.map(([t, p]) => `<details><summary>${t}</summary><p>${esc(p)}</p></details>`).join('')}</div>
    <h2>تنظیمات</h2><div class="card"><label class="row sp" style="margin:0"><span>لرزش لمسی</span><input type="checkbox" id="hp" style="width:22px;height:22px" ${S.haptic ? 'checked' : ''}></label>
    <button class="btn ghost block sm" id="lo" style="margin-top:12px">خروج از همه نشست‌ها</button></div>`;
  $('#tp').onclick = () => {
    const s = sheet(`<h3>شارژ کیف پول</h3><label>مبلغ (تومان، حداقل 10,000)</label><input id="am" type="number" inputmode="numeric" class="ltr" min="10000" placeholder="100000">
      <button class="btn block" id="gp" style="margin-top:12px">ادامه</button>`);
    $('#gp', s).onclick = () => { const v = parseInt($('#am', s).value, 10); if (!(v >= 10000)) return toast('حداقل مبلغ 10,000 تومان است.', true); checkout({ kind: 'topup', base: v, title: 'شارژ کیف پول' }); };
  };
  const rl = $('#rl'); if (rl) rl.onclick = () => copy(a.referral.link);
  $('#hp').onchange = (e) => { S.haptic = e.target.checked; localStorage.setItem('haptic', S.haptic ? '1' : '0'); };
  $('#lo').onclick = (e) => busy(e.target, async () => { await api('/api/v1/auth/logout', { method: 'POST' }); await login(); toast('سایر نشست‌ها ابطال شدند ✅'); });
}

const TIPS = { connection: 'اپ کلاینت را به‌روز کن، «Update subscription» را بزن و بعد دوباره وصل شو. اگر حل نشد تیکت بزن.', payment: 'سفارش‌های کارت‌به‌کارت بعد از تأیید ادمین فعال می‌شوند؛ وضعیت را در تاریخچه سفارش‌ها ببین.', activation: 'فعال‌سازی گاهی چند دقیقه طول می‌کشد و در صورت خطا خودکار تکرار می‌شود.', renewal: 'تمدید به انقضای فعلی اضافه می‌شود و بعد از پرداخت خودکار اعمال می‌شود.', other: 'مشکلت را برایمان بنویس.' };
async function pageSupport() {
  skeleton(2);
  const d = await api('/api/v1/support/tickets?limit=20');
  const cats = Object.entries(d.categories);
  view.innerHTML = `<h2>پشتیبانی</h2><div class="card"><p class="mut small">ساعات پاسخگویی: همه روزه ۹ صبح تا ۱۲ شب</p>
    <div class="grid2"><button class="btn" id="nt">🎫 ثبت تیکت</button><button class="btn ghost" id="chat">💬 چت با پشتیبان</button></div></div>
    <h2>مشکلات رایج</h2><div class="card">${cats.map(([k, v]) => `<details><summary>${esc(v)}</summary><p>${esc(TIPS[k] || '')}</p></details>`).join('')}</div>
    <h2>تیکت‌های من</h2>${d.items.length ? d.items.map((t) => `<a class="card" href="#/ticket/${t.id}" style="display:block"><div class="row sp"><div><b>#${t.id} ${esc(t.subject)}</b><div class="small mut">${esc(t.category_title)} • ${jdt(t.updated_at)}</div></div>
      <span class="chip ${t.status === 'answered' ? 'ok' : t.status === 'closed' ? '' : 'warn'}">${{ open: 'باز', answered: 'پاسخ داده شد', closed: 'بسته' }[t.status]}</span></div></a>`).join('') : empty('🎫', 'تیکتی نداری.')}`;
  $('#chat').onclick = () => { if (tg && tg.openTelegramLink && /t\.me\//.test(d.support_url)) tg.openTelegramLink(d.support_url); else window.open(d.support_url, '_blank'); };
  $('#nt').onclick = () => {
    const s = sheet(`<h3>تیکت جدید</h3><label>دسته‌بندی</label><select id="c">${cats.map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join('')}</select>
      <label>موضوع</label><input id="s" maxlength="100"><label>توضیح</label><textarea id="b" maxlength="2000"></textarea>
      <button class="btn block" id="sd" style="margin-top:12px">ارسال</button>`);
    $('#sd', s).onclick = (e) => busy(e.target, async () => {
      const t = await api('/api/v1/support/tickets', { method: 'POST', body: { category: $('#c', s).value, subject: $('#s', s).value, body: $('#b', s).value } });
      closeSheet(); toast('تیکت ثبت شد ✅'); location.hash = `#/ticket/${t.id}`;
    });
  };
}
async function pageTicket(id) {
  skeleton(2);
  const t = await api(`/api/v1/support/tickets/${id}`);
  view.innerHTML = `<h2>#${t.id} ${esc(t.subject)}</h2><div class="small mut">${esc(t.category_title)}</div>
    ${t.messages.map((m) => `<div class="msg ${m.sender}"><div class="small mut">${m.sender === 'admin' ? 'پشتیبانی' : 'شما'} • ${jdt(m.created_at)}</div>${esc(m.body).replace(/\n/g, '<br>')}</div>`).join('')}
    ${t.status !== 'closed' ? `<textarea id="rb" placeholder="پیام جدید…" maxlength="2000"></textarea><div class="grid2" style="margin-top:8px"><button class="btn" id="rs">ارسال</button><button class="btn ghost" id="cl">بستن تیکت</button></div>` : '<p class="mut">این تیکت بسته شده است.</p>'}`;
  const rs = $('#rs'); if (!rs) return;
  rs.onclick = (e) => busy(e.target, async () => { await api(`/api/v1/support/tickets/${id}/messages`, { method: 'POST', body: { body: $('#rb').value } }); pageTicket(id); });
  $('#cl').onclick = (e) => busy(e.target, async () => { await api(`/api/v1/support/tickets/${id}/close`, { method: 'POST' }); location.hash = '#/support'; });
}

// ───── روتر ─────
const ROUTES = [[/^#\/?$/, 'home', pageHome], [/^#\/shop$/, 'shop', pageShop], [/^#\/services$/, 'services', pageServices], [/^#\/service\/(\d+)$/, 'services', pageService],
  [/^#\/account$/, 'account', pageAccount], [/^#\/support$/, 'support', pageSupport], [/^#\/ticket\/(\d+)$/, 'support', pageTicket], [/^#\/order\/([A-Za-z0-9]+)$/, 'services', pageOrder]];
async function route() {
  clearTimeout(poll); closeSheet(); window.scrollTo(0, 0);
  const h = location.hash || '#/';
  const r = ROUTES.find(([re]) => re.test(h)) || ROUTES[0];
  document.querySelectorAll('#nav a').forEach((a) => a.classList.toggle('on', a.dataset.r === r[1]));
  const arg = (h.match(r[0]) || [])[1];
  if (tg && tg.BackButton) { if (arg !== undefined && r[1] !== 'home') tg.BackButton.show(); else tg.BackButton.hide(); }
  try { await r[2](arg); } catch (e) { if (e.code === 'no_telegram') return; fail(e); view.innerHTML = empty('⚠️', esc(e.message), '<button class="btn" onclick="location.reload()">تلاش دوباره</button>'); }
}

function boot() {
  if (tg) { try { tg.ready(); tg.expand(); tg.setHeaderColor('#070b1a'); tg.setBackgroundColor('#070b1a'); tg.BackButton.onClick(() => history.back()); } catch (e) {} }
  window.addEventListener('online', () => ($('#offline').hidden = true));
  window.addEventListener('offline', () => ($('#offline').hidden = false));
  window.addEventListener('hashchange', route);
  login().then(route).catch((e) => {
    view.innerHTML = e.code === 'no_telegram'
      ? empty('📱', 'این صفحه را از داخل ربات تلگرام باز کن.')
      : empty('🔒', esc(e.message), e.code === 'not_registered' || e.code === 'membership_required' ? '' : '<button class="btn" onclick="location.reload()">تلاش دوباره</button>');
  });
}
boot();
})();
