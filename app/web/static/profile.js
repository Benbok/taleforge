// Профиль: аккаунт и статистика у всех, модели ИИ у Admin и Super Admin, роли пользователей у Super Admin.
// Использует $, api, esc, show, me, room из index.html.
const ROLE_RU = { super_admin: "Суперадмин", admin: "Админ", player: "Игрок" };
const PROVIDER_RU = { claude: "Claude", gemini: "Gemini", local: "LM Studio" };
let prof = null, providers = [], modelProfiles = [], editingModel = null;

function fmtDate(s) { try { return new Date(s).toLocaleString("ru-RU", { dateStyle: "medium", timeStyle: "short" }); } catch { return s; } }
function checkLine(c) {
  if (!c || !c.at) return '<span class="muted">не проверялась</span>';
  const when = fmtDate(c.at);
  return c.ok
    ? `<span class="ok">✓ отвечает</span> <span class="muted">· ${c.latency_ms ?? "?"} мс · «${esc(c.reply)}» · ${when}</span>`
    : `<span class="bad">✗ ${esc(c.error.replace(/ \(.*$/s, ""))}</span> <span class="muted">· ${when}</span>${c.error.includes(" (") ? `<details><summary class="muted">подробности</summary><code>${esc(c.error)}</code></details>` : ""}`;
}

async function openProfile() {
  if (typeof closeWs === "function") closeWs();
  room = null; show("profile");
  prof = await api("/api/me/profile");
  renderAccount(); loadProfileHeroes();
  $("pModels").classList.toggle("hidden", !prof.can_manage_models);
  $("pUsers").classList.toggle("hidden", !prof.can_manage_users);
  if (prof.can_manage_models) await loadModels();
  if (prof.can_manage_users) await loadUsers();
}

function renderAccount() {
  const u = prof.user, s = prof.stats;
  $("pAccount").innerHTML = `<h3 style="margin-top:0">${esc(u.name)} <span class="badge">${ROLE_RU[u.platform_role] || u.platform_role}</span></h3>
    <p class="muted">С нами с ${fmtDate(prof.created_at)}</p>
    <div class="stats">
      <div><b>${s.campaigns_playing}</b><span>играет</span></div>
      <div><b>${s.campaigns_mastering}</b><span>ведёт сам</span></div>
      <div><b>${s.library_characters}</b><span>героев в профиле</span></div>
      ${prof.can_manage_models ? `<div><b>${s.campaigns_owned}</b><span>своих кампаний</span></div><div><b>$${(s.llm_spend_usd ?? 0).toFixed(2)}</b><span>на модели (${s.llm_calls} вызовов)</span></div>` : ""}
    </div>`;
  $("pNewName").value = u.name;
}

$("pRenameBtn").onclick = async () => {
  $("pAccErr").textContent = "";
  try { me = await api("/api/me", { method: "PATCH", body: { name: $("pNewName").value.trim() } }); setWhoami(); await openProfile(); $("pAccErr").textContent = "Имя сохранено."; }
  catch (e) { $("pAccErr").textContent = e.message; }
};
$("pPassBtn").onclick = async () => {
  $("pAccErr").textContent = "";
  try { await api("/api/me/password", { method: "POST", body: { old_password: $("pOldPass").value, new_password: $("pNewPass").value } }); $("pOldPass").value = $("pNewPass").value = ""; $("pAccErr").textContent = "Пароль изменён."; }
  catch (e) { $("pAccErr").textContent = e.message; }
};

// --- модели ИИ ---
async function loadModels() {
  [providers, modelProfiles] = await Promise.all([api("/api/admin/providers"), api("/api/admin/models")]);
  $("pProviders").innerHTML = providers.map(p => {
    const state = p.key_set === null ? `<span class="muted">ключ не нужен · ${esc(p.api_base)}</span>`
      : p.key_set ? `<span class="ok">ключ задан</span>` : `<span class="bad">нет ключа: задайте ${esc(p.key_env)} в окружении сервера</span>`;
    return `<li><span><b>${esc(p.title)}</b>${p.default_model ? ` <span class="muted">· по умолчанию ${esc(p.default_model)}</span>` : ""}</span>${state}</li>`;
  }).join("");
  const superAdmin = me.platform_role === "super_admin";
  $("pModelList").innerHTML = modelProfiles.length ? modelProfiles.map(m => `<li class="model">
      <span><b>${esc(m.name)}</b>${m.is_default ? ' <span class="badge">по умолчанию</span>' : ""}
        <span class="muted">· ${PROVIDER_RU[m.provider]} · ${esc(m.resolved_model || m.model)} · t=${m.temperature}${m.api_base ? " · " + esc(m.api_base) : ""}${m.campaigns ? ` · кампаний: ${m.campaigns}` : ""}</span>
        <div id="chk_${m.id}">${checkLine(m.last_check)}</div></span>
      <button class="ghost" data-mcheck="${m.id}">Проверить</button>
      <button class="ghost" data-medit="${m.id}">Изменить</button>
      ${superAdmin && !m.is_default ? `<button class="ghost" data-mdefault="${m.id}">Сделать основной</button>` : ""}
      ${superAdmin || !m.is_default ? `<button class="ghost" data-mdel="${m.id}">Удалить</button>` : ""}
    </li>`).join("") : '<li class="muted">Моделей пока нет. Добавьте первую: её можно будет выбрать мастером кампании.</li>';
  $("mDefaultBox").classList.toggle("hidden", !superAdmin);
}

