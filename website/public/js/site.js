// AnKar Video Editor website. One script for all pages (body[data-page]). Text is always set with textContent —
// never innerHTML — so nothing from the server or a user can inject HTML.
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) if (c != null) e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return e;
}

async function api(path, body) {
  const r = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(j.detail || `Something went wrong (${r.status}).`); e.status = r.status; throw e; }
  return j;
}

function showMsg(box, text, kind = 'err') {
  if (!box) return;
  box.className = `msg ${kind}`;
  box.textContent = text;
  box.classList.toggle('hidden', !text);
}

/** Wire a <form>: collects named inputs, disables the button while busy, shows errors in .msg inside the form. */
function form(sel, handler) {
  const f = $(sel);
  if (!f) return;
  f.addEventListener('submit', async e => {
    e.preventDefault();
    const btn = f.querySelector('button[type=submit]');
    const msg = f.querySelector('.msg');
    const data = Object.fromEntries([...f.querySelectorAll('input[name]')].map(i => [i.name, i.type === 'checkbox' ? i.checked : i.value]));
    showMsg(msg, '');
    btn && (btn.disabled = true);
    try { await handler(data, f, msg); }
    catch (x) { showMsg(msg, x.message); for (const p of f.querySelectorAll('input[type=password]')) if (p.dataset.keep !== '1') p.value = ''; }
    finally { btn && (btn.disabled = false); }
  });
}

const next = () => new URLSearchParams(location.search).get('next');
const afterSignIn = () => { location.href = next() === 'download' ? '/account?download=1' : '/account'; };

// ---------------------------------------------------------------- header (signed-in state + update dot)
let ME = null;
async function header() {
  try { ME = await api('/api/me'); } catch (e) { ME = { signed_in: false }; }
  const a = $('#navAcct');
  if (a && ME.username) {
    a.textContent = ME.username;
    a.href = '/account';
    a.classList.remove('primary');
    if (ME.update_available) a.append(el('span', { class: 'dot', title: 'A new version is available' }));
  }
  for (const d of $$('[data-download]')) d.href = ME.username ? '/api/download' : '/signup?next=download';
  try {
    const c = await api('/api/config');
    if (c.repo) for (const g of $$('[data-github]')) { g.href = `https://github.com/${c.repo}`; g.classList.remove('hidden'); }
    return c;
  } catch (e) { return {}; }
}

function releaseList(target, rels, { latestTag = true } = {}) {
  target.replaceChildren(...rels.map((r, i) => el('div', { class: `rel ${i === 0 && latestTag ? 'latest' : ''}` },
    el('h3', {}, `Version ${r.version}`, el('span', { class: 'date', text: r.date }), i === 0 && latestTag ? el('span', { class: 'tag', text: 'latest' }) : null),
    el('ul', {}, r.notes.map(n => el('li', { text: n }))))));
}

