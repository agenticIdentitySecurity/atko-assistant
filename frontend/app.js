/* Atko Assistant — vanilla JS client */

let chatHistory = [];
let loading = false;

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', async () => {
  try {
    const res = await fetch('/api/me');
    if (!res.ok) { window.location.href = '/login-page'; return; }
    const user = await res.json();
    const nameEl = document.getElementById('user-name');
    const badgeEl = document.getElementById('user-badge');
    if (nameEl && badgeEl) {
      nameEl.textContent = user.name || user.email;
      badgeEl.classList.remove('hidden');
      badgeEl.classList.add('flex');
    }
  } catch (e) {
    window.location.href = '/login-page';
  }
  document.getElementById('input').focus();
});

// ---------------------------------------------------------------------------
// Sending
// ---------------------------------------------------------------------------

function onKey(e) {
  if (e.key === 'Enter' && !loading) send();
}

async function send() {
  const input = document.getElementById('input');
  const msg = input.value.trim();
  if (!msg || loading) return;

  input.value = '';
  setLoading(true);
  resetInspector();

  appendMessage('user', msg);
  const thinkingId = appendThinking();

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: msg,
        conversation_history: chatHistory,
      }),
    });

    removeThinking(thinkingId);

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
      appendMessage('assistant', `Error: ${err.detail || res.statusText}`);
      renderFlowEvents(err.flow_events || []);
      renderTokenDetails(err.token_details);
      return;
    }

    const data = await res.json();
    appendMessage('assistant', data.response, data.tool_calls);
    renderFlowEvents(data.flow_events || []);
    renderToolCalls(data.tool_calls || []);
    renderTokenDetails(data.token_details);

    // Keep last 20 turns in history
    chatHistory.push({ role: 'user', content: msg });
    chatHistory.push({ role: 'assistant', content: data.response });
    if (chatHistory.length > 40) chatHistory = chatHistory.slice(-40);

  } catch (err) {
    removeThinking(thinkingId);
    appendMessage('assistant', `Network error: ${err.message}`);
  } finally {
    setLoading(false);
    document.getElementById('input').focus();
  }
}

// ---------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------

function appendMessage(role, text, toolCalls = []) {
  const list = document.getElementById('message-list');
  const wrapper = document.createElement('div');
  wrapper.className = role === 'user' ? 'flex justify-end' : 'flex justify-start';

  const bubble = document.createElement('div');
  if (role === 'user') {
    bubble.className = 'bg-blue-600 text-white rounded-2xl rounded-tr-sm shadow-sm px-4 py-3 max-w-xl text-sm';
    bubble.textContent = text;
  } else {
    bubble.className = 'bg-white rounded-2xl rounded-tl-sm shadow-sm px-4 py-3 max-w-xl text-sm text-gray-800 prose';
    bubble.innerHTML = formatText(text);
    if (toolCalls && toolCalls.length > 0) {
      const tag = document.createElement('p');
      tag.className = 'mt-2 text-xs text-gray-400';
      tag.textContent = `Tools used: ${toolCalls.join(', ')}`;
      bubble.appendChild(tag);
    }
  }

  wrapper.appendChild(bubble);
  list.appendChild(wrapper);
  scrollBottom();
}

function appendThinking() {
  const id = 'thinking-' + Date.now();
  const list = document.getElementById('message-list');
  const wrapper = document.createElement('div');
  wrapper.id = id;
  wrapper.className = 'flex justify-start';
  wrapper.innerHTML = `
    <div class="bg-white rounded-2xl rounded-tl-sm shadow-sm px-4 py-3 text-sm text-gray-400 dot-blink">
      Thinking<span>.</span><span>.</span><span>.</span>
    </div>`;
  list.appendChild(wrapper);
  scrollBottom();
  return id;
}

function removeThinking(id) {
  document.getElementById(id)?.remove();
}

function setLoading(val) {
  loading = val;
  document.getElementById('send-btn').disabled = val;
  document.getElementById('input').disabled = val;
}

function scrollBottom() {
  const messages = document.getElementById('messages');
  messages.scrollTop = messages.scrollHeight;
}

function logout() {
  window.location.href = '/auth/logout';
}

// ---------------------------------------------------------------------------
// Token Inspector — accordion
// ---------------------------------------------------------------------------

function toggleSection(id) {
  const body = document.getElementById('body-' + id);
  const chevron = document.getElementById('chevron-' + id);
  if (!body) return;
  body.classList.toggle('hidden');
  if (chevron) chevron.classList.toggle('rotate-180');
}

function expandSection(id) {
  const body = document.getElementById('body-' + id);
  const chevron = document.getElementById('chevron-' + id);
  if (!body) return;
  body.classList.remove('hidden');
  if (chevron) chevron.classList.add('rotate-180');
}

function resetInspector() {
  // Reset all claim sections to placeholder
  setPlaceholder('id-token-claims', 'Awaiting login data');
  setPlaceholder('id-jag-claims', 'No exchange yet');
  setPlaceholder('access-token-claims', 'No exchange yet');
  setPlaceholder('tool-calls-list', 'No tools called');
  document.getElementById('flow-events').innerHTML =
    '<p class="text-[11px] text-slate-400 italic">Processing...</p>';
  // Collapse all sections
  ['id-token', 'id-jag', 'access-token', 'tool-calls', 'identity-flow'].forEach(id => {
    const body = document.getElementById('body-' + id);
    const chevron = document.getElementById('chevron-' + id);
    if (body) body.classList.add('hidden');
    if (chevron) chevron.classList.remove('rotate-180');
  });
}

function setPlaceholder(elId, text) {
  const el = document.getElementById(elId);
  if (el) el.innerHTML = `<p class="text-slate-400 italic">${text}</p>`;
}

