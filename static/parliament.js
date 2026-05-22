/**
 * Agent Parliament — real-world case debates via API (signed contracts on server).
 */
(function () {
  const JURY_SLOTS = 5;

  let state = {
    contractId: null,
    sessionId: null,
    caseId: null,
    status: 'idle',
    phase: 'idle',
    playing: false,
    proposerName: 'Proposer',
    responderName: 'Responder',
    pollVotes: {},
    selectedPoll: null,
    contract: null,
    poll: null,
    cases: [],
    verdictMap: {},
  };

  function $(id) {
    return document.getElementById(id);
  }

  function bangGavel() {
    const g = $('gavelBlock');
    if (!g) return;
    g.classList.remove('bang');
    void g.offsetWidth;
    g.classList.add('bang');
  }

  function setPhase(label) {
    const el = $('sessionPhase');
    if (el) el.textContent = label;
  }

  function setSpeaking(side) {
    const proposer = $('agentProposer');
    const responder = $('agentResponder');
    if (proposer) proposer.classList.toggle('speaking', side === 'proposer');
    if (responder) responder.classList.toggle('speaking', side === 'responder');
    if (side !== 'proposer' && proposer) proposer.classList.remove('speaking');
    if (side !== 'responder' && responder) responder.classList.remove('speaking');
  }

  function addTranscript(side, speaker, text) {
    const box = $('debateTranscript');
    if (!box) return;
    const line = document.createElement('div');
    line.className = `transcript-line ${side}`;
    line.innerHTML = `<div class="speaker">${escapeHtml(speaker)}</div><div>${escapeHtml(text)}</div>`;
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
  }

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function clearTranscript() {
    const box = $('debateTranscript');
    if (box) box.innerHTML = '';
  }

  function initJuryGallery() {
    const gallery = $('juryGallery');
    if (!gallery) return;
    gallery.innerHTML = '';
    for (let i = 0; i < JURY_SLOTS; i++) {
      const seat = document.createElement('div');
      seat.className = 'juror-seat';
      seat.id = `jurorSeat${i}`;
      seat.innerHTML = `<span class="juror-emoji">👤</span><span class="juror-label">Seat ${i + 1}</span>`;
      gallery.appendChild(seat);
    }
  }

  function fillJury(count) {
    for (let i = 0; i < JURY_SLOTS; i++) {
      const seat = $(`jurorSeat${i}`);
      if (!seat) continue;
      if (i < count) {
        seat.classList.add('filled');
        seat.querySelector('.juror-emoji').textContent = '⚖️';
        seat.querySelector('.juror-label').textContent = i === 0 ? 'Foreperson' : `Juror ${i + 1}`;
      } else {
        seat.classList.remove('filled');
        seat.querySelector('.juror-emoji').textContent = '👤';
        seat.querySelector('.juror-label').textContent = `Seat ${i + 1}`;
      }
    }
  }

  function delay(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  async function speakLine(line) {
    const side = line.side;
    const speaker = line.speaker || (side === 'proposer' ? state.proposerName : side === 'responder' ? state.responderName : 'Clerk');
    if (side === 'proposer' || side === 'responder') {
      setSpeaking(side);
      const bubble = side === 'proposer' ? $('bubbleProposer') : $('bubbleResponder');
      if (bubble) bubble.textContent = line.text;
    } else {
      setSpeaking(null);
    }
    addTranscript(side, speaker, line.text);
    bangGavel();
    await delay(line.phase === 'poll_prompt' ? 1800 : 2400);
    setSpeaking(null);
    await delay(350);
  }

  function buildVerdictMap(poll) {
    state.verdictMap = {};
    (poll?.options || []).forEach((opt) => {
      state.verdictMap[opt.id] = {
        title: opt.verdict_title || 'Verdict: ' + opt.label,
        steps: (opt.next_steps || []).map((t) => ({ text: t, api: 'POST /agents/debate/sessions/{id}/verdict' })),
      };
    });
  }

  function loadPollVotes() {
    const key = `parliament_poll_${state.contractId || state.sessionId || 'none'}`;
    try {
      const raw = localStorage.getItem(key);
      state.pollVotes = raw ? JSON.parse(raw) : {};
    } catch {
      state.pollVotes = {};
    }
  }

  function savePollVotes() {
    const key = `parliament_poll_${state.contractId || state.sessionId || 'none'}`;
    localStorage.setItem(key, JSON.stringify(state.pollVotes));
  }

  function renderPoll() {
    const poll = state.poll;
    const ask = $('pollAgentAsk');
    const grid = $('pollOptionsGrid');
    if (!poll || !ask || !grid) return;
    ask.innerHTML = `<strong>Agents → Citizens:</strong> ${escapeHtml(poll.question)}`;
    grid.innerHTML = '';
    poll.options.forEach((opt) => {
      const votes = Object.values(state.pollVotes).filter((v) => v === opt.id).length;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'poll-option-btn' + (state.selectedPoll === opt.id ? ' selected' : '');
      btn.innerHTML = `${opt.icon || '•'} ${escapeHtml(opt.label)}<span class="poll-votes">${votes} vote${votes !== 1 ? 's' : ''}</span>`;
      btn.onclick = () => {
        state.selectedPoll = opt.id;
        renderPoll();
      };
      grid.appendChild(btn);
    });
    renderPollBars(poll);
  }

  function renderPollBars(poll) {
    const wrap = $('pollBarWrap');
    if (!wrap) return;
    const total = Math.max(Object.keys(state.pollVotes).length, 1);
    const counts = {};
    poll.options.forEach((o) => (counts[o.id] = 0));
    Object.values(state.pollVotes).forEach((id) => {
      if (counts[id] !== undefined) counts[id]++;
    });
    wrap.innerHTML = poll.options
      .map((opt) => {
        const n = counts[opt.id] || 0;
        const pct = Math.round((n / total) * 100);
        return `
        <div class="poll-bar-row">
          <div class="poll-bar-label"><span>${opt.icon || ''} ${escapeHtml(opt.label)}</span><span>${n} (${pct}%)</span></div>
          <div class="poll-bar-track"><div class="poll-bar-fill" style="width:${pct}%"></div></div>
        </div>`;
      })
      .join('');
  }

  async function castVote() {
    if (!state.selectedPoll) {
      alert('Select a verdict option before casting your vote.');
      return;
    }
    const voterId = $('pollVoterId')?.value?.trim() || `citizen_${Date.now()}`;
    state.pollVotes[voterId] = state.selectedPoll;
    savePollVotes();
    renderPoll();
    await determineVerdict();
  }

  async function determineVerdict() {
    const poll = state.poll;
    if (!poll) return;

    const counts = {};
    poll.options.forEach((o) => (counts[o.id] = 0));
    Object.values(state.pollVotes).forEach((id) => {
      if (counts[id] !== undefined) counts[id]++;
    });
    let winner = state.selectedPoll;
    let max = 0;
    Object.entries(counts).forEach(([id, n]) => {
      if (n > max) {
        max = n;
        winner = id;
      }
    });
    if (!winner || max === 0) return;

    let verdict = state.verdictMap[winner];
    if (state.sessionId) {
      try {
        const res = await fetch(`/agents/debate/sessions/${state.sessionId}/verdict`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ option_id: winner, claim_reward: true }),
        });
        const data = await res.json();
        if (res.ok && data.verdict) {
          verdict = {
            title: data.verdict.title,
            steps: data.verdict.steps || [],
          };
        }
        if (res.ok && data.reward) {
          if (data.reward.won) {
            verdict.title += ` — +${data.reward.reward_itn} ITN to your wallet`;
            verdict.steps.unshift({
              text: data.reward.reason,
              api: `Balance: ${data.reward.new_balance} ITN`,
            });
            window.CourtIdentity?.refresh?.();
            if (typeof loadItnWallet === 'function') loadItnWallet(true);
          } else if (data.reward.reason) {
            verdict.steps.unshift({
              text: data.reward.reason,
              api: 'No ITN reward this case',
            });
          }
        }
      } catch (e) {
        console.warn('Verdict API:', e);
      }
    }

    if (!verdict) {
      verdict = { title: 'Verdict recorded', steps: [{ text: 'Chamber records citizen mandate.' }] };
    }

    const section = $('verdictSection');
    const outcome = $('verdictOutcome');
    const steps = $('nextStepsList');
    if (section) section.classList.add('visible');
    if (outcome) outcome.textContent = verdict.title;
    if (steps) {
      steps.innerHTML = verdict.steps
        .map(
          (s) =>
            `<li>${escapeHtml(s.text || s)}<span class="step-api">${escapeHtml(s.api || '')}</span></li>`
        )
        .join('');
    }
    addTranscript('clerk', 'Clerk of the Chamber', `The citizen verdict is proclaimed: ${verdict.title}`);
  }

  function updateStatusPill() {
    const pill = $('parliamentStatusPill');
    if (pill) {
      const st = (state.status || 'idle').replace(/\s/g, '_');
      pill.className = `parliament-status-pill ${st}`;
      pill.textContent = (state.status || 'idle').replace(/_/g, ' ');
    }
    const meta = $('parliamentContractMeta');
    if (meta) {
      const title = state.cases.find((c) => c.id === state.caseId)?.title || state.caseId || '';
      meta.textContent = state.contractId
        ? `${title} · Contract ${state.contractId}`
        : 'Select a real-world case and open session';
    }
    const summary = $('caseSummaryBox');
    if (summary && state.caseId) {
      const c = state.cases.find((x) => x.id === state.caseId);
      if (c) summary.textContent = c.summary || '';
    }
  }

  async function loadCases() {
    try {
      const res = await fetch('/agents/debate/cases');
      state.cases = await res.json();
      const sel = $('debateCaseSelect');
      if (!sel) return;
      sel.innerHTML = '<option value="">— Select a case —</option>';
      const groups = {};
      state.cases.forEach((c) => {
        const cat = c.category || 'general';
        if (!groups[cat]) groups[cat] = [];
        groups[cat].push(c);
      });
      Object.keys(groups)
        .sort()
        .forEach((cat) => {
          const og = document.createElement('optgroup');
          og.label = cat.charAt(0).toUpperCase() + cat.slice(1);
          groups[cat].forEach((c) => {
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = c.title;
            og.appendChild(opt);
          });
          sel.appendChild(og);
        });
      sel.onchange = () => {
        state.caseId = sel.value;
        const c = state.cases.find((x) => x.id === state.caseId);
        if (c) {
          state.proposerName = c.proposer_role;
          state.responderName = c.responder_role;
          $('agentProposerName').textContent = c.proposer_role;
          $('agentResponderName').textContent = c.responder_role;
        }
        updateStatusPill();
      };
    } catch (e) {
      console.error('Failed to load cases', e);
    }
  }

  async function startRealDebate() {
    const caseId = $('debateCaseSelect')?.value || state.caseId;
    if (!caseId) {
      alert('Select a real-world case first.');
      return;
    }
    const playerDid = window.CourtIdentity?.getPlayerOwnerDid?.() || '';
    if (!playerDid) {
      alert('Create your DID and enroll in court (section above) before opening a session.');
      document.getElementById('courtPanel')?.scrollIntoView({ behavior: 'smooth' });
      return;
    }
    const playerSide = window.CourtIdentity?.getPlayerSide?.() || 'proposer';
    if (state.playing) return;
    state.playing = true;
    state.caseId = caseId;
    clearTranscript();
    fillJury(0);
    $('verdictSection')?.classList.remove('visible');
    setPhase('Convening chamber…');
    $('btnParliamentPlay').disabled = true;

    try {
      const res = await fetch('/agents/debate/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          case_id: caseId,
          use_llm: $('useLlmDebate')?.checked || false,
          player_owner_did: playerDid,
          player_side: playerSide,
        }),
      });
      const session = await res.json();
      if (!res.ok) throw new Error(session.detail || res.statusText);

      state.sessionId = session.session_id;
      state.contractId = session.contract_id;
      state.contract = session;
      state.status = session.status || 'delivered';
      if (session.player_counsel_name && session.player_side === 'proposer') {
        state.proposerName = session.player_counsel_name;
        state.responderName = session.responder_role;
      } else if (session.player_counsel_name && session.player_side === 'responder') {
        state.proposerName = session.proposer_role;
        state.responderName = session.player_counsel_name;
      } else {
        state.proposerName = session.proposer_role;
        state.responderName = session.responder_role;
      }
      state.poll = session.poll;
      buildVerdictMap(session.poll);
      $('agentProposerName').textContent = session.proposer_role;
      $('agentResponderName').textContent = session.responder_role;
      $('pollContractId').value = session.contract_id;
      loadPollVotes();
      updateStatusPill();

      const lines = session.transcript || [];
      for (const line of lines) {
        if (!state.playing) break;
        if (line.phase === 'offer') setPhase('Opening arguments');
        if (line.phase === 'counter') setPhase('Debate — opposing arguments');
        if (line.phase === 'accept') setPhase('Motion to accept');
        if (line.phase === 'deliver') setPhase('Delivery & resolution');
        if (line.phase === 'poll_prompt') setPhase('Citizen poll');
        await speakLine(line);
      }

      setPhase('Jury of the chamber');
      addTranscript('clerk', 'Clerk', 'Citizens may witness this contract. Jury seats open for attestation.');
      for (let i = 0; i < Math.min(2, JURY_SLOTS); i++) {
        await delay(500);
        fillJury(i + 1);
      }

      state.status = 'delivered';
      updateStatusPill();
      renderPoll();
      $('citizenPollSection')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      setPhase('Awaiting citizen verdict');
    } catch (e) {
      alert('Debate failed: ' + e.message);
      setPhase('Error');
    } finally {
      state.playing = false;
      $('btnParliamentPlay').disabled = false;
    }
  }

  function stopSession() {
    state.playing = false;
    setSpeaking(null);
    setPhase('Session paused');
  }

  function resetSession() {
    stopSession();
    state.contractId = null;
    state.sessionId = null;
    state.contract = null;
    state.status = 'idle';
    state.poll = null;
    state.pollVotes = {};
    state.selectedPoll = null;
    clearTranscript();
    fillJury(0);
    if ($('bubbleProposer')) $('bubbleProposer').textContent = 'Select a case…';
    if ($('bubbleResponder')) $('bubbleResponder').textContent = 'Select a case…';
    $('verdictSection')?.classList.remove('visible');
    $('pollContractId').value = '';
    updateStatusPill();
    renderPoll();
  }

  async function loadContractFromApi() {
    const id = $('pollContractId')?.value?.trim();
    if (!id) {
      alert('Enter a contract ID');
      return;
    }
    try {
      const res = await fetch(`/agents/contracts/${id}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      state.contractId = data.contract_id;
      state.contract = data;
      state.status = data.status || 'open';
      const terms = data.terms || {};
      state.poll = terms.poll || state.poll;
      if (terms.case_id) state.caseId = terms.case_id;
      buildVerdictMap(state.poll);
      state.proposerName = terms.debate_title ? data.proposer_agent_did?.slice(-20) : 'Proposer';
      state.responderName = data.responder_agent_did?.slice(-20) || 'Responder';
      $('agentProposerName').textContent = state.proposerName;
      $('agentResponderName').textContent = state.responderName;
      updateStatusPill();
      clearTranscript();
      fillJury(data.witnesses?.length || 0);
      const msgs = data.messages || [];
      for (const m of msgs) {
        const side = m.agent_did === data.proposer_agent_did ? 'proposer' : 'responder';
        const text = m.body?.argument || m.body?.delivery_log?.resolution || JSON.stringify(m.body || {}).slice(0, 300);
        await speakLine({ side, speaker: side === 'proposer' ? state.proposerName : state.responderName, text });
      }
      loadPollVotes();
      renderPoll();
    } catch (e) {
      alert('Could not load contract: ' + e.message);
    }
  }

  async function fetchParliamentStats() {
    try {
      const res = await fetch('/agents/parliament/stats');
      const data = await res.json();
      const el = $('parliamentStatsLine');
      if (el) {
        el.textContent = `${data.agents} agents · ${data.contracts} contracts · ${data.debate_cases || 0} debate cases`;
      }
    } catch {
      /* ignore */
    }
  }

  window.ParliamentChamber = {
    start: startRealDebate,
    stop: stopSession,
    reset: resetSession,
    loadContract: loadContractFromApi,
    castVote: castVote,
    determineVerdict: determineVerdict,
  };

  document.addEventListener('DOMContentLoaded', function () {
    initJuryGallery();
    loadCases();
    loadPollVotes();
    updateStatusPill();
    fetchParliamentStats();
    $('btnParliamentPlay')?.addEventListener('click', startRealDebate);
    $('btnParliamentStop')?.addEventListener('click', stopSession);
    $('btnParliamentReset')?.addEventListener('click', resetSession);
    $('btnParliamentLoad')?.addEventListener('click', loadContractFromApi);
    $('btnCastVote')?.addEventListener('click', castVote);
    $('btnDetermineVerdict')?.addEventListener('click', determineVerdict);
  });
})();
