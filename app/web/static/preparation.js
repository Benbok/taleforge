// Подготовка кампании: анкета при создании и персоны ИИ-мастера (профиль, создание кампании, смена в комнате).
// Использует $, api, esc, room из index.html и modelProfiles-стиль выбора из profile.js.
let campOpts = null, myPersonas = [], editingPersona = null;

async function loadCampOpts() {
  if (!campOpts) campOpts = await api("/api/campaign-options");
  return campOpts;
}
function optionsHtml(map, selected, empty) {
  return (empty ? `<option value="">${esc(empty)}</option>` : "") +
    Object.entries(map).map(([k, v]) => `<option value="${esc(k)}" ${String(k) === String(selected) ? "selected" : ""}>${esc(v)}</option>`).join("");
}

// --- выбор персоны: создание кампании и комната ---
function personaOptions(selected) {
  const mine = myPersonas.map(p => `<option value="my:${p.id}" ${selected === "my:" + p.id ? "selected" : ""}>Моя: ${esc(p.name)}</option>`).join("");
  const presets = campOpts.presets.map(p => `<option value="pre:${p.id}" ${selected === "pre:" + p.id ? "selected" : ""}>${esc(p.name)}</option>`).join("");
  return `<option value="">Без персоны: мастер по умолчанию</option>${mine}${presets}`;
}
function personaStyle(v) {
  if (v.startsWith("my:")) return myPersonas.find(p => p.id === v.slice(3))?.style || "";
  if (v.startsWith("pre:")) return campOpts.presets.find(p => p.id === v.slice(4))?.style || "";
  return "";
}
function personaBody(v) {
  if (v.startsWith("my:")) return { persona_id: v.slice(3) };
  if (v.startsWith("pre:")) return { preset: v.slice(4) };
  return {};
}
function personaChoice(master) {
  if (master.type === "owner") return {};
  const b = personaBody($("cPersona").value);
  return b.preset ? { persona_preset: b.preset } : b;
}

// --- анкета кампании ---
async function fillPreparation() {
  const o = await loadCampOpts();
  myPersonas = await api("/api/me/master-personas").catch(() => []);
  $("cPersona").innerHTML = personaOptions("pre:storyteller"); showCreateStyle();
  $("bLength").innerHTML = optionsHtml(o.brief.length, "", "пусть решит мастер");
  $("bThreat").innerHTML = optionsHtml(o.brief.threat, "", "пусть решит мастер");
  $("bPillars").innerHTML = Object.entries(o.brief.pillars).map(([k, v]) =>
    `<div><label>${esc(v)}</label><select data-pillar="${k}">${optionsHtml(o.brief.amounts, "mid")}</select></div>`).join("");
  $("bEmotions").innerHTML = Object.entries(o.brief.emotions).map(([k, v]) =>
    `<label><input type="checkbox" data-emotion="${k}"> ${esc(v)}</label>`).join("");
  syncPersonaBox();
}
function showCreateStyle() {
  const s = personaStyle($("cPersona").value);
  $("cPersonaStyle").textContent = s; $("cPersonaStyle").classList.toggle("hidden", !s);
}
function syncPersonaBox() { $("cPersonaBox").classList.toggle("hidden", $("cMaster").value === "owner"); if ($("cMaster").value === "owner") $("cPersonaStyle").classList.add("hidden"); else showCreateStyle(); }
function briefBody() {
  const b = {};
  if ($("bLength").value) b.length = $("bLength").value;
  if ($("bThreat").value) b.threat = $("bThreat").value;
  const pillars = {};
  document.querySelectorAll("[data-pillar]").forEach(el => { if (el.value !== "mid") pillars[el.dataset.pillar] = el.value; });
  if (Object.keys(pillars).length) b.pillars = pillars;
  const emotions = [...document.querySelectorAll("[data-emotion]:checked")].map(el => el.dataset.emotion);
  if (emotions.length) b.emotions = emotions;
  if ($("bWishes").value.trim()) b.wishes = $("bWishes").value.trim();
  return b;
}
function excludedThemes() { return $("cExcluded").value.split(",").map(x => x.trim()).filter(Boolean).slice(0, 20); }

document.addEventListener("change", (ev) => {
  const t = ev.target;
  if (t.id === "cPersona") showCreateStyle();
  if (t.id === "cMaster") syncPersonaBox();
  if (t.dataset && t.dataset.emotion !== undefined) {
    const on = document.querySelectorAll("[data-emotion]:checked");
    if (on.length > (campOpts?.brief.max_emotions || 3)) t.checked = false;
    t.closest("label").classList.toggle("on", t.checked);
  }
  if (t.closest && t.closest("#perForm")) {
    if (t.id === "perFrom") return fillPersonaForm(presetSettings(t.value));
    previewPersona();
  }
});

