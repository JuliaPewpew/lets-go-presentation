import fs from "node:fs";
import test from "node:test";

test("Mini App client JavaScript parses", () => {
  const script = fs.readFileSync(new URL("../miniapp.js", import.meta.url), "utf8");
  new Function(script);
});

test("voting gives immediate and persisted visual feedback", () => {
  const html = fs.readFileSync(new URL("../miniapp.js", import.meta.url), "utf8");
  for (const marker of ["✓ Ваш выбор", "Ваш выбор:", "Можно изменить.", "Проголосовали:"]) {
    if (!html.includes(marker)) throw new Error(`Missing voting feedback: ${marker}`);
  }
});

test("planning uses an in-app date poll instead of a browser prompt", () => {
  const html = fs.readFileSync(new URL("../miniapp.html", import.meta.url), "utf8") +
    fs.readFileSync(new URL("../miniapp.js", import.meta.url), "utf8");
  if (!html.includes('id="dateForm"') || !html.includes('type="datetime-local"') ||
      !html.includes("/api/date/vote") || !html.includes("/api/date/confirm")) {
    throw new Error("Missing in-app date poll");
  }
  if (html.includes("prompt(`Победила идея")) throw new Error("Browser prompt must not be used");
});

test("compact layout does not cover idea cards with a floating add button", () => {
  const html = fs.readFileSync(new URL("../miniapp.html", import.meta.url), "utf8");
  const script = fs.readFileSync(new URL("../miniapp.js", import.meta.url), "utf8");
  if (!script.includes('id="add"') || !html.includes('class="skeleton"')) {
    throw new Error("Missing compact add action or loading skeleton");
  }
  if (html.includes('class="fab"')) throw new Error("Floating add button still overlaps content");
});

test("archive photos are loaded through the authenticated endpoint", () => {
  const html = fs.readFileSync(new URL("../miniapp.js", import.meta.url), "utf8");
  for (const marker of ["data-photo", "async function photos", "/api/archive/photo/", "X-Telegram-Init-Data", "URL.createObjectURL"]) {
    if (!html.includes(marker)) throw new Error(`Missing secure archive photo behavior: ${marker}`);
  }
});

test("new social and activity features are reachable in the interface", () => {
  const html = fs.readFileSync(new URL("../miniapp.html", import.meta.url), "utf8") +
    fs.readFileSync(new URL("../miniapp.js", import.meta.url), "utf8");
  for (const marker of ["/comments", "/reactions", "/api/company/switch", "/api/settings",
    "/confirm", 'type="file"', "Случайная идея", "Поделиться", "lg-onboarding"]) {
    if (!html.includes(marker)) throw new Error(`Missing feature marker: ${marker}`);
  }
});
