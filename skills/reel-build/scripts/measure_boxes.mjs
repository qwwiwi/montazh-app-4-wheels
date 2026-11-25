// Measure real element boxes of a generated reel composition in headless Chrome.
//
// usage: node measure_boxes.mjs <project dir> <out.json>
//
// puppeteer-core is taken from the global HyperFrames install (it ships with it), Chrome from
// CHROME_PATH or the usual macOS location. The page is loaded from file:// (fonts and GSAP are
// local), the timeline is moved to its end so every revealed item has its final box, and the boxes
// are written as JSON: every caption (box of the group + box of each word) and, per scene, its
// cards and the text/graphic parts inside them (parts that sit in a scrolling window are skipped).
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [, , projectArg, outArg] = process.argv;
if (!projectArg || !outArg) {
  console.error("usage: node measure_boxes.mjs <project dir> <out.json>");
  process.exit(2);
}

const globalRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
const require = createRequire(resolve(globalRoot, "hyperframes", "package.json"));
const puppeteer = require("puppeteer-core");

const chrome = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const project = resolve(projectArg);
const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-sandbox", "--allow-file-access-from-files"] });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1080, height: 1920, deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(resolve(project, "index.html")).href, { waitUntil: "load" });
  // the page names its caption/body family (Golos Text, or Inter Tight of the html-components kit)
  const family = await page.evaluate(() => document.querySelector('meta[name="reel-font"]')?.content || "Golos Text");
  await page.evaluate(async (family) => {
    await document.fonts.load(`800 60px '${family}'`, "Аб Claude");
    await document.fonts.load("500 30px 'JetBrains Mono'", "Аб Claude");
    await document.fonts.ready;
  }, family);
  const result = await page.evaluate((family) => {
    const tls = window.__timelines || {};
    for (const k of Object.keys(tls)) tls[k].progress(1);
    const rect = (r) => ({ x0: r.left, y0: r.top, x1: r.right, y1: r.bottom, w: r.width, h: r.height });
    const box = (el) => rect(el.getBoundingClientRect());
    const textBox = (e) => {
      const range = document.createRange();
      range.selectNodeContents(e);
      return rect(range.getBoundingClientRect());
    };
    const captions = [...document.querySelectorAll("[data-cap]")].map((el) => ({
      id: el.id, mode: el.dataset.mode, shot: el.dataset.shot,
      start: parseFloat(el.dataset.start), duration: parseFloat(el.dataset.duration),
      text: el.textContent.trim(), ...box(el),
      words: [...el.querySelectorAll(".w")].map((w) => ({ text: w.textContent.trim(), ...box(w) })),
    }));
    const parseRgb = (str) => {
      const m = str.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const v = m[1].split(",").map(parseFloat);
      return { r: v[0], g: v[1], b: v[2], a: v.length > 3 ? v[3] : 1 };
    };
    const effBg = (el) => {
      for (let e = el; e; e = e.parentElement) {
        const c = parseRgb(getComputedStyle(e).backgroundColor);
        if (c && c.a >= 0.9) return [c.r, c.g, c.b];
      }
      return [255, 255, 255];
    };
    const effOpacity = (el) => {
      let o = 1;
      for (let e = el; e; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity);
      return o;
    };
    const effFg = (el, bg) => {
      const c = parseRgb(getComputedStyle(el).color) || { r: 0, g: 0, b: 0, a: 1 };
      return [c.r * c.a + bg[0] * (1 - c.a), c.g * c.a + bg[1] * (1 - c.a), c.b * c.a + bg[2] * (1 - c.a)];
    };
    const hasOwnText = (e) => [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim() !== "");
    const hasCharSpans = (e) => e.querySelector(":scope > .ch, :scope > .ch2") !== null;
    const scenes = [...document.querySelectorAll(".scene")].map((s) => {
      const zone = s.querySelector("[data-zone]");
      const cards = [...zone.querySelectorAll(".card")].map((c) => ({ id: c.id, ...box(c) }));
      const loose = [...zone.children].filter((e) => !e.classList.contains("card")).map((e) => ({ text: e.tagName.toLowerCase(), ...box(e) }));
      const parts = [];
      for (const e of zone.querySelectorAll("*")) {
        if (e.closest("[data-scroll]")) continue;
        const tag = e.tagName.toLowerCase();
        if (tag === "path" || e.classList.contains("ch") || e.classList.contains("ch2") || e.classList.contains("cr")) continue;
        if (effOpacity(e) < 0.02) continue;                    // not visible at the end of the timeline (a page that was turned, a hidden skeleton)
        const own = hasOwnText(e) || hasCharSpans(e);
        if (!own && tag !== "svg") continue;
        const card = e.closest(".card");
        const b = tag === "svg" ? box(e) : textBox(e);
        const cs = getComputedStyle(e);
        const font = parseFloat(cs.fontSize);
        const bg = effBg(e);
        const opacity = cs.visibility === "hidden" ? 0 : effOpacity(e);
        parts.push({ tag, text: e.textContent.trim().slice(0, 40), ...b, card: card ? card.id : null, font,
                     mono: cs.fontFamily.includes("JetBrains"), fg: effFg(e, bg), bg, opacity });
      }
      return { id: s.id, kind: s.dataset.kind, zone: zone.dataset.zone, start: parseFloat(s.dataset.start), dur: parseFloat(s.dataset.duration), cards, loose, parts };
    });
    const roles = {};
    for (const e of document.querySelectorAll("[data-role]")) {
      roles[e.dataset.role] = { ...box(e), text: e.textContent.trim(), font: parseFloat(getComputedStyle(e).fontSize) };
    }
    const fontsOk = document.fonts.check(`800 60px '${family}'`, "Аб") && document.fonts.check("500 30px 'JetBrains Mono'", "Аб");
    return { captions, scenes, roles, fontsOk, family, timelines: Object.keys(tls) };
  }, family);
  writeFileSync(resolve(outArg), JSON.stringify(result, null, 1));
  console.log(`measured ${result.captions.length} captions, ${result.scenes.length} scenes, fonts ok: ${result.fontsOk}`);
} finally {
  await browser.close();
}
