// API Keys page. Values are only ever sent TO the server (with the password); the server never sends a key back,
// only "saved ••••abcd". All text is set with textContent (no HTML injection).
const $ = id => document.getElementById(id);
let state = null;
let mode = null;            // {kind: 'set' | 'remove' | 'custom', name, label}

async function call(path, body) {
  const r = await fetch(path, {
    method: body ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json', 'X-Vlog-Keys': '1' },
    body: body ? JSON.stringify(body) : undefined, credentials: 'same-origin', cache: 'no-store',
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || j.error || r.statusText);
  return j;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function card(k, custom) {
  const c = el('div', 'card');
  const info = el('div', 'info');
  info.append(el('div', 'title', k.label), el('div', 'sub', `Used by: ${k.used_for}${custom ? ` · name: ${k.name}` : ''}`));
  const st = !k.set ? el('div', 'status no', 'Not set') :
    k.source === 'environment' ? el('div', 'status env', `From an environment variable (${k.masked}) — change it there`) :
    el('div', 'status ok', `Saved ${k.masked}${k.updated ? ` · updated ${k.updated}` : ''}`);
  info.append(st);
  if (k.hint && !k.set) info.append(el('div', 'sub', `Get it at ${k.hint}`));
  const acts = el('div', 'acts');
  const res = el('div', 'result hidden');
  if (k.source !== 'environment') {
    const b = el('button', 'btn' + (k.set ? '' : ' primary'), k.set ? 'Change' : 'Add key');
    b.onclick = () => open({ kind: 'set', name: k.name, label: k.label, hint: k.hint });
    acts.append(b);
    if (k.set) {
      const r = el('button', 'btn danger', 'Remove');
      r.onclick = () => open({ kind: 'remove', name: k.name, label: k.label });
      acts.append(r);
    }
  }
  if (k.set) {
    const t = el('button', 'btn', 'Test');
    t.onclick = async () => {
      t.disabled = true; res.classList.remove('hidden'); res.textContent = 'Testing…';
      try { const r = await call('/api/keys/test', { name: k.name }); res.textContent = (r.ok ? '✅ ' : '⚠ ') + r.message; }
      catch (e) { res.textContent = '⚠ ' + e.message; }
      t.disabled = false;
    };
    acts.append(t);
  }
  c.append(info, acts, res);
  return c;
}

function render() {
  const s = $('services'), cu = $('custom');
  s.replaceChildren(...state.services.map(k => card(k, false)));
  cu.replaceChildren(...state.custom.map(k => card(k, true)));
  $('noCustom').classList.toggle('hidden', state.custom.length > 0);
  $('enc').textContent = state.encryption || 'AES-256-GCM';
  const a = state.auth || {};
  const unset = a.password === 'unset';
  $('setup').classList.toggle('hidden', !unset);
  $('keysArea').classList.toggle('hidden', unset);
  $('customArea').classList.toggle('hidden', unset);
  $('changePw').classList.toggle('hidden', unset);
  for (const m of document.querySelectorAll('.minLen')) m.textContent = a.min_len || 10;
  $('pwInfo').textContent = unset ? 'Password: not created yet.'
    : 'Password: your own password is active (stored on this PC only, as a one-way hash).';
  const lk = $('locked');
  lk.classList.toggle('hidden', !a.locked_s);
  lk.textContent = a.locked_s ? `Too many wrong passwords — changes are locked for ${a.locked_s} s.` : '';
}

async function load() {
  try { state = await call('/api/keys'); render(); }
  catch (e) { document.body.replaceChildren(el('p', 'notice warn', 'This page only works inside AnKar Video Editor: ' + e.message)); }
}

function open(m) {
  mode = m;
  const custom = m.kind === 'custom', remove = m.kind === 'remove';
  $('mTitle').textContent = remove ? `Remove the ${m.label} key?` : custom ? 'Add another key' : `${m.label} key`;
  $('mHint').textContent = remove ? 'The AI features that use it stop working until you add a key again.'
    : (m.hint ? `Get it at ${m.hint}. ` : '') + 'Paste the key; it is encrypted and never shown again.';
  $('nameRow').classList.toggle('hidden', !custom);
  $('labelRow').classList.toggle('hidden', !custom);
  $('valueRow').classList.toggle('hidden', remove);
  $('ok').textContent = remove ? 'Remove' : 'Save';
  $('ok').className = 'btn ' + (remove ? 'danger' : 'primary');
  for (const f of ['fName', 'fLabel', 'fValue', 'fPass']) $(f).value = '';
  $('fValue').type = 'password'; $('toggle').textContent = 'Show';
  $('mErr').classList.add('hidden');
  $('modal').classList.remove('hidden');
  setTimeout(() => $(custom ? 'fName' : remove ? 'fPass' : 'fValue').focus(), 30);
}

function close() {
  $('modal').classList.add('hidden');
  for (const f of ['fValue', 'fPass']) $(f).value = '';     // don't keep secrets in the page
  mode = null;
}

$('toggle').onclick = () => { const v = $('fValue'); v.type = v.type === 'password' ? 'text' : 'password'; $('toggle').textContent = v.type === 'password' ? 'Show' : 'Hide'; };
$('cancel').onclick = close;
$('addCustom').onclick = () => open({ kind: 'custom', label: 'Custom key' });
$('modal').addEventListener('pointerdown', e => { if (e.target === $('modal')) close(); });
window.addEventListener('keydown', e => { if (e.key === 'Escape' && mode) close(); });
$('form').onsubmit = async e => {
  e.preventDefault();
  const err = $('mErr');
  const password = $('fPass').value;
  if (!password) { err.textContent = 'Enter your password.'; err.classList.remove('hidden'); return; }
  $('ok').disabled = true;
  try {
    if (mode.kind === 'remove') state = await call('/api/keys/remove', { name: mode.name, password });
    else state = await call('/api/keys/set', { name: mode.kind === 'custom' ? $('fName').value.trim() : mode.name,
                                               value: $('fValue').value, label: $('fLabel').value, password });
    close(); render();
  } catch (x) {
    err.textContent = x.message; err.classList.remove('hidden');
    $('fPass').value = '';
    call('/api/keys').then(s => { state = s; render(); }).catch(() => {});
  } finally { $('ok').disabled = false; }
};

// ---- password: create (first time) / change
function showErr(id, msg) { const e = $(id); e.textContent = msg; e.classList.toggle('hidden', !msg); }

$('setupForm').onsubmit = async e => {
  e.preventDefault();
  const a = $('sNew').value, b = $('sNew2').value;
  if (a !== b) return showErr('sErr', 'The two passwords are different.');
  try { state = await call('/api/keys/password', { new: a }); $('sNew').value = $('sNew2').value = ''; showErr('sErr', ''); render(); }
  catch (x) { showErr('sErr', x.message); }
};

const closePw = () => { $('pwModal').classList.add('hidden'); for (const f of ['pCur', 'pNew', 'pNew2']) $(f).value = ''; };
$('changePw').onclick = () => { showErr('pErr', ''); $('pwModal').classList.remove('hidden'); setTimeout(() => $('pCur').focus(), 30); };
$('pCancel').onclick = closePw;
$('pwModal').addEventListener('pointerdown', e => { if (e.target === $('pwModal')) closePw(); });
$('pwForm').onsubmit = async e => {
  e.preventDefault();
  if ($('pNew').value !== $('pNew2').value) return showErr('pErr', 'The two new passwords are different.');
  $('pOk').disabled = true;
  try { state = await call('/api/keys/password', { current: $('pCur').value, new: $('pNew').value }); closePw(); render(); }
  catch (x) { showErr('pErr', x.message); $('pCur').value = ''; }
  finally { $('pOk').disabled = false; }
};

load();
