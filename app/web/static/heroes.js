// Лист героя: в кампании (свой герой, проверка мастером или владельцем) и в профиле (герои библиотеки).
// Использует $, api, esc, room, mySeat, AB, AB_RU, SK_RU, ST_RU, METHOD_RU, loadHeroes, loadLibrary из index.html.
const SAVE_NOTE = "спасброски";
let sheetCtx = null;

function signed(n) { return n == null ? "?" : (n >= 0 ? "+" : "") + n; }
function statusText(c) {
  if (c.status === "submitted") return c.reviewer === "ai" ? "на проверке у ИИ-мастера" : "на проверке у мастера";
  return ST_RU[c.status] || c.status;
}

function sheetHtml(c, { library = false } = {}) {
  const d = c.derived || {}, r = c.resources || {}, s = c.sheet || {};
  const who = [c.origin_name, c.class_name].filter(Boolean).join(", ");
  let h = `<h3 style="margin:0">${esc(c.name || "без имени")}</h3>
    <p class="muted" style="margin:4px 0 10px">${esc(who || "не собран")} · уровень ${c.level || s.level || 1}${library ? "" : " · " + statusText(c)}${s.ability_method ? " · " + (METHOD_RU[s.ability_method] || s.ability_method) : ""}</p>`;
  if (c.review_error) h += `<p class="bad">ИИ-мастер не смог проверить героя: ${esc(c.review_error.replace(/ \(.*$/s, ""))}</p>`;
  if (c.review_comment) h += `<p class="muted">Мастер: ${esc(c.review_comment)}</p>`;
  const top = [];
  if (r.hp_max) top.push(["Хиты", `${r.hp}/${r.hp_max}${r.temp_hp ? " +" + r.temp_hp : ""}`]);
  else if (d.hp_max) top.push(["Хиты", d.hp_max]);
  if (d.ac != null && !library) top.push(["КД", d.ac]);
  if (d.pb != null) top.push(["Бонус мастерства", signed(d.pb)]);
  if (top.length) h += `<div class="stats">${top.map(([k, v]) => `<div><b>${esc(v)}</b><span>${k}</span></div>`).join("")}</div>`;
  if (d.abilities) {
    h += `<h4>Характеристики</h4><div class="abil">${AB.map(a => `<div class="abox"><span class="muted">${AB_RU[a]}</span><b>${d.abilities[a]}</b><span>${signed(d.mods?.[a])}</span></div>`).join("")}</div>`;
  }
  if (d.saves) h += `<p><span class="muted">${SAVE_NOTE}:</span> ${AB.map(a => `${AB_RU[a]} ${signed(d.saves[a])}`).join(" · ")}</p>`;
  if (d.skills) {
    const prof = new Set(s.skills || []);
    h += `<h4>Навыки</h4><div class="skills">${Object.entries(d.skills).sort((x, y) => (SK_RU[x[0]] || x[0]).localeCompare(SK_RU[y[0]] || y[0], "ru")).map(([k, v]) => `<div>${prof.has(k) ? "<b>" : ""}${esc(SK_RU[k] || k)} ${signed(v)}${prof.has(k) ? "</b>" : ""}</div>`).join("")}</div>`;
  }
  if (d.attacks?.length) h += `<h4>Атаки</h4><ul>${d.attacks.map(a => `<li>${esc(a.name)} ${signed(a.attack_bonus)}, ${esc(a.damage)}</li>`).join("")}</ul>`;
  if (d.effects?.length) h += `<h4>Состояния</h4><p>${d.effects.map(e => esc(e.name) + (e.stacks > 1 ? " ×" + e.stacks : "")).join(", ")}</p>`;
  if (!library) {
    h += `<h4>Инвентарь</h4>` + (c.inventory?.length
      ? `<ul>${c.inventory.map(i => `<li>${esc(i.name)}${i.qty > 1 ? " ×" + i.qty : ""}${i.equipped ? ' <span class="muted">(надето)</span>' : ""}</li>`).join("")}</ul>`
      : `<p class="muted">${["draft", "submitted"].includes(c.status) ? "Стартовое снаряжение выдаётся после одобрения мастером." : "Пусто."}</p>`);
  } else {
    h += `<p class="muted">Снаряжение выбирается из стартовых наборов класса; предметы появятся у копии героя в кампании после одобрения.</p>`;
  }
  if (c.public_bio) h += `<h4>Внешность и история</h4><p>${esc(c.public_bio)}</p>`;
  if (c.private_backstory) h += `<h4>Тайная предыстория</h4><p>${esc(c.private_backstory)}</p>`;
  if (!library && !c.sheet && c.bonds?.length) h += `<h4>Связи</h4><ul>${c.bonds.map(b => `<li><span class="muted">${esc(b.question)}</span> ${esc(b.answer)}</li>`).join("")}</ul>`;
  const pers = Object.entries(c.personality || {}).filter(([, v]) => v);
  if (pers.length) h += `<h4>Характер</h4><ul>${pers.map(([k, v]) => `<li><span class="muted">${esc(k)}:</span> ${esc(v)}</li>`).join("")}</ul>`;
  if (library && c.copies) {
    h += `<h4>Копии в кампаниях</h4>` + (c.copies.length
      ? `<ul>${c.copies.map(x => `<li>${esc(x.campaign_name)} <span class="muted">· ${ST_RU[x.status] || x.status} · уровень ${x.level}</span></li>`).join("")}</ul><p class="muted">Копии развиваются отдельно: правка или удаление героя в профиле их не меняет.</p>`
      : '<p class="muted">Пока не играет ни в одной кампании.</p>');
  }
  return h;
}