// ---------------------------------------------------------------- pages
const pages = {
  async home() {
    try {
      const l = await api('/api/latest');
      for (const v of $$('[data-latest]')) v.textContent = l.version;
    } catch (e) { /* offline */ }
  },

  async whatsnew() {
    const l = await api('/api/latest');
    releaseList($('#releases'), l.releases);
  },

  async signup(cfg) {
    if (ME.username) return afterSignIn();
    $$('.minpw').forEach(e => { e.textContent = cfg.min_password || 10; });
    if (!cfg.email_possible) { $('#emailRow').classList.add('hidden'); $('#noEmailYet').classList.remove('hidden'); }
    const email = $('input[name=email]');
    const warn = () => $('#noEmailWarn').classList.toggle('hidden', !!email.value.trim() || !cfg.email_possible);
    email?.addEventListener('input', warn); warn();
    form('#signupForm', async d => {
      if (d.password !== d.password2) throw new Error('The two passwords are different.');
      await api('/api/signup', { username: d.username, password: d.password, email: d.email || null });
      afterSignIn();
    });
  },

  async signin() {
    if (ME.username) return afterSignIn();
    if (next() === 'download') showMsg($('#why'), 'Sign in (or create a free account) to download — then we can remind you when there\'s a new version.', 'info');
    form('#signinForm', async d => { await api('/api/signin', { username: d.username, password: d.password }); afterSignIn(); });
  },

  async forgot(cfg) {
    if (!cfg.email_reset) { $('#forgotOff').classList.remove('hidden'); $('#step1').classList.add('hidden'); return; }
    let user = '';
    form('#step1', async d => {
      const r = await api('/api/forgot', { username: d.username });
      user = d.username;
      $('#step1').classList.add('hidden');
      $('#step2').classList.remove('hidden');
      showMsg($('#sent'), r.message, 'info');
      $('input[name=code]').focus();
    });
    form('#step2', async d => {
      if (d.new !== d.new2) throw new Error('The two passwords are different.');
      await api('/api/reset', { username: user, code: d.code, new: d.new });
      location.href = '/account';
    });
  },

  async account() {
    if (!ME.username) { location.href = '/signin'; return; }
    const draw = me => {
      ME = me;
      $('#avatar').textContent = me.username[0].toUpperCase();
      $('#uname').textContent = me.username;
      $('#joined').textContent = `Member since ${me.joined}`;
      $('#adminLink').classList.toggle('hidden', !me.admin);
      const v = $('#versionInfo');
      if (me.last_version) v.replaceChildren(el('div', { class: 'big-v', text: me.last_version }),
        el('div', { class: 'muted' }, `Your latest download · ${me.last_download}`));
      else v.replaceChildren(el('div', { class: 'muted', text: "You haven't downloaded AnKar Video Editor yet." }));
      const up = $('#update');
      up.classList.toggle('hidden', !me.update_available);
      if (me.update_available) {
        $('#upTitle').replaceChildren(`Version ${me.latest.version} is available`, el('span', { class: 'dot' }));
        releaseList($('#upNotes'), me.notes_since, { latestTag: false });
      }
      $('#dlBtn').textContent = me.last_version && !me.update_available ? `Download ${me.latest.version} again` : `Download ${me.latest.version}`;
      $('#emailState').textContent = me.email ? `Saved: ${me.email}` : 'No email saved — a forgotten password can\'t be recovered.';
      $('#emailRemove').classList.toggle('hidden', !me.email);
      $('#emailBox').classList.toggle('hidden', !me.email_possible);
    };
    draw(ME);
    if (new URLSearchParams(location.search).get('download') === '1') {
      history.replaceState(null, '', '/account');
      showMsg($('#dlMsg'), 'Your download is starting. Unzip it, then double-click "Setup AnKar Video Editor.bat".', 'ok');
      location.href = '/api/download';
      setTimeout(async () => draw(await api('/api/me')), 2500);
    }
    $('#dlBtn').addEventListener('click', () => {
      showMsg($('#dlMsg'), 'Your download is starting. Unzip it, then double-click "Setup AnKar Video Editor.bat" (see Get started).', 'ok');
      setTimeout(async () => draw(await api('/api/me')), 2500);
    });
    form('#pwForm', async (d, f, msg) => {
      if (d.new !== d.new2) throw new Error('The two new passwords are different.');
      await api('/api/password', { current: d.current, new: d.new });
      f.reset(); showMsg(msg, 'Password changed. Other browsers were signed out.', 'ok');
    });
    form('#emailForm', async (d, f, msg) => {
      draw(await api('/api/email', { email: d.email, password: d.password }));
      f.reset(); showMsg(msg, 'Email saved. It is only used for "forgot password".', 'ok');
    });
    $('#emailRemove').addEventListener('click', async () => {
      const pw = $('#emailForm input[name=password]').value;
      const msg = $('#emailForm .msg');
      if (!pw) return showMsg(msg, 'Type your password above, then click Remove email.');
      try { draw(await api('/api/email', { email: null, password: pw })); $('#emailForm').reset(); showMsg(msg, 'Email removed.', 'ok'); }
      catch (x) { showMsg(msg, x.message); }
    });
    $('#myData').addEventListener('click', async () => {
      const d = await api('/api/mydata');
      $('#dataList').replaceChildren(...Object.entries(d).flatMap(([k, v]) => [el('dt', { text: k.replaceAll('_', ' ') }), el('dd', { text: v ?? '—' })]));
      $('#dataBox').classList.remove('hidden');
    });
    $('#signout').addEventListener('click', async () => { await api('/api/signout', {}); location.href = '/'; });
    form('#deleteForm', async d => {
      if (!d.sure) throw new Error('Tick the box to confirm.');
      await api('/api/delete', { password: d.password });
      location.href = '/?deleted=1';
    });
  },

  async admin() {
    if (!ME.username) { location.href = '/signin'; return; }
    let st;
    try { st = await api('/api/admin/status'); }
    catch (e) { $('#notAdmin').classList.remove('hidden'); return; }
    const show = id => ['#setup', '#unlock', '#dash'].forEach(s => $(s).classList.toggle('hidden', s !== id));
    if (st.unlocked) return dash();
    show(st.totp ? '#unlock' : '#setup');
    form('#setupForm', async d => {
      const r = await api('/api/admin/totp/setup', { password: d.password });
      $('#setupForm').classList.add('hidden');
      $('#qrBox').classList.remove('hidden');
      if (r.qr) $('#qr').src = r.qr; else $('#qr').classList.add('hidden');
      $('#secret').textContent = r.secret.match(/.{1,4}/g).join(' ');
    });
    const verify = async d => { await api('/api/admin/totp/verify', { code: d.code }); dash(); };
    form('#confirmForm', verify);
    form('#unlockForm', verify);

    async function dash() {
      show('#dash');
      const s = await api('/api/admin/stats');
      const tile = (n, l) => el('div', { class: 'tile' }, el('div', { class: 'n', text: n }), el('div', { class: 'l', text: l }));
      $('#tiles').replaceChildren(tile(s.users, 'users'), tile(s.new_7d, 'new in 7 days'), tile(s.new_30d, 'new in 30 days'),
        tile(`${s.up_to_date}/${s.users}`, `on the latest (${s.latest_version})`), tile(s.with_email, 'with a reset email'),
        tile(s.active_sessions, 'signed-in browsers'));
      const table = (rows, heads) => el('table', {}, el('thead', {}, el('tr', {}, heads.map(h => el('th', { text: h })))),
        el('tbody', {}, rows.map(r => el('tr', {}, r.map(c => el('td', {}, c))))));
      $('#byVersion').replaceChildren(table(Object.entries(s.users_by_latest_download), ['latest download', 'users']));
      $('#downloads').replaceChildren(table(Object.entries(s.downloads_by_version), ['version', 'downloads (all time)']));
      $('#list').replaceChildren(table(s.list.map(u => [`#${u.user}`, u.joined, u.last_download, u.disabled ? 'disabled' : 'active']),
        ['user', 'joined', 'last download', 'status']));
    }
    form('#actForm', async (d, f, msg) => {
      const action = f.querySelector('select').value;
      if (action === 'delete' && !confirm(`Delete user #${d.user} for good?`)) return;
      await api('/api/admin/user', { user: d.user, action });
      showMsg(msg, `User #${d.user}: ${action} done.`, 'ok'); f.reset(); dash();
    });
  },
};

(async () => {
  const cfg = await header();
  const p = document.body.dataset.page;
  if (new URLSearchParams(location.search).get('deleted') === '1') showMsg($('#flash'), 'Your account and everything stored about it were deleted.', 'ok');
  try { await pages[p]?.(cfg); }
  catch (e) { showMsg($('#flash') || $('.msg'), e.message); }
})();
