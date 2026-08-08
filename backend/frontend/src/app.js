import * as weeklyPayloadBridge from "./core/weekly-payload-bridge.js";
import { BOOTSTRAP_CONTRACT, bootstrapUi } from "./bootstrap.js";

// W3's production artifact is a classic self-contained inline script. The
// source graph remains native ES modules, but this entry deliberately exports
// nothing so Vite can emit one IIFE with no browser import/export syntax.
if (typeof window !== "undefined" && typeof document !== "undefined") {
  // These reviewed release identities are runtime-visible on the root element
  // so tree-shaking cannot silently remove the markers verified by ui_bundle.py.
  document.documentElement.dataset.hermesUiScript = "HERMES_UI_SCRIPT_OPEN:";
  document.documentElement.dataset.hermesUiBootstrap = BOOTSTRAP_CONTRACT;
  weeklyPayloadBridge.installWeeklyPayloadBridge(window);
  bootstrapUi();
}
