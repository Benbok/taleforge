// Журнал мастера: ходы мастера, вызовы инструментов, броски и обращения к модели. Только Admin и Super Admin.
const ML_STATUS = { done: "готово", failed: "сбой", running: "идёт" };
const ML_PURPOSE = { decide: "решение", narrate: "повествование", parse: "разбор реплики", summary: "сводка", review: "проверка героя" };

function mlIsAdmin() { return me && (me.platform_role === "admin" || me.platform_role === "super_admin"); }
function mlOpen() { return !$("masterLogCard").classList.contains("hidden"); }

function masterLogOnRoom() {
  $("masterLogBtn").classList.toggle("hidden", !mlIsAdmin());
  $("masterLogCard").classList.add("hidden");
}

function mlTime(s) { return s ? new Date(s).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""; }
function mlPairs(o) { return Object.entries(o || {}).map(([k, v]) => `${esc(k)}=<b>${esc(v)}</b>`).join(", "); }

function mlCall(c) {
  if (c.args === undefined) return `<li class="secret">${esc(c.tool)} — скрытое действие <span class="muted">(содержимое в журнале отключено)</span></li>`;
  const flags = [c.secret ? '<span class="badge">скрыто</span>' : "", c.routed ? '<span class="badge">сервер</span>' : "", c.auto ? '<span class="badge">авто</span>' : ""].join(" ");
  const res = c.error ? `<span class="bad">✗ ${esc(c.error)}</span>` : c.result && Object.keys(c.result).length ? "→ " + mlPairs(c.result) : c.ok ? "✓" : "";
  return `<li${c.secret ? ' class="secret"' : ""}><b>${esc(c.tool)}</b>(${mlPairs(c.args)}) ${res} ${flags}</li>`;
}

function mlLlm(x) {
  return `<li>${ML_PURPOSE[x.purpose] || esc(x.purpose)} · ${esc(x.model)} · ${x.tokens_in}→${x.tokens_out} ток. · ${x.latency_ms} мс · $${x.cost.toFixed(4)}${x.error ? ` <span class="bad">✗ ${esc(x.error)}</span>` : ""}</li>`;
}

function mlTurn(t) {
  const cost = t.llm.reduce((a, x) => a + x.cost, 0);
  const head = `${mlTime(t.started_at)} · ${ML_STATUS[t.status] || esc(t.status)} · реплики ${t.seq[0] ?? "—"}–${t.seq[1]} · вызовов ${t.calls.length} · $${cost.toFixed(4)}`;
  const parts = [];
  if (t.error) parts.push(`<div class="bad">${esc(t.error)}</div>`);
  if (t.advance) parts.push(`<div class="muted">Ход существ: ${esc(t.advance)}</div>`);
  if (t.calls.length) parts.push(`<div>Инструменты:</div><ul>${t.calls.map(mlCall).join("")}</ul>`);
  if (t.combat.length) parts.push(`<div>Бой:</div><ul>${t.combat.map(n => `<li>${esc(n)}</li>`).join("")}</ul>`);
  if (t.audit && (t.audit.regenerated || t.audit.stripped.length))
    parts.push(`<div>Разметка: ${t.audit.regenerated ? "текст переписан" : ""}${t.audit.stripped.length ? `, снято: ${esc(t.audit.stripped.join(", "))}` : ""}</div>`);
  if (t.llm.length) parts.push(`<div>Модель:</div><ul>${t.llm.map(mlLlm).join("")}</ul>`);
  return `<details${t.status === "failed" ? " open" : ""}><summary${t.status === "failed" ? ' class="bad"' : ""}>${head}</summary>${parts.join("")}</details>`;
}

async function masterLogLoad() {
  $("mlErr").textContent = "";
  try {
    const log = await api(`/api/campaigns/${room.id}/master-log`);
    $("mlNote").textContent = log.secrets_visible ? " · скрытые броски и шёпот показаны" : " · скрытые действия без содержимого";
    let html = "", session;
    for (const t of log.turns) {
      if (t.session_id !== session) { session = t.session_id; html += `<p class="muted" style="margin:8px 0 2px">Сессия ${esc(session || "—")}</p>`; }
      html += mlTurn(t);
    }
    if (log.service_llm.length) html += `<details><summary class="muted">Служебные вызовы модели (${log.service_llm.length})</summary><ul>${log.service_llm.map(x => mlLlm(x).replace("<li>", `<li>${mlTime(x.at)} · `)).join("")}</ul></details>`;
    // открытые ходы остаются открытыми после обновления
    const open = new Set([...$("mlBody").querySelectorAll("details[open] summary")].map(s => s.textContent));
    $("mlBody").innerHTML = html || '<p class="muted">Мастер ещё не делал ходов.</p>';
    $("mlBody").querySelectorAll("details summary").forEach(s => { if (open.has(s.textContent)) s.parentElement.open = true; });
  } catch (e) { $("mlErr").textContent = e.message; }
}

function masterLogRefresh() { if (room && mlOpen()) masterLogLoad(); }

$("masterLogBtn").onclick = () => { $("masterLogCard").classList.remove("hidden"); masterLogLoad(); };
$("mlRefresh").onclick = masterLogLoad;
$("mlClose").onclick = () => $("masterLogCard").classList.add("hidden");