function openSheet(c, ctx) {
  sheetCtx = { ...ctx, c };
  $("sheetBody").innerHTML = sheetHtml(c, { library: ctx.kind === "library" });
  const act = [];
  if (ctx.kind === "review") {
    act.push(`<label>Комментарий игроку (нужен, если возвращаете на доработку)</label><textarea id="sheetComment" rows="2"></textarea>`);
    act.push(`<p class="row" style="flex-wrap:wrap"><button id="sheetApprove" style="flex:0 0 auto">Одобрить</button><button class="ghost" id="sheetReturn" style="flex:0 0 auto">Вернуть на доработку</button>${c.reviewer === "ai" ? '<button class="ghost" id="sheetRetryAi" style="flex:0 0 auto">Повторить проверку ИИ</button>' : ""}</p>`);
  }
  if (ctx.kind === "mine" && c.status === "submitted" && c.reviewer === "ai" && c.review_error) act.push(`<p><button class="ghost" id="sheetRetryAi">Повторить проверку ИИ</button></p>`);
  if (ctx.kind === "library") act.push(`<p class="row" style="flex-wrap:wrap"><button id="sheetEdit" style="flex:0 0 auto">Изменить</button><button class="ghost" id="sheetDelete" style="flex:0 0 auto">Удалить</button></p>`);
  const withBonds = ctx.kind !== "library" && c.sheet && ["approved", "active"].includes(c.status);
  if (withBonds) act.unshift('<div id="sheetBonds"></div>');
  $("sheetActions").innerHTML = act.join(""); $("sheetErr").textContent = "";
  $("sheetModal").classList.remove("hidden"); document.body.classList.add("modal-open");
  if (withBonds) loadBonds(c.id);
}

// Связи героя: игрок отвечает на вопросы мастера, мастер видит все ответы, остальные — только открытые.
async function loadBonds(id) {
  try { renderBonds(id, await api(`/api/campaigns/${room.id}/characters/${id}/bonds`)); } catch { /* нет доступа */ }
}
function renderBonds(id, data) {
  const box = $("sheetBonds"); if (!box || sheetCtx?.c.id !== id) return;
  const b = data.bonds || {}, ans = b.answers || {}, qs = b.questions || [];
  let h = "<h4>Связи героя</h4>";
  if (b.status === "asking") h += '<p class="muted">Мастер готовит вопросы под эту кампанию…</p>';
  if (!qs.length) { box.innerHTML = h + '<p class="muted">Вопросов пока нет.</p>'; return; }
  if (!data.can_answer) {
    box.innerHTML = h + `<ul>${qs.map(q => `<li><span class="muted">${esc(q.text)}</span> ${ans[q.id] ? esc(ans[q.id].text) + (ans[q.id].private ? ' <span class="muted">(лично)</span>' : "") : '<span class="muted">нет ответа</span>'}</li>`).join("")}</ul>`;
    return;
  }
  h += '<p class="muted">Ответы свяжут героя с историей и отрядом. Открытые увидят все за столом, личные — только мастер.</p>';
  h += qs.map(q => `<label>${esc(q.text)}</label><textarea rows="2" maxlength="600" data-bond="${esc(q.id)}">${esc(ans[q.id]?.text || "")}</textarea>
    <label class="muted" style="display:flex;gap:6px;align-items:center"><input type="checkbox" data-bondpriv="${esc(q.id)}" style="width:auto"${ans[q.id]?.private ? " checked" : ""}> лично, только мастеру</label>`).join("");
  h += '<p><button id="bondsSave" style="flex:0 0 auto">Сохранить ответы</button> <span class="muted" id="bondsNote"></span></p>';
  box.innerHTML = h;
  if (b.status === "asking") setTimeout(() => sheetCtx?.c.id === id && loadBonds(id), 4000);
}
function onBondsEvent(p) {
  if (sheetCtx?.c.id === p.character_id && !document.activeElement?.dataset?.bond) loadBonds(p.character_id);
}
async function saveBonds() {
  const answers = [...document.querySelectorAll("[data-bond]")].map(t => ({ id: t.dataset.bond, text: t.value.trim(), private: document.querySelector(`[data-bondpriv="${t.dataset.bond}"]`).checked }));
  const r = await api(`/api/campaigns/${room.id}/characters/${sheetCtx.c.id}/bonds`, { method: "PUT", body: { answers } });
  renderBonds(sheetCtx.c.id, r); $("bondsNote").textContent = "Сохранено.";
}
function closeSheet() { $("sheetModal").classList.add("hidden"); document.body.classList.remove("modal-open"); sheetCtx = null; }

