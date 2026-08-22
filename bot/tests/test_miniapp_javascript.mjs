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
