/* Shared by the metaloop pages (each chain's live page, the plan page): connecting to the page's database, comments and
   viewer; asking Claude from the page (Send to Claude, so the thread wakes the main session); showing Claude's answers,
   which the main session writes to the db "replies" collection (owner-only), keyed by the item's id or q-*. */
var TwoWay = (function () {
  var comments = null, user = null, myId = '';
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function date(iso) { var d = new Date(iso); return isNaN(d) ? null : d; }
  function fmt(iso) { var d = date(iso); return d ? d.toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'}) : String(iso || ''); }
  function hhmm(iso) { var d = date(iso); return d ? d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}) : String(iso || ''); }
  function ago(iso) {
    var d = date(iso); if (!d) return '';
    var m = Math.round((Date.now() - d.getTime()) / 60000);
    return m < 1 ? 'just now' : m < 60 ? m + ' min ago' : m < 1440 ? Math.round(m / 60) + ' h ago' : fmt(iso);
  }
  function paras(box, text) {
    box.textContent = '';
    String(text || '').split(/\n{2,}/).forEach(function (t) { t = t.trim(); if (t) box.appendChild(el('p', null, t)); });
  }
  function errorText(e) {
    var c = e && e.code;
    if (c === 'consent_required') return 'Not sent: allow this page to comment for you, then try again.';
    if (c === 'claude_unavailable') return 'Not sent: Claude can’t take questions from this view. Leave a comment instead.';
    if (c === 'rate_limited') return 'Not sent: too many at once. Try again in a minute.';
    if (c === 'forbidden') return 'Commenting from this page is off here.';
    return 'Not sent. Try again.';
  }
  /* Post text as a comment at target AND send it to Claude. Falls back to the plain composer when sending can't go through.
     Settles once the send has gone or failed: keep the button off until then, or a second click sends it twice. */
  function send(target, label, text, st, done) {
    if (!comments) { st.textContent = 'Open the published page to send this to Claude.'; return Promise.resolve(); }
    return comments.canSendToClaude().then(null, function () { return 'off'; }).then(function (v) {
      if (v !== 'available') {
        return comments.openComposer({element: target}).then(function () {
          st.textContent = v === 'writers_only' ? 'Only editors can send to Claude, so a plain comment box is open instead.'
            : v === 'no_session' ? 'Claude isn’t connected right now. Leave a comment; it is answered when Claude is back.'
            : 'Leave a comment here instead.';
        }, function () { st.textContent = 'Comments are off in this view.'; });
      }
      st.textContent = 'Sending…';
      return comments.anchorFor(target).then(function (anchor) {
        return comments.sendToClaude({anchor: anchor, text: (label + ': ' + text).slice(0, 3900)});
      }).then(function () { st.textContent = 'Sent. Claude answers in the comment thread and on this page.'; if (done) done(); },
        function (e) { st.textContent = errorText(e); });
    });
  }
  /* Tell Claude something the viewer just did on the page (an answer, an approval, a sign-off), when it can be sent. */
  function notify(target, text, st) {
    if (!comments) return;
    comments.canSendToClaude().then(function (v) {
      if (v !== 'available') return;
      return comments.anchorFor(target).then(function (anchor) { return comments.sendToClaude({anchor: anchor, text: text.slice(0, 3900)}); })
        .then(function () { if (st) st.textContent += ' Claude has been told.'; }, function () {});
    }, function () {});
  }
  function attachAsk(target, label, mount) {
    var wrap = el('div', 'ask');
    var btn = el('button', 'askbtn', 'Ask Claude about this'); btn.type = 'button';
    var box = el('div', 'askbox'); box.hidden = true;
    var ta = el('textarea'); ta.rows = 2; ta.maxLength = 3500; ta.placeholder = 'Your question, or the change you want';
    ta.setAttribute('aria-label', 'Your question for Claude about ' + label);
    var row = el('div', 'row');
    var go = el('button', 'btn sm', 'Send to Claude'); go.type = 'button';
    var cancel = el('button', 'btn sm sec', 'Cancel'); cancel.type = 'button';
    var st = el('p', 'askstate'); st.setAttribute('role', 'status');
    row.appendChild(go); row.appendChild(cancel); box.appendChild(ta); box.appendChild(row);
    wrap.appendChild(btn); wrap.appendChild(box); wrap.appendChild(st); mount.appendChild(wrap);
    btn.addEventListener('click', function () { st.textContent = ''; box.hidden = false; btn.hidden = true; ta.focus(); });
    cancel.addEventListener('click', function () { box.hidden = true; btn.hidden = false; btn.focus(); });
    go.addEventListener('click', function () {
      var text = ta.value.trim(); if (!text) { ta.focus(); return; }
      go.disabled = true;
      send(target, label, text, st, function () { ta.value = ''; box.hidden = true; btn.hidden = false; })
        .then(function () { go.disabled = false; });
    });
  }
  function reply(r) {
    var b = el('div', 'reply');
    b.appendChild(el('span', 'who', 'Claude' + (r.at ? ' · ' + fmt(r.at) : '')));
    var t = el('div', 'txt'); paras(t, r.text); b.appendChild(t);
    return b;
  }
  /* The free questions (replies q-*) in the order they were asked. */
  function questions(replies, mount) {
    mount.textContent = '';
    Object.keys(replies).filter(function (k) { return k.indexOf('q-') === 0; })
      .sort(function (a, b) { return String(replies[a].at || '').localeCompare(String(replies[b].at || '')); })
      .forEach(function (k) {
        var r = replies[k], item = el('div', 'qa-item');
        if (r.where) item.appendChild(el('span', 'where', r.where));
        if (r.question) item.appendChild(el('p', 'q', r.question));
        item.appendChild(reply(r)); mount.appendChild(item);
      });
    return mount.childNodes.length;
  }
  function watch(db, path, cb) {
    db.collection(path).onSnapshot(function (snap) {
      var out = {};
      (snap.docs || []).forEach(function (doc) { out[doc.id] = doc.data() || {}; });
      cb(out);
    }, function () {});
  }
  /* h.db(db), h.comments(c), h.status(text): called as each capability arrives (or can't). */
  function connect(h) {
    if (!(window.claude && typeof window.claude.use === 'function')) { h.status('Open the published page to see it live.'); return; }
    var timer = setTimeout(function () { h.status('This view can’t load the page’s data.'); }, 10000);
    window.claude.use('db').then(function (d) {
      clearTimeout(timer);
      if (!d) { h.status('This view can’t load the page’s data.'); return; }
      h.db(d);
    }, function () { clearTimeout(timer); h.status('This view can’t load the page’s data.'); });
    window.claude.use('user').then(function (u) {
      if (!u) return;
      user = u; u.id().then(function (id) { myId = id || ''; }, function () {});
    }, function () {});
    window.claude.use('comments').then(function (c) { if (c) { comments = c; if (h.comments) h.comments(c); } }, function () {});
  }
  return {el: el, fmt: fmt, hhmm: hhmm, ago: ago, paras: paras, send: send, notify: notify, attachAsk: attachAsk,
          reply: reply, questions: questions, watch: watch, connect: connect, me: function () { return myId; }};
})();
