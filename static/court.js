/**
 * Court enrollment — identity (DID) required, then agent + wallet for debate rewards.
 */
(function () {
  const STORAGE = {
    did: 'identitynet_did',
    pub: 'identitynet_public_key',
    priv: 'identitynet_private_key',
    userId: 'identitynet_user_id',
    agentDid: 'identitynet_court_agent_did',
    agentName: 'identitynet_court_agent_name',
  };

  function $(id) {
    return document.getElementById(id);
  }

  function loadIdentity() {
    return {
      did: localStorage.getItem(STORAGE.did) || '',
      publicKey: localStorage.getItem(STORAGE.pub) || '',
      privateKey: localStorage.getItem(STORAGE.priv) || '',
      userId: localStorage.getItem(STORAGE.userId) || '',
      agentDid: localStorage.getItem(STORAGE.agentDid) || '',
      agentName: localStorage.getItem(STORAGE.agentName) || '',
    };
  }

  function saveIdentity(data) {
    if (data.did) localStorage.setItem(STORAGE.did, data.did);
    if (data.publicKey) localStorage.setItem(STORAGE.pub, data.publicKey);
    if (data.privateKey) localStorage.setItem(STORAGE.priv, data.privateKey);
    if (data.userId) localStorage.setItem(STORAGE.userId, String(data.userId));
    if (data.agentDid) localStorage.setItem(STORAGE.agentDid, data.agentDid);
    if (data.agentName) localStorage.setItem(STORAGE.agentName, data.agentName);
    refreshUI();
  }

  function refreshUI() {
    const id = loadIdentity();
    if ($('courtOwnerDid')) $('courtOwnerDid').value = id.did;
    if ($('courtPublicKey')) $('courtPublicKey').value = id.publicKey;
    if ($('courtPrivateKey') && id.privateKey) $('courtPrivateKey').value = id.privateKey;
    if ($('courtAgentName') && id.agentName) $('courtAgentName').value = id.agentName;

    const status = $('courtIdentityStatus');
    const enrollBtn = $('btnCourtEnroll');
    if (status) {
      if (id.did) {
        status.innerHTML = `<span class="court-status-ok">Identity ready</span> · User #${id.userId || '?'}<div class="court-did-box">${id.did}</div>`;
        if (enrollBtn) enrollBtn.disabled = !id.privateKey;
      } else {
        status.innerHTML = '<span class="court-status-warn">No DID — complete step 1</span>';
        if (enrollBtn) enrollBtn.disabled = true;
      }
    }
    if (id.did) refreshCourtStatus();
  }

  async function refreshCourtStatus() {
    const id = loadIdentity();
    if (!id.did) return;
    const box = $('courtEnrollStatus');
    const walletBox = $('courtWalletBox');
    try {
      const res = await fetch(`/agents/court/status/${encodeURIComponent(id.did)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      if (data.court_enrolled) {
        saveIdentity({ agentDid: data.agent_did, agentName: data.agent_name });
        if (box) {
          box.innerHTML = `<span class="court-status-ok">Court agent active</span> · ${data.debate_wins} wins · ${data.ledger_balance} ITN`;
        }
        if (walletBox) {
          walletBox.style.display = 'block';
          walletBox.innerHTML = `Agent DID: ${data.agent_did}<br>Balance: ${data.wallet?.balance?.summary?.balance ?? data.ledger_balance} ITN`;
        }
        if ($('itnUserId') && data.user_id) {
          $('itnUserId').value = data.user_id;
        }
      } else if (box) {
        box.innerHTML = '<span class="court-status-warn">Not enrolled — complete step 2</span>';
        if (walletBox) walletBox.style.display = 'none';
      }
    } catch (e) {
      if (box) box.innerHTML = `<span class="text-danger">${e.message}</span>`;
    }
  }

  async function generateKeys() {
    try {
      const res = await fetch('/generate-keys');
      const data = await res.json();
      $('courtPublicKey').value = data.public_key;
      $('courtPrivateKey').value = data.private_key;
      saveIdentity({ publicKey: data.public_key, privateKey: data.private_key });
    } catch (e) {
      alert(e.message);
    }
  }

  function canonicalJson(obj) {
    const sortKeys = (o) => {
      if (Array.isArray(o)) return o.map(sortKeys);
      if (o && typeof o === 'object') {
        return Object.keys(o)
          .sort()
          .reduce((acc, k) => {
            acc[k] = sortKeys(o[k]);
            return acc;
          }, {});
      }
      return o;
    };
    return JSON.stringify(sortKeys(obj));
  }

  async function signRegistration(username, email, pub, priv) {
    const ts = new Date().toISOString();
    const payload = {
      action: 'register',
      username,
      email: email || null,
      public_key: pub,
      timestamp: ts,
    };
    const sig = await signCanonical(priv, canonicalJson(payload));
    return { signature: sig, timestamp: ts };
  }

  async function signCanonical(privHex, canonicalJson) {
    const priv = await crypto.subtle.importKey(
      'pkcs8',
      hexToPkcs8(privHex),
      { name: 'Ed25519' },
      false,
      ['sign']
    );
    const sig = await crypto.subtle.sign(
      'Ed25519',
      priv,
      new TextEncoder().encode(canonicalJson)
    );
    return bufToHex(sig);
  }

  function hexToPkcs8(hex) {
    const raw = hexToBuf(hex);
    const prefix = new Uint8Array([
      0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x04, 0x22, 0x04, 0x20,
    ]);
    const out = new Uint8Array(prefix.length + raw.length);
    out.set(prefix);
    out.set(raw, prefix.length);
    return out.buffer;
  }

  function hexToBuf(h) {
    const a = new Uint8Array(h.length / 2);
    for (let i = 0; i < a.length; i++) a[i] = parseInt(h.substr(i * 2, 2), 16);
    return a;
  }

  function bufToHex(buf) {
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
  }

  async function registerIdentity() {
    const username = $('courtUsername')?.value?.trim();
    const pub = $('courtPublicKey')?.value?.trim();
    const priv = $('courtPrivateKey')?.value?.trim();
    if (!username || !pub || !priv) {
      alert('Username, public key, and private key required');
      return;
    }
    try {
      const { signature, timestamp } = await signRegistration(username, null, pub, priv);
      const res = await fetch('/users/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          email: null,
          public_key: pub,
          registration_signature: signature,
          timestamp,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      saveIdentity({
        did: data.did,
        publicKey: pub,
        privateKey: priv,
        userId: data.id,
      });
      $('courtIdentityStatus').innerHTML = `<span class="court-status-ok">Registered</span><div class="court-did-box">${data.did}</div>`;
      $('btnCourtEnroll').disabled = false;
      if ($('itnUserId')) $('itnUserId').value = data.id;
      loadItnWallet && loadItnWallet(true);
    } catch (e) {
      alert('Register failed: ' + e.message);
    }
  }

  async function enrollCourt() {
    const id = loadIdentity();
    const agentName = $('courtAgentName')?.value?.trim() || 'Court_Counsel';
    if (!id.did || !id.publicKey || !id.privateKey) {
      alert('Complete identity step first');
      return;
    }
    const ts = new Date().toISOString();
    const payload = {
      action: 'court_enroll',
      owner_did: id.did,
      agent_name: agentName,
      public_key: id.publicKey,
      timestamp: ts,
    };
    try {
      const signature = await signCanonical(id.privateKey, canonicalJson(payload));
      const res = await fetch('/agents/court/enroll', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          owner_did: id.did,
          agent_name: agentName,
          public_key: id.publicKey,
          signature,
          timestamp: ts,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      saveIdentity({ agentDid: data.agent_did, agentName: data.agent_name });
      $('courtEnrollStatus').innerHTML = `<span class="court-status-ok">${data.message}</span>`;
      $('courtWalletBox').style.display = 'block';
      $('courtWalletBox').innerHTML = `Agent: ${data.agent_did}<br>ITN balance: ${data.ledger_balance}`;
      if ($('itnUserId')) $('itnUserId').value = data.user_id;
      if (typeof loadItnWallet === 'function') loadItnWallet(true);
    } catch (e) {
      alert('Enroll failed: ' + e.message);
    }
  }

  function getPlayerSide() {
    const r = document.querySelector('input[name="playerSide"]:checked');
    return r ? r.value : 'proposer';
  }

  function getPlayerOwnerDid() {
    return loadIdentity().did || '';
  }

  window.CourtIdentity = {
    load: loadIdentity,
    getPlayerSide,
    getPlayerOwnerDid,
    refresh: refreshCourtStatus,
  };

  document.addEventListener('DOMContentLoaded', function () {
    $('btnCourtGenKeys')?.addEventListener('click', generateKeys);
    $('btnCourtRegister')?.addEventListener('click', registerIdentity);
    $('btnCourtEnroll')?.addEventListener('click', enrollCourt);
    refreshUI();
  });
})();
