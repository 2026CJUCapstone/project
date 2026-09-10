import { loader } from "@monaco-editor/react";
import distribution from 'virtual:local-monaco';

// The full installed editor and all services are copied unchanged by Vite.
// One local loader instance avoids rebundling Monaco and TypeScript while
// keeping language features; no CDN or second ESM Monaco instance is used.
let configured = false;

export function configureLocalMonaco() {
  if (configured) return;

  // The supplied AMD entry installs its own worker factory, including its
  // ready handshake and local importScripts URLs. Do not replace that protocol.
  loader.config({ paths: { vs: distribution.vs } });
  configured = true;
}