// --- персоны в профиле ---
const PERSONA_FIELDS = [["seriousness", "Серьёзность"], ["humor", "Юмор"], ["darkness", "Мрачность"], ["verbosity", "Описания"], ["pace", "Темп"], ["manner", "Манера"], ["harshness", "Подача последствий"]];
async function loadPersonas() {
  await loadCampOpts();
  myPersonas = await api("/api/me/master-personas");
  $("perList").innerHTML = myPersonas.length ? myPersonas.map(p => `<li><span><b>${esc(p.name)}</b><div class="muted" style="white-space:pre-line;font-size:13px">${esc(p.style)}</div></span>
    <button class="ghost" data-peredit="${p.id}">Изменить</button><button class="ghost" data-perdel="${p.id}">Удалить</button></li>`).join("")
    : '<li class="muted">Своих персон пока нет. Можно выбирать встроенные или создать свою на их основе.</li>';
}
function presetSettings(id) { return campOpts.presets.find(p => p.id === id)?.settings || campOpts.persona.default; }
function fillPersonaForm(settings) {
  const o = campOpts.persona;
  $("perFields").innerHTML = PERSONA_FIELDS.map(([k, label]) => `<div><label>${label}</label><select data-perfield="${k}">${optionsHtml(o[k], settings[k])}</select></div>`).join("");
  $("perNotes").value = settings.notes || ""; previewPersona();
}
function personaFormSettings() {
  const s = {};
  document.querySelectorAll("[data-perfield]").forEach(el => { s[el.dataset.perfield] = /^\d+$/.test(el.value) ? +el.value : el.value; });
  s.notes = $("perNotes").value.trim();
  return s;
}
function previewPersona() {
  const o = campOpts.persona, s = personaFormSettings();
  $("perPreview").textContent = `Так мастер поймёт персону: ${o.seriousness[s.seriousness]}, ${o.humor[s.humor]}, ${o.darkness[s.darkness]}; описания — ${o.verbosity[s.verbosity]}; манера — ${o.manner[s.manner]}.`;
}
function personaForm(p) {
  editingPersona = p;
  $("perFormTitle").textContent = p ? "Изменить персону" : "Новая персона";
  $("perName").value = p?.name || "";
  $("perFrom").innerHTML = '<option value="">—</option>' + campOpts.presets.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join("");
  fillPersonaForm(p?.settings || campOpts.persona.default);
  $("perErr").textContent = ""; $("perForm").classList.remove("hidden"); $("perName").focus();
}
$("perNotes").oninput = previewPersona;
$("perNewBtn").onclick = () => personaForm(null);
$("perCancel").onclick = () => { $("perForm").classList.add("hidden"); editingPersona = null; };
$("perSave").onclick = async () => {
  $("perErr").textContent = "";
  const body = { name: $("perName").value.trim(), settings: personaFormSettings() };
  try {
    if (editingPersona) await api("/api/me/master-personas/" + editingPersona.id, { method: "PATCH", body });
    else await api("/api/me/master-personas", { method: "POST", body });
    $("perForm").classList.add("hidden"); editingPersona = null; await loadPersonas();
  } catch (e) { $("perErr").textContent = e.message; }
};

