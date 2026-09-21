// End-to-end test of the Figma plugin UI in headless Chromium with a mocked Figma API.
// Flow: open -> scan -> audit -> select recommended fixes -> preview -> apply -> rescan -> preview again (0 changes)
//       -> downloads -> import CSS.
// Usage: node tests/e2e-plugin.js [screenshot-dir]
const fs = require("fs");
const os = require("os");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.join(__dirname, "..");
const P = path.join(ROOT, "skills/token-push-figma/figma-plugin");
const shotDir = process.argv[2];
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "tf-e2e-"));
fs.copyFileSync(path.join(P, "ui.html"), path.join(tmp, "ui.html"));
const fixture = fs.readFileSync(path.join(__dirname, "fixtures/figma-variables-demo.json"), "utf8");
const shell = fs.readFileSync(path.join(P, "shell.js"), "utf8").replace("figma.showUI(__html__,", "figma.showUI(null,");
fs.writeFileSync(path.join(tmp, "harness.html"), `<!doctype html><body style="margin:0">
<iframe id="ui" src="ui.html" style="width:600px;height:760px;border:0"></iframe>
<script>${fs.readFileSync(path.join(__dirname, "mock-figma-api.js"), "utf8")}</script>
<script>
  window.figma = mkFigma(${fixture});
  figma.showUI = function () {};
  figma.notify = function (t) { window.__notes = (window.__notes || []).concat([t]); };
  figma.closePlugin = function () {};
  figma.ui = { postMessage: function (m) { document.getElementById("ui").contentWindow.postMessage({ pluginMessage: m }, "*"); } };
  window.addEventListener("message", function (e) { if (e.data && e.data.pluginMessage) figma.ui.onmessage(e.data.pluginMessage); });
</script>
<script>${fs.readFileSync(path.join(P, "core.js"), "utf8")}</script>
<script>${shell}</script>
</body>`);

let fails = 0;
const check = (ok, label) => { console.log((ok ? "  ok   " : "  FAIL ") + label); if (!ok) fails++; };

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 600, height: 760 }, acceptDownloads: true });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto("file://" + path.join(tmp, "harness.html"));
  const ui = page.frameLocator("#ui");
  const shot = async (name) => { if (shotDir) await page.screenshot({ path: path.join(shotDir, name + ".png") }); };
  const tab = (name) => ui.locator(`nav button[data-tab="${name}"]`).click();
  const scores = async () => (await ui.locator(".card .v").allInnerTexts()).map((t) => parseInt(t, 10));

  await ui.locator(".card").first().waitFor({ timeout: 10000 });
  const s0 = await scores();
  check(s0.length === 3, "scan and audit on open: 3 scores " + JSON.stringify(s0));
  check((await ui.locator("#status").innerText()).includes("variables"), "status shows variable count");
  check((await ui.locator("select[data-tier]").count()) === 4, "4 collections with tier selectors");
  await shot("1-overview");

  await tab("findings");
  check((await ui.locator("#tab-findings .f").count()) > 5, "findings listed");
  await shot("2-findings");

  await tab("contrast");
  const failRows = await ui.locator("#tab-contrast tr").count();
  check(failRows > 1, "contrast failures listed (" + (failRows - 1) + ")");
  check((await ui.locator("#tab-contrast").innerText()).includes("APCA"), "APCA shown as WCAG 3 draft preview");
  await shot("3-contrast");

  await tab("fix");
  await ui.locator("#recommend").click();
  await ui.locator("#preview").click();
  await ui.locator("#dry .note").waitFor();
  const dryText = await ui.locator("#dry").innerText();
  check(/Preview: \d+ changes/.test(dryText), "preview: " + dryText.split("\n")[0]);
  check(dryText.includes("Projected scores"), "projected scores shown");
  check(!(await ui.locator("#apply").isDisabled()), "apply enabled after preview");
  await shot("4-fix-preview");

  await ui.locator("#apply").click();
  await ui.locator("#status").filter({ hasText: "changes applied" }).waitFor({ timeout: 10000 });
  const s1 = await scores();
  check(s1[1] > s0[1], "accessibility improved after apply: " + s0[1] + " -> " + s1[1]);
  check(s1[0] >= s0[0] && s1[2] >= s0[2], "structure and AI-ready not worse: " + JSON.stringify(s0) + " -> " + JSON.stringify(s1));
  check((await ui.locator(".delta").count()) > 0, "before/after delta shown");
  await shot("5-overview-after");

  await tab("fix");
  await ui.locator("#preview").click();
  await ui.locator("#dry .note").waitFor();
  const again = await ui.locator("#dry .note").innerText();
  check(again.includes("Preview: 0 changes"), "second preview is a no-op: " + again.split("\n")[0]);
  check(await ui.locator("#apply").isDisabled(), "apply disabled when nothing to change");

  await tab("export");
  for (const [k, name] of [["report", "token-audit-report.md"], ["css", "tokens.css"], ["manifest", "tokens.manifest.json"], ["audit-md", "audit.md"], ["export", "figma-variables.json"]]) {
    const [dl] = await Promise.all([page.waitForEvent("download"), ui.locator(`[data-dl="${k}"]`).click()]);
    const p = await dl.path();
    const size = fs.statSync(p).size;
    check(dl.suggestedFilename() === name && size > 100, "download " + name + " (" + size + " bytes)");
    if (shotDir) fs.copyFileSync(p, path.join(shotDir, name));
  }
  await ui.locator("#importFile").setInputFiles(path.join(__dirname, "fixtures/tokens-demo.css"));
  await ui.locator("#status").filter({ hasText: "tokens-demo.css" }).waitFor();
  check((await ui.locator("select[data-tier]").count()) === 4, "CSS import audited (Primitives, Semantic, Theme, Responsive)");
  await shot("6-css-import");

  check(errors.length === 0, "no JS errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  await browser.close();
  console.log(fails ? fails + " failed" : "e2e ok");
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
