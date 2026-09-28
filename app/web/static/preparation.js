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