function modelForm(m) {
  editingModel = m;
  $("mFormTitle").textContent = m ? "Изменить модель" : "Новая модель";
  $("mName").value = m?.name || ""; $("mProvider").value = m?.provider || "claude"; $("mModel").value = m?.model || "";
  $("mBase").value = m?.api_base || ""; $("mTemp").value = m?.temperature ?? 0.8; $("mDefault").checked = !!m?.is_default;
  $("mCheckOut").innerHTML = ""; $("mErr").textContent = ""; syncProviderFields();
  $("mForm").classList.remove("hidden"); $("mName").focus();
}
function syncProviderFields() {
  const p = $("mProvider").value, info = providers.find(x => x.id === p);
  $("mBaseBox").classList.toggle("hidden", p !== "local"); $("mLocalBtn").classList.toggle("hidden", p !== "local");
  $("mBase").placeholder = info?.api_base || "http://localhost:1234/v1";
  $("mModel").placeholder = p === "claude" ? `пусто — ${info?.default_model || "модель по умолчанию"}` : p === "gemini" ? "например gemini-2.5-pro" : "имя модели, загруженной в LM Studio";
}
function formBody() {
  const p = $("mProvider").value;
  return { name: $("mName").value.trim(), provider: p, model: $("mModel").value.trim(), api_base: p === "local" ? ($("mBase").value.trim() || null) : null, temperature: +$("mTemp").value };
}
$("mProvider").onchange = syncProviderFields;
$("mNewBtn").onclick = () => modelForm(null);
$("mCancel").onclick = () => { $("mForm").classList.add("hidden"); editingModel = null; };
$("mLocalBtn").onclick = async () => {
  $("mErr").textContent = "";
  try {
    const q = $("mBase").value.trim() ? "?api_base=" + encodeURIComponent($("mBase").value.trim()) : "";
    const list = await api("/api/admin/providers/local/models" + q);
    $("mLocalList").innerHTML = list.map(x => `<option value="${esc(x)}">`).join("");
    $("mErr").textContent = list.length ? `LM Studio отдаёт моделей: ${list.length}. Выберите в поле «Модель».` : "LM Studio отвечает, но модели не загружены.";
  } catch (e) { $("mErr").textContent = e.message; }
};
$("mTryBtn").onclick = async () => {
  const b = formBody(); $("mCheckOut").innerHTML = '<span class="muted">Проверяю…</span>';
  try { $("mCheckOut").innerHTML = checkLine(await api("/api/admin/models/check", { method: "POST", body: { provider: b.provider, model: b.model, api_base: b.api_base } })); }
  catch (e) { $("mCheckOut").innerHTML = `<span class="bad">${esc(e.message)}</span>`; }
};
$("mSave").onclick = async () => {
  $("mErr").textContent = "";
  const body = formBody();
  if (me.platform_role === "super_admin") body.is_default = $("mDefault").checked;
  try {
    if (editingModel) await api("/api/admin/models/" + editingModel.id, { method: "PATCH", body });
    else await api("/api/admin/models", { method: "POST", body });
    $("mForm").classList.add("hidden"); editingModel = null; await loadModels();
  } catch (e) { $("mErr").textContent = e.message; }
};

// --- пользователи (Super Admin) ---
async function loadUsers() {
  const users = await api("/api/admin/users");
  $("pUserList").innerHTML = users.map(u => `<li><span><b>${esc(u.name)}</b>${u.id === me.id ? ' <span class="muted">(вы)</span>' : ""}</span>
    <select data-role="${u.id}" ${u.id === me.id ? "disabled" : ""}>${Object.entries(ROLE_RU).map(([k, v]) => `<option value="${k}" ${k === u.platform_role ? "selected" : ""}>${v}</option>`).join("")}</select></li>`).join("");
}
$("uCreate").onclick = async () => {
  $("uErr").textContent = "";
  try { await api("/api/admin/users", { method: "POST", body: { name: $("uName").value.trim(), password: $("uPass").value, platform_role: $("uRole").value } }); $("uName").value = $("uPass").value = ""; await loadUsers(); }
  catch (e) { $("uErr").textContent = e.message; }
};

