"use strict";
const $ = id => document.getElementById(id);
let config = null, state = null, busy = false;
let pendingGuess = null, lastAnnouncement = "";
try { pendingGuess = JSON.parse(sessionStorage.getItem("blockword_pending_guess") || "null"); } catch {}
function savePending(value) {
  pendingGuess = value;
  try {
    if (value) sessionStorage.setItem("blockword_pending_guess", JSON.stringify(value));
    else sessionStorage.removeItem("blockword_pending_guess");
  } catch { /* keep retries working in this tab if storage is blocked. */ }
}
function reconcilePending() {
  if (!pendingGuess || !state) return;
  if (pendingGuess.player !== state.player || pendingGuess.expected_round !== state.round_id ||
      state.board[pendingGuess.expected_attempt - 1]?.word === pendingGuess.word) savePending(null);
}
const input = $("guess-input");
const meanings = ["no unused copy in the answer", "in another position", "correct position"];
const short = address => `${address.slice(0, 8)}…${address.slice(-6)}`;
const explorer = (kind, value) => `https://explorer.aptoslabs.com/${kind}/${value}?network=devnet`;

function status(text, error = false) {
  $("status").textContent = text;
  $("status").className = `status${error ? " error" : ""}${busy ? " busy" : ""}`;
}

async function api(path, body) {
  const options = {credentials: "same-origin"};
  if (body !== undefined) {
    options.method = "POST";
    options.headers = {"Content-Type": "application/json"};
    options.body = JSON.stringify(body);
  }
  let response, value;
  try { response = await fetch(path, options); }
  catch { throw new Error("Connection lost. Check your connection, then choose Check & finish verification. Your guess is saved in this tab."); }
  try { value = await response.json(); }
  catch { throw new Error("The server returned an unreadable response. Check & finish verification before submitting again."); }
  if (!response.ok) {
    const detail = typeof value.detail === "string" ? value.detail : "Please enter a five-letter term from the list.";
    const error = new Error(detail); error.status = response.status; throw error;
  }
  return value;
}

function renderBoard() {
  const board = $("board"); board.replaceChildren();
  for (let r = 0; r < 6; r++) {
    const row = document.createElement("div"); row.className = "board-row"; row.setAttribute("role", "row");
    const guess = state?.board[r];
    const current = state && !state.finished && r === state.board.length;
    if (current) row.classList.add("current");
    const word = guess?.word || (current ? input.value.toLowerCase() : "");
    for (let c = 0; c < 5; c++) {
      const tile = document.createElement("div");
      const feedback = guess ? ["absent", "elsewhere", "exact"][guess.feedback[c]] : word[c] ? "typed" : "";
      tile.className = `tile ${feedback}`; tile.textContent = word[c] || "";
      tile.setAttribute("role", "cell");
      tile.setAttribute("aria-label", word[c] ? `${word[c].toUpperCase()}, ${guess ? meanings[guess.feedback[c]] : "entered"}` : `Row ${r + 1}, letter ${c + 1}, empty`);
      row.append(tile);
    }
    board.append(row);
  }
}

function renderKeyboard() {
  const known = {};
  for (const guess of state?.board || []) {
    [...guess.word].forEach((letter, i) => {known[letter] = Math.max(known[letter] ?? -1, guess.feedback[i]);});
  }
  $("keyboard").replaceChildren();
  for (const keys of ["qwertyuiop", "asdfghjkl", "↵zxcvbnm⌫"]) {
    const row = document.createElement("div"); row.className = "key-row";
    for (const letter of keys) {
      const key = document.createElement("button"); key.type = "button";
      key.className = `key${letter === "↵" || letter === "⌫" ? " wide" : ""}${known[letter] !== undefined ? ` ${["absent", "elsewhere", "exact"][known[letter]]}` : ""}`;
      key.textContent = letter.toUpperCase(); key.disabled = busy;
      key.setAttribute("aria-label", letter === "↵" ? "Submit guess" : letter === "⌫" ? "Delete letter" : `${letter.toUpperCase()}${known[letter] !== undefined ? `, ${meanings[known[letter]]}` : ""}`);
      key.addEventListener("click", () => {
        if (letter === "↵") {submitGuess(); return;}
        input.value = letter === "⌫" ? input.value.slice(0, -1) : (input.value + letter).slice(0, 5);
        renderBoard();
      });
      row.append(key);
    }
    $("keyboard").append(row);
  }
}

