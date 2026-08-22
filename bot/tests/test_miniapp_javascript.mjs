import fs from "node:fs";
import test from "node:test";

test("Mini App client JavaScript parses", () => {
  const script = fs.readFileSync(
    new URL("../miniapp.js", import.meta.url),
    "utf8",
  );
  new Function(script);
});

test("voting gives immediate and persisted visual feedback", () => {
  const html = fs.readFileSync(
    new URL("../miniapp.js", import.meta.url),
    "utf8",
  );
  for (const marker of [
    "✓ Ваш выбор",
    "Ваш выбор:",
    "Можно изменить.",
    "Проголосовали:",
  ]) {
    if (!html.includes(marker))
      throw new Error(`Missing voting feedback: ${marker}`);
  }
});

test("planning uses an in-app date poll instead of a browser prompt", () => {
  const html =
    fs.readFileSync(new URL("../miniapp.html", import.meta.url), "utf8") +
    fs.readFileSync(new URL("../miniapp.js", import.meta.url), "utf8");
  if (
    !html.includes('id="dateForm"') ||
    !html.includes('type="datetime-local"') ||
    !html.includes("/api/date/vote") ||
    !html.includes("/api/date/confirm")
  ) {
    throw new Error("Missing in-app date poll");
  }
  if (html.includes("prompt(`Победила идея"))
    throw new Error("Browser prompt must not be used");
});

test("compact layout does not cover idea cards with a floating add button", () => {
  const html = fs.readFileSync(
    new URL("../miniapp.html", import.meta.url),
    "utf8",
  );
  const script = fs.readFileSync(
    new URL("../miniapp.js", import.meta.url),
    "utf8",
  );
  if (!script.includes('id="add"') || !html.includes('class="skeleton"')) {
    throw new Error("Missing compact add action or loading skeleton");
  }
  if (html.includes('class="fab"'))
    throw new Error("Floating add button still overlaps content");
});

test("archive photos are loaded through the authenticated endpoint", () => {
  const html = fs.readFileSync(
    new URL("../miniapp.js", import.meta.url),
    "utf8",
  );
  for (const marker of [
    "data-photo",
    "async function photos",
    "/api/archive/photo/",
    "X-Telegram-Init-Data",
    "URL.createObjectURL",
  ]) {
    if (!html.includes(marker))
      throw new Error(`Missing secure archive photo behavior: ${marker}`);
  }
});

test("new social and activity features are reachable in the interface", () => {
  const html =
    fs.readFileSync(new URL("../miniapp.html", import.meta.url), "utf8") +
    fs.readFileSync(new URL("../miniapp.js", import.meta.url), "utf8");
  for (const marker of [
    "/comments",
    "/reactions",
    "/api/company/switch",
    "/api/settings",
    "/confirm",
    'type="file"',
    "Поделиться",
    "lg-onboarding",
    "rescheduleForm",
    "Сохранить новую дату",
  ]) {
    if (!html.includes(marker))
      throw new Error(`Missing feature marker: ${marker}`);
  }
});

test("guided next action and Telegram sharing are explicit", () => {
  const script = fs.readFileSync(
    new URL("../miniapp.js", import.meta.url),
    "utf8",
  );
  for (const marker of [
    "data-next-tab",
    "Новое голосование пока недоступно",
    "Пригласить друзей в эту компанию",
    "https://t.me/share/url",
    "https://t.me/lets_go_friends_bot?start=app",
    "Вы переключились на компанию",
  ]) {
    if (!script.includes(marker))
      throw new Error(`Missing journey marker: ${marker}`);
  }
  if (script.includes('id="random"'))
    throw new Error("Random idea button must be removed");
});

test("bottom navigation remains the single source of selected tab", () => {
  const combined =
    fs.readFileSync(new URL("../miniapp.html", import.meta.url), "utf8") +
    fs.readFileSync(new URL("../miniapp.js", import.meta.url), "utf8");
  for (const tab of ["ideas", "vote", "activity", "archive"]) {
    if (!combined.includes(`data-tab="${tab}"`))
      throw new Error(`Missing bottom navigation tab: ${tab}`);
  }
  if (!combined.includes('b.classList.toggle("active", b.dataset.tab === tab)'))
    throw new Error("Bottom navigation must own the active state");
});

test("navigation has one contextual next action instead of duplicate steps", () => {
  const script = fs.readFileSync(
    new URL("../miniapp.js", import.meta.url),
    "utf8",
  );
  for (const marker of [
    "function nextAction",
    'id="nextAction"',
    "data-next-tab",
  ]) {
    if (!script.includes(marker))
      throw new Error(`Missing contextual navigation marker: ${marker}`);
  }
  if (script.includes('class="journey"'))
    throw new Error("Hero must not duplicate bottom navigation");
});

test("company management is a labelled header action", () => {
  const html = fs.readFileSync(
    new URL("../miniapp.html", import.meta.url),
    "utf8",
  );
  const script = fs.readFileSync(
    new URL("../miniapp.js", import.meta.url),
    "utf8",
  );
  if (
    !html.includes('id="companyTrigger"') ||
    !html.includes('id="companyName"')
  )
    throw new Error("Company action must be visibly labelled");
  if (!script.includes("companyName.textContent"))
    throw new Error("Company action must show the active company name");
  if (
    !script.includes("function syncCompanyHeader") ||
    !script.includes("syncCompanyHeader();")
  )
    throw new Error("Company label must refresh after switching companies");
});

test("only the organizer or company owner can close voting", () => {
  const script = fs.readFileSync(
    new URL("../miniapp.js", import.meta.url),
    "utf8",
  );
  for (const marker of [
    "const canCloseVote",
    "v.organizer_id",
    "data.company.owner_id",
    "Голосование завершит",
  ]) {
    if (!script.includes(marker))
      throw new Error(`Missing vote permission marker: ${marker}`);
  }
});

test("impossible actions are disabled with an explanation", () => {
  const script = fs.readFileSync(
    new URL("../miniapp.js", import.meta.url),
    "utf8",
  );
  for (const marker of [
    'id="startVote" disabled',
    "Добавьте ещё",
    "aria-disabled",
  ]) {
    if (!script.includes(marker))
      throw new Error(`Missing blocked action marker: ${marker}`);
  }
});

test("photo upload and archive expose loading states", () => {
  const combined =
    fs.readFileSync(new URL("../miniapp.js", import.meta.url), "utf8") +
    fs.readFileSync(new URL("../miniapp.css", import.meta.url), "utf8");
  for (const marker of [
    'id="photoPicker"',
    'id="photoPreview"',
    'id="photoStatus"',
    "Фото загружено",
    "archive-photo-loading",
    "Загружаем фото",
  ]) {
    if (!combined.includes(marker))
      throw new Error(`Missing photo state marker: ${marker}`);
  }
});
