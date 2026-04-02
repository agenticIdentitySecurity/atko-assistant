/* AI Agent Chat — vanilla JS client */

let history = [];
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
    if (nameEl) {
      nameEl.textContent = user.name || user.email;
      nameEl.classList.remove('hidden');
    }
  } catch {
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

  // Reset side panels for new request
  document.getElementById('flow-events').innerHTML =
    '<p class="text-[11px] text-slate-400 text-center mt-4">Processing…</p>';
  document.getElementById('token-exchanges').innerHTML =
    '<p class="text-[11px] text-slate-400 text-center mt-2">Processing…</p>';
  document.getElementById('token-summary').classList.add('hidden');

  appendMessage('user', msg);

  const thinkingId = appendThinking();

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: msg,
        conversation_history: history,
      }),
    });

    removeThinking(thinkingId);

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
      appendMessage('assistant', `⚠️ Error: ${err.detail || res.statusText}`);
      renderFlowEvents(err.flow_events || []);
      renderTokenExchanges(err.token_exchanges || []);
      return;
    }

    const data = await res.json();
    appendMessage('assistant', data.response, data.tool_calls);
    renderFlowEvents(data.flow_events || []);
    renderTokenExchanges(data.token_exchanges || []);

    // Keep last 20 turns in history
    history.push({ role: 'user', content: msg });
    history.push({ role: 'assistant', content: data.response });
    if (history.length > 40) history = history.slice(-40);

  } catch (err) {
    removeThinking(thinkingId);
    appendMessage('assistant', `⚠️ Network error: ${err.message}`);
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
  wrapper.className = role === 'user'
    ? 'flex justify-end'
    : 'flex justify-start';

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
      tag.textContent = `🔧 Tools used: ${toolCalls.join(', ')}`;
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
// Identity Flow panel
// ---------------------------------------------------------------------------

function renderFlowEvents(events) {
  const panel = document.getElementById('flow-events');
  panel.innerHTML = '';
  if (!events.length) {
    panel.innerHTML = '<p class="text-[11px] text-slate-400 text-center mt-4">Send a message to see the<br/>Okta token flow in action.</p>';
    return;
  }
  events.forEach((evt, i) => {
    const div = document.createElement('div');
    div.className = 'flow-step text-[11px] px-3 py-2 rounded border step-ok';
    div.style.animationDelay = `${i * 0.08}s`;
    div.textContent = `✓  ${evt}`;
    panel.appendChild(div);
  });
}

// ---------------------------------------------------------------------------
// Token Exchange panel
// ---------------------------------------------------------------------------

function renderTokenExchanges(exchanges) {
  const panel     = document.getElementById('token-exchanges');
  const summary   = document.getElementById('token-summary');
  const grantedEl = document.getElementById('token-granted-count');
  const deniedEl  = document.getElementById('token-denied-count');
  panel.innerHTML = '';

  if (!exchanges.length) {
    panel.innerHTML = '<p class="text-[11px] text-slate-400 text-center mt-2">No exchanges yet.</p>';
    summary.classList.add('hidden');
    return;
  }

  const granted = exchanges.filter(e => e.success && !e.access_denied);
  const denied  = exchanges.filter(e => e.access_denied || !e.success);

  summary.classList.remove('hidden');
  grantedEl.textContent = `✓ ${granted.length} Granted`;
  if (denied.length > 0) {
    deniedEl.classList.remove('hidden');
    deniedEl.textContent = `✗ ${denied.length} Denied`;
  } else {
    deniedEl.classList.add('hidden');
  }

  exchanges.forEach(ex => {
    const isGranted = ex.success && !ex.access_denied;
    const card = document.createElement('div');
    card.className = isGranted
      ? 'rounded-lg border-2 p-3 border-green-300 bg-green-50'
      : 'rounded-lg border-2 p-3 border-red-300 bg-red-50';

    const scopesToShow = isGranted
      ? (ex.scopes || [])
      : (ex.requested_scopes && ex.requested_scopes.length ? ex.requested_scopes : ex.scopes || []);
    const scopeLabel = isGranted ? 'Granted scope:' : 'Requested scope:';
    const scopeClass = isGranted
      ? 'bg-green-100 text-green-700 border border-green-300'
      : 'bg-red-100 text-red-600 border border-red-300';

    const avatarLetter = (ex.agent || 'F').charAt(0).toUpperCase();
    const agentColor   = ex.color || '#6366f1';
    const agentName    = ex.agent_name || 'Frontier MCP';
    const exchangeType = ex.demo_mode ? 'Demo Mode' : 'ID-JAG Exchange';
    const badgeClass   = isGranted ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600';
    const badgeText    = isGranted ? '✓ Granted' : '✗ Denied';

    const scopePills = scopesToShow
      .map(s => `<span class="px-2 py-0.5 text-[10px] rounded-full font-mono ${scopeClass}">${s}</span>`)
      .join('');

    const scopeBlock = scopesToShow.length ? `
      <div class="mt-1">
        <div class="text-[9px] text-slate-500 uppercase tracking-wide mb-1">${scopeLabel}</div>
        <div class="flex flex-wrap gap-1">${scopePills}</div>
      </div>` : '';

    const policyBlock = !isGranted ? `
      <div class="mt-2 flex items-center gap-1 text-[10px] text-slate-500">
        <svg class="w-3 h-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.955 11.955 0 003 12c0 6.627 5.373 12 12 12s12-5.373 12-12c0-2.25-.619-4.356-1.698-6.162M12 2.964z"/>
        </svg>
        Blocked by Okta governance policy
      </div>` : '';

    card.innerHTML = `
      <div class="flex items-start justify-between mb-2">
        <div class="flex items-center gap-2">
          <div class="w-7 h-7 rounded-lg flex items-center justify-center text-white text-xs font-bold"
               style="background:${agentColor}">${avatarLetter}</div>
          <div>
            <div class="text-xs font-semibold text-slate-800">${agentName}</div>
            <div class="text-[10px] text-slate-400">${exchangeType}</div>
          </div>
        </div>
        <span class="text-[10px] font-semibold px-2 py-0.5 rounded-full ${badgeClass}">${badgeText}</span>
      </div>
      ${scopeBlock}${policyBlock}`;

    panel.appendChild(card);
  });
}

// ---------------------------------------------------------------------------
// Very minimal markdown-ish formatter (no library dependency)
// ---------------------------------------------------------------------------

function formatText(text) {
  // Escape HTML first
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

  // Bullet lists (lines starting with - or *)
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
