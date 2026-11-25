// Capture a Habr article and publisher figures without holding DOM handles across hydration.
const fs = require('node:fs/promises');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {createHash} = require('node:crypto');
const globalModules = execFileSync('npm',['root','-g'],{encoding:'utf8'}).trim();
const fromHyperframes = require('node:module').createRequire(path.join(globalModules,'hyperframes/package.json'));
const puppeteer = fromHyperframes('puppeteer-core');

function permitted(url) {
  const u = new URL(url);
  return u.protocol==='https:' && ['habr.com','habrastorage.org','assets.habr.com'].includes(u.hostname)
    && !u.username && !u.password && (!u.port || u.port==='443');
}
async function restrict(page) {
  await page.setRequestInterception(true);
  page.on('request',r => (permitted(r.url()) && r.method()==='GET' ? r.continue() : r.abort()).catch(()=>{}));
}
function cuePhrases(title) {
  const names=title.match(/[A-Z][a-zA-Z0-9.-]+(?:\s+(?:[A-Z][a-zA-Z0-9.-]+|\d+(?:\.\d+)?)){0,3}/g)||[];
  return [...new Set([title,...names,...names.flatMap(name=>name.split(' ').filter(w=>w.length>=4))])].filter(Boolean).slice(0,24);
}
async function capture(url, folder) {
  const browser = await puppeteer.launch({executablePath:process.env.REEL_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
  try {
    const page = await browser.newPage();
    await page.setViewport({width:900,height:760,deviceScaleFactor:1.5});
    await restrict(page);
    const response = await page.goto(url,{waitUntil:'domcontentloaded',timeout:45000});
    if (!response?.ok()) throw Error('Article unavailable');
    await page.waitForSelector('article h1',{timeout:10000});
    await page.evaluate(()=>document.fonts.ready);
    const record=await page.evaluate(()=>{
      const article=document.querySelector('article');
      const body=article.querySelector('.article-formatted-body,.tm-article-body,#post-content-body');
      if (!body) throw Error('Article body unavailable');
      const h=article.querySelector('h1');
      const box=h.getBoundingClientRect();
      const text=e=>(e?.textContent||'').replace(/\s+/g,' ').trim();
      const figures=Array.from(body.querySelectorAll('img')).map(img=>{
        const figure=img.closest('figure')||img.closest('p')||img.parentElement;
        return {url:img.currentSrc||img.getAttribute('data-src')||img.src,
          caption:(text(figure.querySelector('figcaption'))||img.alt||img.title||'').slice(0,200),
          context:[text(figure.previousElementSibling),text(figure.nextElementSibling)].join(' ').slice(0,540)};
      });
      return {title:text(h), published_at:article.querySelector('time')?.dateTime||'',
        clip:{x:0,y:Math.max(0,Math.floor(box.top+scrollY)-180),width:900,height:Math.min(610,Math.ceil(box.height)+320)},
        paragraphs:Array.from(body.querySelectorAll('p')).map(text).filter(s=>s.length>40).slice(0,24).join('\n').slice(0,3500),figures};
    });
    async function save(file,bytes) {
      await fs.writeFile(path.join(folder,file),bytes);
      return createHash('sha256').update(bytes).digest('hex');
    }
    const base={kind:'news',source_url:url,credit:'habr.com',rights:'Editorial image from the credited article; reuse license unverified.'};
    const primary={...base,id:'article',title:record.title,phrase:record.title,file:'source.png',
      published_at:record.published_at,untrusted_article_excerpt:record.paragraphs,cue_phrases:cuePhrases(record.title),
      screenshot_sha256:await save('source.png',await page.screenshot({clip:record.clip})),related_sources:[]};
    const viewer=await browser.newPage();
    await restrict(viewer);
    const fetched=new Set();
    for (const figure of record.figures) {
      if (primary.related_sources.length>=10) break;
      if (!figure.url || !permitted(figure.url) || fetched.has(figure.url)) continue;
      fetched.add(figure.url);
      const response=await viewer.goto(figure.url,{waitUntil:'load',timeout:15000}).catch(()=>null);
      if (!response?.ok() || !/^image\/(?:jpeg|png|webp|gif|avif)\b/i.test(response.headers()['content-type']||'')) continue;
      const data=await viewer.evaluate(()=>{
        const im=document.images[0];
        if (!im||im.naturalWidth<240||im.naturalHeight<100) return null;
        const scale=Math.min(1,2000/Math.max(im.naturalWidth,im.naturalHeight));
        const canvas=document.createElement('canvas');
        canvas.width=Math.round(im.naturalWidth*scale);canvas.height=Math.round(im.naturalHeight*scale);
        canvas.getContext('2d').drawImage(im,0,0,canvas.width,canvas.height);
        return canvas.toDataURL('image/png').split(',')[1];
      });
      if (!data) continue;
      const id='figure-'+(primary.related_sources.length+1),file=id+'.png';
      const caption=figure.caption.replace(/Источник\.?/gi,'').trim();
      primary.related_sources.push({...base,kind:'screenshot',id,file,title:caption||('Иллюстрация '+(primary.related_sources.length+1)),
        asset_url:figure.url,untrusted_context:figure.context,cue_phrases:cuePhrases(caption),
        screenshot_sha256:await save(file,Buffer.from(data,'base64'))});
    }
    await fs.writeFile(path.join(folder,'source.json'),JSON.stringify(primary,null,2));
  } finally { await browser.close(); }
}
capture(process.argv[2],process.argv[3]).catch(e=>{console.error(e.message);process.exitCode=1;});