async function openCampaignSheet(id, kind) {
  openSheet(await api(`/api/campaigns/${room.id}/characters/${id}`), { kind });
}
async function openLibrarySheet(id) {
  openSheet(await api(`/api/me/characters/${id}`), { kind: "library" });
}
function libraryListHtml(list) {
  return list.length ? list.map(h => `<li><span><b>${esc(h.name || "без имени")}</b> <span class="muted">${esc([h.origin_name, h.class_name].filter(Boolean).join(", ") || "не собран")}${h.errors?.length ? " · не закончен" : ""}</span></span><button class="ghost" data-libview="${h.id}">Посмотреть</button><button class="ghost" data-libedit="${h.id}">Изменить</button><button class="ghost" data-libdel="${h.id}">Удалить</button></li>`).join("") : '<li class="muted">Пока нет героев.</li>';
}

async function reviewAction(approve) {
  const comment = $("sheetComment").value.trim();
  if (!approve && !comment) { $("sheetErr").textContent = "Напишите, что исправить."; return; }
  await api(`/api/campaigns/${room.id}/characters/${sheetCtx.c.id}/review`, { method: "POST", body: { approve, comment } });
  closeSheet(); loadHeroes();
}

document.addEventListener("click", async (ev) => {
  if (ev.target.id === "sheetModal") return closeSheet();
  const t = ev.target.closest("button"); if (!t) return;
  try {
    if (t.id === "sheetClose") return closeSheet();
    if (t.dataset.libview) return openLibrarySheet(t.dataset.libview);
    if (t.dataset.sheet) return openCampaignSheet(t.dataset.sheet, t.dataset.sheetKind || "mine");
    if (t.id === "heroSheetBtn" && hero) return openCampaignSheet(hero.id, "mine");
    if (t.id === "sheetApprove") return reviewAction(true);
    if (t.id === "bondsSave") return saveBonds();
    if (t.id === "sheetReturn") return reviewAction(false);
    if (t.id === "sheetRetryAi" || t.dataset.retryai) {
      const id = t.dataset.retryai || sheetCtx.c.id;
      await api(`/api/campaigns/${room.id}/characters/${id}/review/retry-ai`, { method: "POST" });
      if (sheetCtx) closeSheet();
      addMsg({ kind: "system", content: "Герой снова отправлен на проверку ИИ-мастеру." });
      return loadHeroes();
    }
    if (t.id === "sheetEdit") { const c = sheetCtx.c; closeSheet(); return openBuilder("library", await api(`/api/me/characters/${c.id}`)); }
    if (t.id === "sheetDelete" && confirm("Удалить героя из профиля? Его копии в кампаниях останутся.")) {
      await api(`/api/me/characters/${sheetCtx.c.id}`, { method: "DELETE" }); closeSheet();
      return $("profile").classList.contains("hidden") ? loadLibrary() : loadProfileHeroes();
    }
  } catch (e) { if (sheetCtx) $("sheetErr").textContent = e.message; else alert(e.message); }
});
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && sheetCtx) closeSheet(); });

async function loadProfileHeroes() {
  library = await api("/api/me/characters").catch(() => []);
  $("pHeroList").innerHTML = libraryListHtml(library);
}
