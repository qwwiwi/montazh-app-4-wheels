// Capture the current public homepage in a fresh, anonymous Chrome profile.
const { execFileSync } = require("node:child_process");
const { createRequire } = require("node:module");
const path = require("node:path");
const root = execFileSync("npm", ["root", "-g"], {encoding:"utf8"}).trim();
const puppeteer = createRequire(path.join(root, "hyperframes/package.json"))("puppeteer-core");

async function capture(filename, executablePath) {
  const browser = await puppeteer.launch({headless:true, executablePath, args:["--lang=ru-RU"]});
  try {
    const page = await browser.newPage();
    await page.setViewport({width:1260,height:800,deviceScaleFactor:1});
    const response = await page.goto("https://www.amocrm.ru/", {waitUntil:"domcontentloaded",timeout:60000});
    if (!response || !response.ok() || new URL(page.url()).origin !== "https://www.amocrm.ru") {
      throw new Error("Publisher homepage did not load.");
    }
    await page.waitForFunction(() => /amoCRM/i.test(document.title) &&
      /клиент|продаж/i.test(document.body.innerText) && document.querySelector(".page_header__logo_image"));
    await page.evaluate(() => Promise.race([document.fonts.ready, new Promise(resolve => setTimeout(resolve, 3500))]));
    await page.waitForNetworkIdle({idleTime:500,timeout:5000}).catch(() => {});
    await page.screenshot({path:filename});
  } finally {
    await browser.close();
  }
}
capture(process.argv[2],process.argv[3]).catch(e => { console.error(e.message);process.exitCode=1; });
