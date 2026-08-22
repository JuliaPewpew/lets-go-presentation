const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();
const test = ["localhost", "127.0.0.1"].includes(location.hostname),
  init =
    tg?.initData ||
    (test
      ? new URLSearchParams(location.search).get("test_init_data") || ""
      : "");
let data,
  tab = "ideas",
  editing = null,
  filters = { difficulty: 5, budget: 5, duration: 5 };
const esc = (s) =>
    String(s ?? "").replace(
      /[&<>'"]/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          "'": "&#39;",
          '"': "&quot;",
        })[c],
    ),
  modal = (id, on = true) =>
    document.querySelector(id).classList.toggle("open", on);
const api = async (path, opt = {}) => {
    const h = { "X-Telegram-Init-Data": init, ...opt.headers };
    if (!(opt.body instanceof FormData)) h["Content-Type"] = "application/json";
    const r = await fetch(path, { ...opt, headers: h });
    if (!r.ok) throw Error(await r.text());
    return r.json();
  },
  flash = (e) => {
    const message = e.message || String(e);
    if (tg?.showAlert) tg.showAlert(message);
    else alert(message);
  };
const botUrl = "https://t.me/lets_go_friends_bot?start=app";
const openTelegram = (url) => {
  if (tg?.openTelegramLink) tg.openTelegramLink(url);
  else location.href = url;
};
const inviteFriends = () => {
  const invite = `https://t.me/lets_go_friends_bot?start=join_${data.company.invite_code}`;
  openTelegram(
    `https://t.me/share/url?url=${encodeURIComponent(invite)}&text=${encodeURIComponent(`Вступай в нашу компанию «${data.company.name}» в let’s go!`)}`,
  );
};
function syncCompanyHeader() {
  companyName.textContent = data?.company?.name || "Компания";
}
async function refresh() {
  data = await api("/api/bootstrap");
  syncCompanyHeader();
  if (!data.company) {
    content.innerHTML = "";
    modal("#companyModal");
  }
  render();
}
async function act(path, body = {}, method = "POST") {
  try {
    await api(path, {
      method,
      body: body instanceof FormData ? body : JSON.stringify(body),
    });
    await refresh();
  } catch (e) {
    flash(e);
  }
}
async function load() {
  try {
    await refresh();
    loading.classList.add("hidden");
    app.classList.remove("hidden");
    if (!data.company) modal("#companyModal");
    if (!localStorage.getItem("lg-onboarding")) modal("#onboarding");
  } catch (e) {
    loading.innerHTML =
      '<div class="notice">Откройте приложение кнопкой внутри Telegram.</div>';
  }
}
function card(x, vote = false, selected = "") {
  const can =
    +x.author_id === +data.user.id || +data.company.owner_id === +data.user.id;
  return `<article class="card"><h3>${esc(x.title)}</h3>${x.description ? `<p class="desc">${esc(x.description)}</p>` : ""}<div class="chips"><span class="chip">сложность ${x.difficulty}/5</span><span class="chip">бюджет ${x.budget}/5</span><span class="chip">время ${x.duration}/5</span></div><div class="author">${x.anonymous ? "🎲 автор скрыт" : esc(x.author)}</div>${
    vote
      ? `<button class="secondary vote-btn ${x.title === selected ? "selected" : ""}" data-id="${x.id}">${x.title === selected ? "✓ Ваш выбор" : "Выбрать"}</button>`
      : `<div class="reactions">${["👍", "❤️", "🔥"]
          .map((e) => {
            const r = x.reactions.find((y) => y.emoji === e);
            return `<button class="reaction ${r?.mine ? "mine" : ""}" data-react="${x.id}" data-emoji="${e}">${e} ${r?.count || ""}</button>`;
          })
          .join(
            "",
          )}</div><div class="comments">${x.comments.map((c) => `<div class="comment"><b>${esc(c.display_name)}:</b> ${esc(c.text)}</div>`).join("")}<form class="comment-form" data-comment="${x.id}"><input name="text" maxlength="500" placeholder="Комментарий"><button class="primary">↑</button></form></div>${can ? `<div class="actions"><button class="link edit" data-id="${x.id}">Изменить</button><button class="link remove" data-id="${x.id}">Удалить</button></div>` : ""}`
  }</article>`;
}
function nextAction() {
  if (data.vote)
    return {
      eyebrow: "СЕЙЧАС",
      title: "Идёт голосование",
      description: "Выберите идею или проверьте, кто ещё не проголосовал.",
      label: "Открыть голосование",
      tab: "vote",
    };
  if (data.date_poll)
    return {
      eyebrow: "СЛЕДУЮЩИЙ ШАГ",
      title: "Выбираем дату",
      description: `Победила идея «${data.date_poll.title}».`,
      label: "Выбрать дату",
      tab: "vote",
    };
  if (data.activity)
    return {
      eyebrow: "ЗАПЛАНИРОВАНО",
      title: data.activity.title,
      description: new Date(data.activity.scheduled_at).toLocaleString("ru-RU"),
      label: "Открыть текущий план",
      tab: "activity",
    };
  if (data.ideas.length < 2)
    return {
      eyebrow: "СЛЕДУЮЩИЙ ШАГ",
      title: "Соберите идеи",
      description: `Для голосования нужно ещё ${2 - data.ideas.length}.`,
      label: "+ Добавить идею",
      tab: "ideas",
      action: "add-idea",
    };
  return {
    eyebrow: "ВСЁ ГОТОВО",
    title: "Пора выбрать",
    description: `${data.ideas.length} идей готовы к голосованию.`,
    label: "Перейти к выбору",
    tab: "vote",
  };
}
function render() {
  if (!data?.company) return;
  document
    .querySelectorAll(".nav button")
    .forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  const next = nextAction();
  content.innerHTML = `<section class="hero"><small>${next.eyebrow}</small><h1>${esc(next.title)}</h1><p>${esc(next.description)}</p><button class="hero-action" id="nextAction" data-next-tab="${next.tab}" data-next-action="${next.action || "open"}">${esc(next.label)}</button></section><section class="section" id="body"></section>`;
  const nextActionButton = document.querySelector("#nextAction");
  nextActionButton.onclick = () => {
    tab = nextActionButton.dataset.nextTab;
    render();
    if (nextActionButton.dataset.nextAction === "add-idea") openIdea();
  };
  const b = document.querySelector("#body");
  if (tab === "ideas") ideas(b);
  if (tab === "vote") vote(b);
  if (tab === "activity") activity(b);
  if (tab === "archive") archive(b);
}
function ideas(b) {
  const list = data.ideas.filter(
    (x) =>
      x.difficulty <= filters.difficulty &&
      x.budget <= filters.budget &&
      x.duration <= filters.duration,
  );
  b.innerHTML = `<div class="head"><h2>Идеи</h2><button class="pill hot" id="add">+ Идея</button></div>${data.activity ? '<div class="notice">Следующее голосование станет доступно после завершения текущего плана. Перейдите на шаг «3 · План».</div>' : '<div class="notice">Шаг 1: соберите идеи, затем перейдите на вкладку «2 · Выбор».</div>'}<div class="filters">${["difficulty", "budget", "duration"].map((k, i) => `<select data-filter="${k}"><option value="5">${["Сложность", "Бюджет", "Время"][i]} ≤ 5</option>${[1, 2, 3, 4].map((n) => `<option value="${n}" ${filters[k] === n ? "selected" : ""}>≤ ${n}</option>`).join("")}</select>`).join("")}</div>${list.map((x) => card(x)).join("") || '<div class="empty">Ничего не найдено</div>'}`;
  add.onclick = () => openIdea();
  document.querySelectorAll("[data-filter]").forEach(
    (x) =>
      (x.onchange = () => {
        filters[x.dataset.filter] = +x.value;
        render();
      }),
  );
  document.querySelectorAll("[data-react]").forEach(
    (x) =>
      (x.onclick = () =>
        act(`/api/ideas/${x.dataset.react}/reactions`, {
          emoji: x.dataset.emoji,
        })),
  );
  document.querySelectorAll("[data-comment]").forEach(
    (f) =>
      (f.onsubmit = (e) => {
        e.preventDefault();
        const text = new FormData(f).get("text");
        if (text.trim())
          act(`/api/ideas/${f.dataset.comment}/comments`, { text });
      }),
  );
  document
    .querySelectorAll(".edit")
    .forEach(
      (x) =>
        (x.onclick = () =>
          openIdea(data.ideas.find((i) => i.id === +x.dataset.id))),
    );
  document
    .querySelectorAll(".remove")
    .forEach(
      (x) =>
        (x.onclick = () =>
          confirm("Удалить идею?") &&
          act(`/api/ideas/${x.dataset.id}`, {}, "DELETE")),
    );
}
function vote(b) {
  const v = data.vote,
    me = v?.members.find((m) => +m.id === +data.user.id);
  if (v) {
    const canCloseVote =
      +data.user.id === +v.organizer_id ||
      +data.user.id === +data.company.owner_id;
    b.innerHTML = `<div class="notice">Организатор: <b>${esc(v.organizer)}</b><br>${me?.idea_title ? `Ваш выбор: <b>${esc(me.idea_title)}</b>. Можно изменить.` : "Вы ещё не голосовали."}</div>${data.ideas.map((x) => card(x, true, me?.idea_title)).join("")}<div class="card"><b>✅ Проголосовали:</b> ${
      v.members
        .filter((x) => x.idea_title)
        .map((x) => esc(x.display_name))
        .join(", ") || "никто"
    }<br><b>⏳ Ожидаем:</b> ${
      v.members
        .filter((x) => !x.idea_title)
        .map((x) => esc(x.display_name))
        .join(", ") || "все"
    }${canCloseVote ? '<button class="primary" id="closeVote">Завершить голосование</button>' : `<div class="notice muted">Голосование завершит ${esc(v.organizer)} или владелец компании.</div>`}</div>`;
    document
      .querySelectorAll(".vote-btn")
      .forEach(
        (x) =>
          (x.onclick = () =>
            act("/api/vote/cast", { round_id: v.id, idea_id: +x.dataset.id })),
      );
    if (canCloseVote)
      closeVote.onclick = () => act("/api/vote/close", { round_id: v.id });
    return;
  }
  const p = data.date_poll;
  if (p) {
    const owner =
      +data.user.id === +data.company.owner_id ||
      +data.user.id === +p.created_by;
    b.innerHTML = `<div class="notice">Победила идея <b>${esc(p.title)}</b>. Выберите удобную дату.</div>${p.options.map((o) => `<button class="secondary date-choice ${o.mine ? "selected" : ""}" data-option="${o.id}">${new Date(o.scheduled_at).toLocaleString("ru-RU")} · ${o.votes} голосов</button>`).join("") || '<div class="empty">Даты ещё не предложены.</div>'}${owner ? `<form id="dateForm"><label>Добавить вариант</label><input type="datetime-local" name="scheduled_at" required><button class="primary">Добавить дату</button></form><div class="actions">${p.options.map((o) => `<button class="pill confirm-date" data-option="${o.id}">Назначить ${new Date(o.scheduled_at).toLocaleDateString("ru-RU")}</button>`).join("")}</div>` : ""}`;
    document
      .querySelectorAll(".date-choice")
      .forEach(
        (x) =>
          (x.onclick = () =>
            act("/api/date/vote", { option_id: +x.dataset.option })),
      );
    if (owner) {
      dateForm.onsubmit = (e) => {
        e.preventDefault();
        act("/api/date/options", {
          round_id: p.id,
          scheduled_at: new FormData(e.target).get("scheduled_at"),
        });
      };
      document.querySelectorAll(".confirm-date").forEach(
        (x) =>
          (x.onclick = async () => {
            await act("/api/date/confirm", { option_id: +x.dataset.option });
            tab = "activity";
            await refresh();
          }),
      );
    }
    return;
  }
  if (data.activity) {
    b.innerHTML =
      '<div class="notice"><b>Новое голосование пока недоступно.</b><br>Сначала завершите текущую активность: всем участникам нужно подтвердить участие, и кто-то должен добавить фото.</div><button class="primary" id="goActivity">Перейти к текущему плану</button>';
    goActivity.onclick = () => {
      tab = "activity";
      render();
    };
    return;
  }
  const missingIdeas = Math.max(0, 2 - data.ideas.length);
  if (missingIdeas) {
    b.innerHTML = `<div class="empty">Добавьте ещё ${missingIdeas} ${missingIdeas === 1 ? "идею" : "идеи"}, чтобы начать выбор.</div><button class="primary" id="startVote" disabled aria-disabled="true">Начать голосование</button><button class="secondary" id="addMissingIdea">+ Добавить идею</button>`;
    addMissingIdea.onclick = () => {
      tab = "ideas";
      render();
      openIdea();
    };
    return;
  }
  b.innerHTML =
    '<div class="notice">Все готово: участники смогут выбрать одну идею и изменить голос до завершения.</div><button class="primary" id="startVote" aria-disabled="false">Начать голосование</button>';
  startVote.onclick = () => act("/api/vote/start");
}
function activity(b) {
  const a = data.activity;
  if (!a) {
    b.innerHTML = '<div class="empty">Нет запланированной активности.</div>';
    return;
  }
  const me = data.activity_people.find((x) => +x.id === +data.user.id);
  const canReschedule =
    +a.created_by === +data.user.id || +data.company.owner_id === +data.user.id;
  b.innerHTML = `<article class="card winner"><small>ЗАПЛАНИРОВАНО</small><h3>${esc(a.title)}</h3><p>${new Date(a.scheduled_at).toLocaleString("ru-RU")}</p>${canReschedule ? `<form id="rescheduleForm"><label>Изменить дату и время</label><input type="datetime-local" name="scheduled_at" value="${a.scheduled_at.slice(0, 16)}" required><button class="secondary">Сохранить новую дату</button></form>` : ""}</article><div class="card"><b>Подтверждения</b>${data.activity_people.map((x) => `<p>${x.confirmed ? "✅" : "⏳"} ${esc(x.display_name)}</p>`).join("")}${!me?.confirmed ? '<button class="primary" id="confirmActivity">Я участвовал(а)</button>' : '<div class="notice">Ваше подтверждение получено</div>'}<form id="photoForm" class="photo-form"><label>Добавьте фото — без него ачивка не выдаётся</label><label class="photo-picker" id="photoPicker" for="photoInput">📷 Выбрать фото</label><input class="visually-hidden" id="photoInput" type="file" name="photo" accept="image/jpeg,image/png,image/webp" required><div class="photo-preview hidden" id="photoPreview"><img alt="Предпросмотр выбранного фото"></div><div class="photo-status muted" id="photoStatus" aria-live="polite">Фото ещё не выбрано</div><button class="secondary" id="photoUpload" disabled aria-disabled="true">Загрузить фото</button></form></div>`;
  if (canReschedule) {
    const form = document.querySelector("#rescheduleForm");
    form.scheduled_at.min = new Date().toISOString().slice(0, 16);
    form.onsubmit = (event) => {
      event.preventDefault();
      act(
        `/api/activity/${a.id}`,
        { scheduled_at: new FormData(form).get("scheduled_at") },
        "PUT",
      );
    };
  }
  if (!me?.confirmed)
    confirmActivity.onclick = () => act(`/api/activity/${a.id}/confirm`);
  photoInput.onchange = () => {
    const file = photoInput.files?.[0];
    photoUpload.disabled = !file;
    photoUpload.setAttribute("aria-disabled", String(!file));
    if (!file) {
      photoPreview.classList.add("hidden");
      photoStatus.textContent = "Фото ещё не выбрано";
      return;
    }
    photoPreview.querySelector("img").src = URL.createObjectURL(file);
    photoPreview.classList.remove("hidden");
    photoStatus.textContent = `Выбрано: ${file.name}`;
  };
  photoForm.onsubmit = async (e) => {
    e.preventDefault();
    photoUpload.disabled = true;
    photoStatus.textContent = "Загружаем фото…";
    try {
      await api(`/api/activity/${a.id}/photo`, {
        method: "POST",
        body: new FormData(e.target),
      });
      photoStatus.textContent = "Фото загружено ✓";
      await refresh();
    } catch (error) {
      photoStatus.textContent =
        "Не удалось загрузить фото. Попробуйте ещё раз.";
      photoUpload.disabled = false;
    }
  };
}
function archive(b) {
  b.innerHTML =
    data.archive
      .map(
        (x) =>
          `<article class="card"><small>🏆 ВЫПОЛНЕНО</small><h3>${esc(x.title)}</h3><div class="gallery">${x.photos.map((p) => `<div class="archive-photo-frame archive-photo-loading"><span>Загружаем фото…</span><img class="archive-photo" data-photo="${p.id}" alt="Фото с активности ${esc(x.title)}"></div>`).join("")}</div><button class="secondary share" data-title="${esc(x.title)}">Поделиться в Telegram</button></article>`,
      )
      .join("") ||
    '<div class="empty">Здесь появятся выполненные приключения.</div>';
  photos();
  document
    .querySelectorAll(".share")
    .forEach(
      (x) =>
        (x.onclick = () =>
          openTelegram(
            `https://t.me/share/url?url=${encodeURIComponent(botUrl)}&text=${encodeURIComponent(`Мы сделали это: ${x.dataset.title} 🏆 Попробуйте let’s go! вместе с друзьями.`)}`,
          )),
    );
}
async function photos() {
  for (const img of document.querySelectorAll("[data-photo]"))
    try {
      const r = await fetch(`/api/archive/photo/${img.dataset.photo}`, {
        headers: { "X-Telegram-Init-Data": init },
      });
      if (!r.ok) throw 0;
      img.onload = () =>
        img.parentElement.classList.remove("archive-photo-loading");
      img.src = URL.createObjectURL(await r.blob());
    } catch (_) {
      img.parentElement.classList.remove("archive-photo-loading");
      img.parentElement.innerHTML =
        '<span class="photo-error">Фото недоступно</span>';
    }
}
function openIdea(x = null) {
  editing = x?.id || null;
  ideaTitle.textContent = x ? "Изменить идею" : "Новая идея";
  ideaForm.reset();
  if (x) {
    ideaForm.title.value = x.title;
    ideaForm.description.value = x.description || "";
    ideaForm.anonymous.checked = !!x.anonymous;
    ["difficulty", "budget", "duration"].forEach(
      (k) =>
        (ideaForm.querySelector(`[name=${k}][value="${x[k]}"]`).checked = true),
    );
  }
  modal("#ideaModal");
}
function account() {
  const s = data.settings;
  const isOwner = +data.company.owner_id === +data.user.id;
  accountBody.innerHTML = `<div class="notice">Сейчас выбрана компания: <b>${esc(data.company.name)}</b></div><button class="primary" id="inviteCompany">Пригласить друзей в эту компанию</button><h3>Мои компании</h3>${data.companies.map((c) => `<button class="secondary switch" data-id="${c.id}" ${c.active ? "disabled" : ""}>${c.active ? "✓ Сейчас: " : "Переключиться: "}${esc(c.name)}</button>`).join("")}<button class="primary" id="newCompany">+ Новая компания</button><button class="danger" id="leaveCompany">Выйти из компании</button>${isOwner ? '<p class="muted">Вы владелец. При выходе компания перейдёт самому давнему участнику.</p>' : ""}<h3>Участники</h3><p>${data.members.map((x) => esc(x.display_name)).join(", ")}</p><h3>Напоминания</h3>${[
    ["reminder_week", "За неделю"],
    ["reminder_day", "За день"],
    ["reminder_hours", "За несколько часов"],
    ["reminder_event", "В момент начала"],
    ["reminder_followup", "После встречи"],
  ]
    .map(
      ([k, l]) =>
        `<label class="setting">${l}<input type="checkbox" data-setting="${k}" ${s[k] ? "checked" : ""}></label>`,
    )
    .join(
      "",
    )}<h3>Статистика</h3><p>🏆 ${data.stats.completed} · 💡 ${data.stats.ideas_created} · 🗳 ${data.stats.votes_cast}</p><p>${data.achievements.join("<br>") || "Первая ачивка уже близко!"}</p>`;
  modal("#accountModal");
  inviteCompany.onclick = inviteFriends;
  document.querySelectorAll(".switch").forEach(
    (button) =>
      (button.onclick = async () => {
        try {
          const result = await api("/api/company/switch", {
            method: "POST",
            body: JSON.stringify({ company_id: +button.dataset.id }),
          });
          modal("#accountModal", false);
          await refresh();
          flash(Error(`Вы переключились на компанию «${result.name}»`));
        } catch (error) {
          flash(error);
        }
      }),
  );
  newCompany.onclick = () => {
    modal("#accountModal", false);
    modal("#companyModal");
  };
  leaveCompany.onclick = async () => {
    if (!confirm("Выйти из компании?")) return;
    try {
      const result = await api("/api/company/leave", {
        method: "POST",
        body: "{}",
      });
      modal("#accountModal", false);
      await refresh();
      flash(
        Error(
          result.new_owner
            ? `Вы вышли. Новый владелец компании — ${result.new_owner}.`
            : "Вы вышли из компании.",
        ),
      );
    } catch (error) {
      flash(error);
    }
  };
  document.querySelectorAll("[data-setting]").forEach(
    (x) =>
      (x.onchange = () => {
        const body = {};
        document
          .querySelectorAll("[data-setting]")
          .forEach((y) => (body[y.dataset.setting] = y.checked));
        act("/api/settings", body);
      }),
  );
}
document.querySelectorAll(".nav button").forEach(
  (b) =>
    (b.onclick = () => {
      tab = b.dataset.tab;
      render();
    }),
);
companyTrigger.onclick = account;
document
  .querySelectorAll(".close")
  .forEach(
    (x) => (x.onclick = () => modal("#" + x.closest(".modal").id, false)),
  );
gotIt.onclick = () => {
  localStorage.setItem("lg-onboarding", "1");
  modal("#onboarding", false);
};
const labels = [
  ["difficulty", "Сложность"],
  ["budget", "Бюджет"],
  ["duration", "Длительность"],
];
ratings.innerHTML = labels
  .map(
    ([n, l]) =>
      `<label>${l} · 1–5</label><div class="rating">${[1, 2, 3, 4, 5].map((i) => `<input id="${n}${i}" type="radio" name="${n}" value="${i}" required><label for="${n}${i}">${i}</label>`).join("")}</div>`,
  )
  .join("");
ideaForm.onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target),
    body = Object.fromEntries(f);
  body.anonymous = f.has("anonymous");
  try {
    await api(editing ? `/api/ideas/${editing}` : "/api/ideas", {
      method: editing ? "PUT" : "POST",
      body: JSON.stringify(body),
    });
    modal("#ideaModal", false);
    await refresh();
  } catch (e) {
    flash(e);
  }
};
companyForm.onsubmit = async (e) => {
  e.preventDefault();
  try {
    await api("/api/company", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(e.target))),
    });
    modal("#companyModal", false);
    await refresh();
  } catch (e) {
    flash(e);
  }
};
load();