// --- смена персоны в комнате ---
async function openMasterPersona() {
  await loadCampOpts();
  const [cur, mine] = await Promise.all([api(`/api/campaigns/${room.id}/master-persona`), api("/api/me/master-personas").catch(() => [])]);
  myPersonas = mine;
  $("mpCurrent").textContent = cur.name ? `Сейчас: ${cur.name}` : cur.source === "custom" ? "Сейчас: своя настройка" : cur.style ? `Сейчас: ${cur.style}` : "Сейчас: мастер по умолчанию";
  const sel = cur.source === "preset" ? "pre:" + (campOpts.presets.find(p => p.name === cur.name)?.id || "") : cur.source === "profile" ? "my:" + (myPersonas.find(p => p.name === cur.name)?.id || "") : "";
  $("mpSelect").innerHTML = personaOptions(sel); $("mpStyle").value = cur.source === "legacy" ? "" : cur.style || "";
  $("mpErr").textContent = ""; $("masterPersonaCard").classList.remove("hidden");
}
async function saveMasterPersona() {
  try {
    const cur = await api(`/api/campaigns/${room.id}/master-persona`, { method: "PUT", body: { ...personaBody($("mpSelect").value), style: $("mpStyle").value.trim() || null } });
    $("mpCurrent").textContent = `Сейчас: ${cur.name || "мастер по умолчанию"}. Новый тон — со следующего хода мастера.`;
  } catch (e) { $("mpErr").textContent = e.message; }
}
document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button"); if (!t) return;
  try {
    if (t.dataset.peredit) return personaForm(myPersonas.find(p => p.id === t.dataset.peredit));
    if (t.dataset.perdel && confirm("Удалить персону? Кампании, где она выбрана, сохранят свою копию.")) { await api("/api/me/master-personas/" + t.dataset.perdel, { method: "DELETE" }); return loadPersonas(); }
    if (t.id === "masterPersonaBtn") return openMasterPersona();
    if (t.id === "mpSave") return saveMasterPersona();
    if (t.id === "mpClose") { $("masterPersonaCard").classList.add("hidden"); return; }
  } catch (e) { alert(e.message); }
});