function render() {
  const active = Boolean(state?.round_id && !state.finished);
  $("start-area").hidden = Boolean(state?.round_id);
  $("guess-form").hidden = !active; $("keyboard").hidden = !active;
  $("forfeit-button").hidden = !active;
  $("result").hidden = !state?.verified;
  $("round-label").textContent = state?.round_id ? `ROUND ${String(state.round_id).padStart(2, "0")}` : "READY WHEN YOU ARE";
  $("attempts").textContent = `${state?.board.length || 0} / 6 GUESSES`;
  $("verification-label").textContent = state?.verified ? "✓ VERIFIED ON APTOS" : state?.round_id ? "ANSWER COMMITTED" : "COMMIT → PLAY → VERIFY";
  $("wins").textContent = state?.passport.wins || 0;
  $("rounds").textContent = state?.passport.verified_rounds || 0;
  if (state?.player) {
    $("player-link").href = explorer("account", state.player);
    $("player-link").textContent = `${short(state.player)} ↗`;
    $("player-link").title = state.player;
  }
  if (config?.deployment.explorer) $("contract-link").href = config.deployment.explorer;
  if (state?.verified) {
    $("answer").textContent = state.answer;
    $("definition").textContent = state.definition;
  }
  if (state?.receipts.length) {
    $("receipts").replaceChildren();
    for (const receipt of [...state.receipts].reverse().slice(0, 4)) {
      const link = document.createElement("a"); link.className = "receipt";
      link.href = explorer("txn", receipt.hash); link.target = "_blank"; link.rel = "noopener noreferrer";
      const text = document.createElement("span"), title = document.createElement("span"), hash = document.createElement("span");
      title.className = "receipt-name"; hash.className = "receipt-hash";
      title.textContent = {fund: "Test APT added", start: "Answer committed", guess: "Guess recorded", reveal: "Round verified", forfeit: "Round ended"}[receipt.kind] || receipt.kind;
      hash.textContent = short(receipt.hash); text.append(title, hash);
      const check = document.createElement("span"); check.className = "receipt-check";
      check.textContent = receipt.status === "confirmed" ? "✓ ↗" : ["failed","expired"].includes(receipt.status) ? "×" : "◌";
      check.setAttribute("aria-label", {confirmed:"Confirmed",submitted:"Waiting for confirmation",failed:"Failed",expired:"Expired before completion"}[receipt.status] || receipt.status); link.append(text, check); $("receipts").append(link);
    }
  }
  renderBoard(); renderKeyboard();
  document.querySelectorAll("#start-button,#again-button,#guess-button,#forfeit-button,#refresh-button,#share-button").forEach(button => {button.disabled = busy || !config?.ready;});
  input.disabled = busy;
  const last = state?.board.at(-1);
  const announcementId = `${state?.round_id}/${state?.board.length}`;
  if (last && announcementId !== lastAnnouncement) {
    $("board-announcement").textContent = `Guess ${state.board.length}: ${last.word.toUpperCase()}. ${[...last.word].map((c,i)=>`${c.toUpperCase()}, ${meanings[last.feedback[i]]}`).join(". ")}.`;
    lastAnnouncement = announcementId;
  }
}

function restingStatus() {
  if (!state?.round_id) return "Start a round to guess a five-letter crypto term.";
  if (state.verified) return state.won ? `Found in ${state.board.length}. The contract checked every guess. Nice work.` : "Round verified. Read the answer and its definition below.";
  if (state.finished) return "The round has ended. Choose Check & finish verification to publish the answer and check the result.";
  if (state.receipts.some(receipt=>receipt.status === "submitted")) return "A request is waiting for confirmation. Check & finish verification before another guess.";
  return state.board.length ? "Your guess is recorded on Aptos devnet. What fits next?" : "The answer is committed. Make your first guess.";
}

