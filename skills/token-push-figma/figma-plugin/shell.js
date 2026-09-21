
// ---- Figma plugin shell ----------------------------------------------------
// The UI (ui.html) runs the audit engine; this side only reads and writes variables.
figma.showUI(__html__, { width: 600, height: 760, themeColors: true });

figma.ui.onmessage = async (msg) => {
  try {
    if (msg.type === "scan") {
      const data = await tfExport();
      figma.ui.postMessage({ type: "scan", data, afterApply: !!msg.afterApply });
    } else if (msg.type === "apply") {
      const report = await tfApply(msg.manifest, msg.options);
      figma.ui.postMessage({ type: "report", report });
      if (!report.dryRun) figma.notify("Token Foundry: " + report.summary.totalChanges + " changes applied" + (report.summary.errors ? ", " + report.summary.errors + " errors" : ""));
    } else if (msg.type === "close") {
      figma.closePlugin();
    }
  } catch (e) {
    figma.ui.postMessage({ type: "error", message: String((e && e.message) || e) });
  }
};