// --- сюжет кампании: афиша для всех, подготовка у владельца и мастера ---
let planState = null;
function renderPoster(poster, intro) {
  if (!poster || !poster.title) { $("posterCard").classList.add("hidden"); return; }
  $("posterBody").innerHTML = `<h3 style="margin:0">${esc(poster.title)}</h3><p style="margin:4px 0"><i>${esc(poster.tagline || "")}</i></p>
    <p style="margin:4px 0">${(poster.tags || []).map(t => `<span class="badge">${esc(t)}</span>`).join(" ")}</p>
    ${intro ? `<p class="muted" style="white-space:pre-line;margin-bottom:0">${esc(intro)}</p>` : ""}`;
  $("posterCard").classList.remove("hidden");
}
async function openPlan() {
  $("planCard").classList.add("hidden"); $("planErr").textContent = "";
  renderPoster(room.settings?.poster, room.public_intro);
  if (!(room.is_owner || room.my_role === "master")) return;
  try { planState = await api(`/api/campaigns/${room.id}/plan`); } catch { return; }
  $("planCard").classList.remove("hidden"); renderPlan();
  if (planState.can_generate) loadPlanOptions();
}
function renderPlan() {
  const p = planState, st = p.status;
  const text = { none: "Сюжет ещё не подготовлен. Архитектор построит каркас по анкете и лору мира: завязку, злодеев с планом угрозы, акты, места и тайны. Детали мастер допишет по ходу игры.",
    generating: "Архитектор готовит сюжет… Это может занять пару минут, страницу можно не держать открытой.",
    ready: `Сюжет готов (вариант ${p.version}).`, failed: "Не получилось подготовить сюжет: " + (p.error || "") }[st] || st;
  $("planState").innerHTML = `<p class="${st === "failed" ? "bad" : "muted"}">${esc(text)}</p>`;
  const rev = p.revision && p.revision.status;
  if (rev === "revising") $("planState").innerHTML += '<p class="muted">Акт закрыт: мастер пересматривает дальнейшие акты с учётом того, что уже случилось.</p>';
  if (rev === "failed") $("planState").innerHTML += '<p class="muted">Пересмотреть дальнейшие акты не вышло: игра идёт по прежнему плану.</p>';
  if (rev === "ready" && p.note) $("planState").innerHTML += `<p class="muted">Последний пересмотр — ${esc(p.note.replace(/^пересмотр: /, ""))}</p>`;
  $("planControls").classList.toggle("hidden", !p.can_generate || st === "generating");
  $("planBtn").textContent = st === "ready" ? "Другой вариант" : "Подготовить сюжет";
  if (!p.can_generate && st !== "generating") $("planState").innerHTML += '<p class="muted">Игра уже началась: дальше сюжет меняется по ходу, а не заново.</p>';
  renderPoster(p.poster, p.public_intro);
  if (st === "generating" || rev === "revising") schedulePlanPoll();
  const full = p.plan && p.plan.title;
  $("planDetails").classList.toggle("hidden", !full);
  if (full) $("planFull").innerHTML = planHtml(p.plan);
}
async function loadPlanOptions(structureId) {
  try {
    const q = structureId ? "?structure_id=" + encodeURIComponent(structureId) : "";
    const o = await api(`/api/campaigns/${room.id}/plan/options${q}`);
    if (!structureId) $("planStructure").innerHTML = '<option value="">Автоматически по анкете</option>' + o.structures.map(x => `<option value="${esc(x.id)}" title="${esc(x.description)}">${esc(x.name)}${x.best ? " — лучше всего подходит" : ""}</option>`).join("");
    const e = o.estimate;
    $("planEstimate").textContent = `Примерно ${Math.round((e.tokens_in + e.tokens_out) / 1000)} тыс. токенов на модели ${e.model}` + (e.usd != null ? `, около $${e.usd.toFixed(2)}.` : ": цена неизвестна или модель локальная.") + " Если сервер вернёт каркас на доработку, будет до трёх попыток.";
  } catch (e) { $("planEstimate").textContent = ""; }
}
const ACT_MARK = { active: "идёт", done: "пройден", pending: "впереди" };
const NODE_MARK = { done: "✓", skipped: "обойдён" };
function planHtml(p) {
  const li = (xs, f) => `<ul>${(xs || []).map(x => `<li>${f(x)}</li>`).join("")}</ul>`;
  const mark = t => t ? ` <span class="muted">[${esc(t)}]</span>` : "";
  const outcome = x => x.outcome ? `<br><span class="muted">Итог: ${esc(x.outcome)}</span>` : "";
  const details = x => x.status === "developed" ? mark("развёрнут") + (x.details ? `<br><span class="muted">Детали: ${esc(x.details)}</span>` : "") : "";
  return `<p><b>Конфликт:</b> ${esc(p.conflict)} <b>Ставки:</b> ${esc(p.stakes)}</p>
    <b>Антагонисты</b>${li(p.antagonists, a => `<b>${esc(a.name)}</b>: ${esc(a.goal)}. Слабость: ${esc(a.weakness)}. Тайна: ${esc(a.secret)}<br><span class="muted">План угрозы (сделано шагов: ${a.threat_step || 0} из ${(a.threat || []).length}): ${(a.threat || []).map((t, i) => i < (a.threat_step || 0) ? `<s>${esc(t)}</s>` : esc(t)).join(" → ")}</span>`)}
    <b>Акты</b>${li(p.acts, a => `<b>${esc(a.title)}</b>${mark(ACT_MARK[a.status])} — ${esc(a.goal)}${outcome(a)}${li(a.nodes, n => `${esc(n.title)}${mark(NODE_MARK[n.status])}: ${esc(n.summary)}${outcome(n)}`)}`)}
    <b>Места</b>${li(p.locations, l => `<b>${esc(l.name)}</b>${details(l)}: ${esc(l.role)} <span class="muted">Секрет: ${esc(l.secret)}</span>`)}
    <b>NPC</b>${li(p.npcs, n => `<b>${esc(n.name)}</b>${details(n)}: ${esc(n.role)}; хочет — ${esc(n.want)} <span class="muted">Тайна: ${esc(n.secret)}</span>`)}
    <b>Тайны</b>${li(p.reveals, r => `${esc(r.truth)}${mark(r.revealed ? "раскрыта" : "")} <span class="muted">(${(r.clues || []).length} зацепки)</span>`)}
    <b>Финалы</b>${li(p.endings, e => esc(e))}`;
}
let planPoll = null;
function schedulePlanPoll() {
  // событие по WebSocket может прийти раньше подписки, поэтому, пока сюжет готовится, статус ещё и опрашивается
  clearTimeout(planPoll);
  const id = room.id;
  planPoll = setTimeout(async () => {
    if (!room || room.id !== id) return;
    try { planState = await api(`/api/campaigns/${id}/plan`); renderPlan(); if (planState.status !== "generating" && planState.revision?.status !== "revising") { room.public_intro = planState.public_intro; if (planState.can_generate) loadPlanOptions(); } } catch { /* комната закрыта */ }
  }, 4000);
}
function onPlanEvent(payload) {
  if (!room) return;
  room.settings = { ...(room.settings || {}), plan: payload.plan, poster: payload.poster }; room.public_intro = payload.public_intro;
  if (planState) openPlan(); else renderPoster(payload.poster, payload.public_intro);
}
$("planStructure").onchange = () => loadPlanOptions($("planStructure").value || undefined);
$("planBtn").onclick = async () => {
  $("planErr").textContent = "";
  try {
    planState = await api(`/api/campaigns/${room.id}/plan`, { method: "POST", body: { note: $("planNote").value.trim(), structure_id: $("planStructure").value || null } });
    $("planNote").value = ""; renderPlan();
  } catch (e) { $("planErr").textContent = e.message; }
};