async function run(action, waiting, clearDraft = true) {
  if (busy) return;
  busy = true; render(); status(waiting);
  try {
    const savedGuess = pendingGuess;
    state = await action(); reconcilePending();
    if (clearDraft || (savedGuess && !pendingGuess && input.value.toLowerCase() === savedGuess.word)) input.value = "";
    busy = false; render(); status(restingStatus()); return true;
  }
  catch (error) {busy = false; render(); status(error.message, true); return false;}
}

async function submitGuess() {
  if (busy || !state || state.finished) return;
  const word = input.value.toLowerCase();
  if (!config.words.includes(word)) {status("Pick a five-letter crypto term from the word list.", true); return;}
  reconcilePending();
  if (pendingGuess && pendingGuess.word !== word) {status("Check & finish verification for your saved guess before entering a different word.", true); return;}
  if (!pendingGuess) savePending({word, request_id:crypto.randomUUID(), player:state.player,
    expected_round:state.round_id, expected_attempt:state.board.length + 1});
  if (await run(() => api("/api/guess", pendingGuess), "Recording your guess on Aptos devnet…")) savePending(null);
}

$("guess-form").addEventListener("submit", event => {event.preventDefault(); submitGuess();});
input.addEventListener("input", () => {input.value = input.value.replace(/[^a-z]/gi, "").slice(0, 5); renderBoard();});
$("start-button").addEventListener("click", () => run(() => api("/api/start", {}), "Funding your demo wallet and committing the answer…"));
$("again-button").addEventListener("click", () => run(() => api("/api/start", {}), "Committing your next word…"));
$("refresh-button").addEventListener("click", () => {
  if (!state) {status("Start a round to create your first receipt."); return;}
  run(() => api("/api/recover", {}), "Checking saved requests and finishing verification if needed…", false);
});
$("forfeit-button").addEventListener("click", () => run(() => api("/api/forfeit", {}), "Ending the round and checking the answer on-chain…"));
$("share-button").addEventListener("click", async () => {
  const colors = ["⬜", "🟨", "🟩"];
  const text = `Blockword ${state.won ? state.board.length : "X"}/6 · verified on Aptos devnet\n${state.board.map(row => row.feedback.map(n => colors[n]).join("")).join("\n")}\n${explorer("account", state.player)}`;
  try {await navigator.clipboard.writeText(text); status("Result copied. Leave the answer as a surprise.");}
  catch {status("Clipboard access is unavailable in this browser.", true);}
});
$("words-button").addEventListener("click", () => $("words-dialog").showModal());
$("mobile-words-button").addEventListener("click", () => $("words-dialog").showModal());
$("how-button").addEventListener("click", () => $("how-dialog").showModal());
document.querySelectorAll(".close-dialog").forEach(button => button.addEventListener("click", () => button.closest("dialog").close()));
document.querySelectorAll("dialog").forEach(dialog => dialog.addEventListener("click", event => {if (event.target === dialog) {const box = dialog.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();}}));

async function init() {
  renderBoard();
  try {
    config = await api("/api/config");
    for (const word of config.words) {
      const button = document.createElement("button"); button.className = "word-chip"; button.textContent = word;
      button.addEventListener("click", () => {
        $("words-dialog").close();
        if (state && !state.finished && !busy) {input.value = word; renderBoard(); input.focus();}
      });
      $("word-list").append(button);
    }
    if (config.ready) {
      try {state = await api("/api/state");}
      catch (error) {if (error.status !== 401) throw error;}
      reconcilePending(); render(); status(restingStatus());
    } else {render(); status("Local setup is incomplete. See the README for setup and deployment steps.", true);}
  } catch (error) {render(); status(error.message, true);}
}
init();