// ---------------------------------------------------------------------------
// Render token claims
// ---------------------------------------------------------------------------

function renderTokenDetails(details) {
  if (!details) return;

  // Client IDs
  if (details.oidc_client_id || details.agent_client_id) {
    const wrap = document.getElementById('client-ids');
    if (wrap) wrap.classList.remove('hidden');
    const oidcEl = document.getElementById('oidc-client-id');
    const agentEl = document.getElementById('agent-client-id');
    if (oidcEl) oidcEl.textContent = details.oidc_client_id || '';
    if (agentEl) agentEl.textContent = details.agent_client_id || '';
  }

  if (details.id_token_claims) {
    renderClaims('id-token-claims', details.id_token_claims);
    expandSection('id-token');
  }
  if (details.id_jag_claims) {
    renderClaims('id-jag-claims', details.id_jag_claims);
    expandSection('id-jag');
  }
  if (details.access_token_claims) {
    renderClaims('access-token-claims', details.access_token_claims);
    expandSection('access-token');
  }
}

const KEY_CLAIMS = ['sub', 'iss', 'aud', 'exp', 'iat', 'scp', 'scope', 'act', 'name', 'email', 'cid'];

function renderClaims(elId, claims) {
  const el = document.getElementById(elId);
  if (!el || !claims) return;

  // Key claims summary
  const keyRows = Object.entries(claims)
    .filter(([k]) => KEY_CLAIMS.includes(k))
    .map(([key, val]) => {
      const display = formatClaimValue(key, val);
      return `<div class="flex justify-between gap-2 py-0.5">
        <span class="text-slate-500 shrink-0">${key}</span>
        <span class="font-mono text-slate-700 text-right truncate" title="${escapeAttr(String(val))}">${display}</span>
      </div>`;
    }).join('');

  // Raw JSON toggle
  const rawId = elId + '-raw';
  const rawJson = escapeAttr(JSON.stringify(claims, null, 2))
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');

  el.innerHTML = (keyRows || '<p class="text-slate-400 italic">No claims</p>') +
    `<div class="mt-1.5 border-t border-slate-200 pt-1.5">
      <button onclick="document.getElementById('${rawId}').classList.toggle('hidden')" class="text-[10px] text-blue-500 hover:text-blue-700 font-medium">
        Show/hide raw JSON
      </button>
      <pre id="${rawId}" class="hidden mt-1 p-2 bg-slate-900 text-slate-200 rounded text-[10px] overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap break-all">${escapeHtml(JSON.stringify(claims, null, 2))}</pre>
    </div>`;
}

function formatClaimValue(key, val) {
  // Timestamps
  if ((key === 'exp' || key === 'iat') && typeof val === 'number' && val > 1e9) {
    const d = new Date(val * 1000);
    return d.toLocaleTimeString() + ' ' + d.toLocaleDateString();
  }
  // Arrays (scopes)
  if (Array.isArray(val)) return val.join(', ');
  // Objects (like act)
  if (typeof val === 'object' && val !== null) {
    return Object.entries(val).map(([k, v]) => `${k}:${v}`).join(', ');
  }
  // Long strings
  const s = String(val);
  if (s.length > 35) return s.slice(0, 35) + '...';
  return s;
}

function escapeAttr(s) {
  return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ---------------------------------------------------------------------------
// Render tool calls
// ---------------------------------------------------------------------------

function renderToolCalls(toolCalls) {
  const el = document.getElementById('tool-calls-list');
  if (!el) return;

  if (!toolCalls || toolCalls.length === 0) {
    el.innerHTML = '<p class="text-slate-400 italic">No tools called</p>';
    return;
  }

  const pills = toolCalls.map(t =>
    `<span class="inline-block px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 border border-emerald-300 font-mono">${t}</span>`
  ).join(' ');

  el.innerHTML = pills;
  expandSection('tool-calls');
}

// ---------------------------------------------------------------------------
// Identity Flow panel
// ---------------------------------------------------------------------------

function renderFlowEvents(events) {
  const panel = document.getElementById('flow-events');
  if (!panel) return;
  panel.innerHTML = '';

  if (!events.length) {
    panel.innerHTML = '<p class="text-[11px] text-slate-400 italic">Send a message to see the flow</p>';
    return;
  }

  events.forEach((evt, i) => {
    const div = document.createElement('div');
    div.className = 'flow-step text-[11px] px-2 py-1.5 rounded border step-ok';
    div.style.animationDelay = `${i * 0.08}s`;
    div.textContent = `\u2713  ${evt}`;
    panel.appendChild(div);
  });

  expandSection('identity-flow');
}

// ---------------------------------------------------------------------------
// Very minimal markdown-ish formatter (no library dependency)
// ---------------------------------------------------------------------------

function formatText(text) {
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Code blocks ```...```
  html = html.replace(/```[\s\S]*?```/g, m => {
    const code = m.slice(3, -3).replace(/^\w*\n/, '');
    return `<pre><code>${code}</code></pre>`;
  });

  // Inline code `...`
  html = html.replace(/`([^`]+)`/g, '<code class="bg-gray-100 px-1 rounded text-xs">$1</code>');

  // Bold **...**
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  // Bullet lists
  const lines = html.split('\n');
  let inList = false;
  const out = [];
  for (const line of lines) {
    const bullet = line.match(/^[-*]\s+(.*)/);
    if (bullet) {
      if (!inList) { out.push('<ul>'); inList = true; }
      out.push(`<li>${bullet[1]}</li>`);
    } else {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(line ? `<p>${line}</p>` : '');
    }
  }
  if (inList) out.push('</ul>');
  return out.join('');
}
