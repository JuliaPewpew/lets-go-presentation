import fs from "node:fs";
import test from "node:test";

test("Mini App client JavaScript parses", () => {
  const html = fs.readFileSync(new URL("../miniapp.html", import.meta.url), "utf8");
  const script = html.split("<script>")[1].split("</script>")[0];
  new Function(script);
});

test("voting gives immediate and persisted visual feedback", () => {
  const html = fs.readFileSync(new URL("../miniapp.html", import.meta.url), "utf8");
  for (const marker of ["Сохраняем…", "✓ Ваш выбор", "Ваш выбор:", "notificationOccurred('success')"]) {
    if (!html.includes(marker)) throw new Error(`Missing voting feedback: ${marker}`);
  }
});

test("planning uses an in-app date form instead of a browser prompt", () => {
  const html = fs.readFileSync(new URL("../miniapp.html", import.meta.url), "utf8");
  if (!html.includes('id="planForm"') || !html.includes('type="datetime-local"')) {
    throw new Error("Missing in-app planning form");
  }
  if (html.includes("prompt(`Победила идея")) throw new Error("Browser prompt must not be used");
});

test("compact layout does not cover idea cards with a floating add button", () => {
  const html = fs.readFileSync(new URL("../miniapp.html", import.meta.url), "utf8");
  if (!html.includes('id="addInline"') || !html.includes("skeleton-card")) {
    throw new Error("Missing compact add action or loading skeleton");
  }
  if (html.includes('class="fab"')) throw new Error("Floating add button still overlaps content");
});

test("archive photos are loaded through the authenticated endpoint", () => {
  const html = fs.readFileSync(new URL("../miniapp.html", import.meta.url), "utf8");
  for (const marker of ["data-photo", "loadArchivePhotos", "X-Telegram-Init-Data", "URL.createObjectURL"]) {
    if (!html.includes(marker)) throw new Error(`Missing secure archive photo behavior: ${marker}`);
  }
});
