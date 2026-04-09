/* Atko Assistant — unauthenticated landing page */

// Pre-scripted conversation tree
const CONVERSATIONS = {
  // Initial welcome — shown on page load
  welcome: {
    assistant: "Hello! I'm Atko Assistant, here to help you find answers as quickly as possible.\n\nMake sure to sign in to get started.",
    actions: [
      { text: 'Sign in', type: 'auth' },
      { text: 'What can you help with?', type: 'chat', key: 'capabilities' },
      { text: "I'm a new customer", type: 'chat', key: 'new_customer' },
      { text: 'View available plans', type: 'chat', key: 'plans' },
    ],
  },
  capabilities: {
    assistant: "I can help you manage your Frontier account, view your orders, explore available products and plans, and even add new subscriptions — all powered by secure identity flows through Okta.\n\nSign in to get started, or ask me more about what's available.",
    actions: [
      { text: 'Sign in', type: 'auth' },
      { text: "I'm a new customer", type: 'chat', key: 'new_customer' },
      { text: 'View available plans', type: 'chat', key: 'plans' },
    ],
  },
  new_customer: {
    assistant: "Welcome! As a new customer, you can explore our streaming and connectivity plans. Once you sign in with Okta, I can help you set up your account and add subscriptions.\n\nWhat would you like to do?",
    actions: [
      { text: 'Sign in to get started', type: 'auth' },
      { text: 'View available plans', type: 'chat', key: 'plans' },
      { text: 'What can you help with?', type: 'chat', key: 'capabilities' },
    ],
  },
  plans: {
    assistant: "Frontier offers a variety of streaming and connectivity plans including services like Paramount+, Disney+, and more. You can view full details and pricing after signing in.\n\nWould you like to sign in now?",
    actions: [
      { text: 'Sign in to explore plans', type: 'auth' },
      { text: 'What can you help with?', type: 'chat', key: 'capabilities' },
      { text: "I'm a new customer", type: 'chat', key: 'new_customer' },
    ],
  },
};

// ── Init ──

document.addEventListener('DOMContentLoaded', () => {
  showAssistantMessage(CONVERSATIONS.welcome);
});

// ── Rendering ──

function showAssistantMessage(convo) {
  const list = document.getElementById('message-list');

  // Assistant bubble
  const wrapper = document.createElement('div');
  wrapper.className = 'flex justify-start msg-appear';

  const bubble = document.createElement('div');
  bubble.className = 'bg-blue-50 rounded-2xl rounded-tl-sm px-5 py-4 max-w-lg text-sm text-slate-700 leading-relaxed prose';
  bubble.innerHTML = formatText(convo.assistant);
  wrapper.appendChild(bubble);
  list.appendChild(wrapper);

  // Quick-action pills (after a short delay for natural feel)
  setTimeout(() => {
    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'quick-actions flex flex-wrap justify-center gap-2 mt-3';

    convo.actions.forEach((action, i) => {
      const btn = document.createElement('button');
      btn.className = 'action-appear px-4 py-2 rounded-full border-2 border-blue-200 text-sm text-blue-700 hover:bg-blue-50 transition';
      btn.style.animationDelay = `${i * 0.08}s`;
      btn.textContent = action.text;

      if (action.type === 'auth') {
        btn.className = 'action-appear px-4 py-2 rounded-full border-2 border-blue-400 text-sm text-blue-700 font-medium hover:bg-blue-50 transition';
        btn.onclick = () => { window.location.href = '/auth/login'; };
      } else {
        btn.onclick = () => handleAction(action);
      }

      actionsDiv.appendChild(btn);
    });

    list.appendChild(actionsDiv);
    scrollBottom();
  }, 300);

  scrollBottom();
}

function handleAction(action) {
  const list = document.getElementById('message-list');

  // Remove previous quick-action buttons
  const prevActions = list.querySelectorAll('.quick-actions');
  prevActions.forEach(el => el.remove());

  // Show user message (right-aligned)
  const userWrapper = document.createElement('div');
  userWrapper.className = 'flex justify-end msg-appear';
  const userBubble = document.createElement('div');
  userBubble.className = 'bg-slate-100 rounded-2xl rounded-tr-sm px-5 py-3 max-w-lg text-sm text-slate-800';
  userBubble.textContent = action.text;
  userWrapper.appendChild(userBubble);
  list.appendChild(userWrapper);
  scrollBottom();

  // Show thinking dots, then assistant response
  const thinkingId = showThinking();
  setTimeout(() => {
    removeThinking(thinkingId);
    const convo = CONVERSATIONS[action.key];
    if (convo) {
      showAssistantMessage(convo);
    }
  }, 800);
}

function showThinking() {
  const id = 'thinking-' + Date.now();
  const list = document.getElementById('message-list');
  const wrapper = document.createElement('div');
  wrapper.id = id;
  wrapper.className = 'flex justify-start msg-appear';
  wrapper.innerHTML = `
    <div class="bg-blue-50 rounded-2xl rounded-tl-sm px-5 py-3 text-sm text-slate-400 dot-blink">
      Thinking<span>.</span><span>.</span><span>.</span>
    </div>`;
  list.appendChild(wrapper);
  scrollBottom();
  return id;
}

function removeThinking(id) {
  document.getElementById(id)?.remove();
}

function scrollBottom() {
  const messages = document.getElementById('messages');
  if (messages) messages.scrollTop = messages.scrollHeight;
}

// ── Minimal text formatter ──

function formatText(text) {
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Bold **...**
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  // Split into paragraphs on double newline
  const paragraphs = html.split('\n\n');
  return paragraphs.map(p => `<p>${p}</p>`).join('');
}
