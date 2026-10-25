// Copies Silero VAD's model, its audio worklet and onnxruntime's WASM files into public/vad/,
// so the app serves them itself (no CDN). Run by `npm run build`; also run it once before
// `npm run dev`. public/vad/ is gitignored.
import { copyFileSync, mkdirSync, readdirSync } from "node:fs";
import { join } from "node:path";

const out = "public/vad";
mkdirSync(out, { recursive: true });
const sources = [
  ["node_modules/@ricky0123/vad-web/dist", /^(vad\.worklet\.bundle\.min\.js|silero_vad_.*\.onnx)$/],
  ["node_modules/onnxruntime-web/dist", /^ort-wasm-simd-threaded\.(wasm|mjs)$/],
];
for (const [dir, pattern] of sources) {
  for (const name of readdirSync(dir).filter((n) => pattern.test(n))) {
    copyFileSync(join(dir, name), join(out, name));
    console.log(`copied ${name}`);
  }
}
