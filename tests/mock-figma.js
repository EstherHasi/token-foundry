// Minimal in-memory mock of the Figma Plugin variables API, enough to run core.js in Node.
// Usage: node tests/mock-figma.js <figma-export.json|-> <manifest.json> <out-export.json>
//   "-" as first argument starts from an empty file.
// Runs simulate, apply, apply again; exits 1 if the second apply is not a no-op or errors appear.
const fs = require("fs");
const path = require("path");

const mkFigma = require("./mock-figma-api.js");

(async () => {
  const [expFile, manFile, outFile] = process.argv.slice(2);
  global.figma = mkFigma(expFile && expFile !== "-" ? JSON.parse(fs.readFileSync(expFile, "utf8")) : null);
  const core = fs.readFileSync(path.join(__dirname, "../skills/token-push-figma/figma-plugin/core.js"), "utf8");
  // eslint-disable-next-line no-eval
  eval(core + ";global.tfApply=tfApply;global.tfExport=tfExport;");
  const man = JSON.parse(fs.readFileSync(manFile, "utf8"));
  const sim = await tfApply(man, { dryRun: true });
  const app = await tfApply(man, { dryRun: false });
  const again = await tfApply(man, { dryRun: false });
  const line = (l, r) => console.log(l.padEnd(9), JSON.stringify(r.summary), r.safety ? "safety:" + r.safety.problems.length : "");
  line("simulate", sim);
  line("apply", app);
  line("again", again);
  if (outFile) fs.writeFileSync(outFile, JSON.stringify(await tfExport(), null, 1));
  const bad = app.errors.length || again.summary.totalChanges !== 0 || sim.summary.totalChanges !== app.summary.totalChanges;
  if (bad) {
    console.error("FAIL", app.errors.slice(0, 5));
    process.exit(1);
  }
})();
