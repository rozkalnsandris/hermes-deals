import * as weeklyPayloadBridge from "./core/weekly-payload-bridge.js";
import { bootstrapUi } from "./bootstrap.js";

// Kept through W3 because ui_bundle.py and immutable-release checks still pin
// this reviewed application identity marker. W5 owns marker archaeology cleanup.
const PRODUCTION_BUNDLE_IDENTITY = "HERMES_UI_SCRIPT_OPEN:";
void PRODUCTION_BUNDLE_IDENTITY;

// W3's production artifact is a classic self-contained inline script. The
// source graph remains native ES modules, but the entry deliberately exports
// nothing so Vite can emit one IIFE with no browser import/export syntax.
if (typeof window !== "undefined" && typeof document !== "undefined") {
  weeklyPayloadBridge.installWeeklyPayloadBridge(window);
  bootstrapUi();
}