document.addEventListener("change", async (ev) => {
  const t = ev.target;
  if (t.dataset.role) {
    try { await api("/api/admin/users/" + t.dataset.role, { method: "PATCH", body: { platform_role: t.value } }); }
    catch (e) { alert(e.message); await loadUsers(); }
  }
});
document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button"); if (!t) return;
  try {
    if (t.dataset.mcheck) {
      $("chk_" + t.dataset.mcheck).innerHTML = '<span class="muted">Проверяю…</span>'; t.disabled = true;
      const m = await api(`/api/admin/models/${t.dataset.mcheck}/check`, { method: "POST" }).finally(() => { t.disabled = false; });
      $("chk_" + m.id).innerHTML = checkLine(m.last_check); return;
    }
    if (t.dataset.medit) return modelForm(modelProfiles.find(m => m.id === t.dataset.medit));
    if (t.dataset.mdefault) { await api("/api/admin/models/" + t.dataset.mdefault, { method: "PATCH", body: { is_default: true } }); return loadModels(); }
    if (t.dataset.mdel && confirm("Удалить модель? Кампании, где она уже выбрана, продолжат работать на ней.")) { await api("/api/admin/models/" + t.dataset.mdel, { method: "DELETE" }); return loadModels(); }
    if (t.id === "masterModelBtn") return openMasterModel();
    if (t.id === "mmSave") return saveMasterModel();
    if (t.id === "mmClose") { $("masterModelCard").classList.add("hidden"); return; }
  } catch (e) { alert(e.message); }
});

// --- выбор модели мастера: создание кампании и смена в комнате ---
function modelOptions(selectedId) {
  return modelProfiles.map(m => `<option value="p:${m.id}" ${m.id === selectedId ? "selected" : ""}>ИИ: ${esc(m.name)}${m.is_default ? " (по умолчанию)" : ""}</option>`).join("");
}
async function fillMasterSelect() {
  modelProfiles = await api("/api/admin/models").catch(() => []);
  const def = modelProfiles.find(m => m.is_default);
  $("cMaster").innerHTML = (modelProfiles.length ? modelOptions(def?.id) : '<option value="claude">ИИ: Claude (модель по умолчанию)</option>') + '<option value="owner">Я сам</option>';
  $("cMasterHint").innerHTML = modelProfiles.length ? "" : 'Модели ИИ настраиваются в <a href="#" id="toProfile">профиле</a>.';
  $("cPlaysBox").classList.toggle("hidden", $("cMaster").value === "owner");
}
function masterChoice() {
  const v = $("cMaster").value;
  if (v === "owner") return { type: "owner" };
  if (v.startsWith("p:")) return { type: "agent", model_profile_id: v.slice(2) };
  return { type: "agent", provider: v };
}
async function openMasterModel() {
  const [cur, list] = await Promise.all([api(`/api/campaigns/${room.id}/master-model`), api("/api/admin/models")]);
  modelProfiles = list;
  $("mmCurrent").textContent = `Сейчас: ${cur.model_profile_name ? cur.model_profile_name + " · " : ""}${PROVIDER_RU[cur.provider] || cur.provider} · ${cur.resolved_model || cur.model}`;
  $("mmSelect").innerHTML = list.length ? modelOptions(cur.model_profile_id) : '<option value="">Нет моделей: добавьте их в профиле</option>';
  $("mmErr").textContent = ""; $("masterModelCard").classList.remove("hidden");
}
async function saveMasterModel() {
  const v = $("mmSelect").value; if (!v) return;
  try { const cur = await api(`/api/campaigns/${room.id}/master-model`, { method: "PUT", body: { model_profile_id: v.slice(2) } }); $("mmCurrent").textContent = `Сейчас: ${cur.model_profile_name} · ${cur.resolved_model || cur.model}. Мастер ответит новой моделью со следующего хода.`; }
  catch (e) { $("mmErr").textContent = e.message; }
}
function setWhoami() {
  $("whoami").textContent = me.name + (me.platform_role !== "player" ? " · " + (ROLE_RU[me.platform_role] || me.platform_role) : "");
  $("profileBtn").classList.remove("hidden");
}
$("profileBtn").onclick = () => openProfile();
$("pBack").onclick = () => lobby();
document.addEventListener("click", (ev) => { if (ev.target.id === "toProfile") { ev.preventDefault(); openProfile(); } });
