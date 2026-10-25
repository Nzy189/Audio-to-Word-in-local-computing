// Run from the workspace. The access code is accepted only on stdin, without echo.
const {chromium} = require('C:/Users/nzy189/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');

async function readSecret() {
  process.stdout.write('Application access code (input hidden): ');
  if (process.stdin.isTTY) process.stdin.setRawMode(true);
  process.stdin.resume();
  process.stdin.setEncoding('utf8');
  return new Promise(resolve => {
    let value = '';
    function onData(data) {
      value += data;
      if (/[\r\n]/.test(value)) {
        process.stdin.off('data', onData);
        if (process.stdin.isTTY) process.stdin.setRawMode(false);
        process.stdin.pause();
        process.stdout.write('\n');
        resolve(value.trim());
      }
    }
    process.stdin.on('data', onData);
  });
}

(async () => {
  const code = await readSecret();
  const browser = await chromium.launch({channel:'chrome',headless:true});
  const context = await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  const page = await context.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const created=[];
  try {
    await page.goto('https://80.238.236.1',{waitUntil:'networkidle'});
    await page.locator('#code').fill(code);await page.locator('#loginButton').click();
    await page.locator('#appView').waitFor({state:'visible'});
    const before=await (await page.request.get('https://80.238.236.1/api/jobs')).json();
    for(const old of before){
      assert.equal(old.elapsed,null);assert.equal(old.started,null);
      assert.equal(await page.locator(`.job[data-job-id="${old.id}"]`).count(),1);
    }
    console.log('PASS existing records remain visible, historical timing is not invented');
    const results=[];
    for(const [lang,label] of [['zh','中文'],['en','英文']]){
      const name='记录检查-'+label+'-'+Date.now()+'.wav';
      await page.locator('#file').setInputFiles({name,mimeType:'audio/wav',buffer:fs.readFileSync('test-results/'+lang+'.wav')});
      await page.waitForFunction(name=>document.querySelector('#resultName').textContent.includes(name)&&document.querySelector('#resultName').textContent.includes('已完成'),name,{timeout:120000});
      const id=await page.locator('.job.active').getAttribute('data-job-id');created.push(id);
      const job=await (await page.request.get('https://80.238.236.1/api/jobs/'+id)).json();
      assert(job.started>=job.created);assert(job.finished>=job.started);assert(job.elapsed>0);
      assert(Math.abs((job.finished-job.started)-job.elapsed)<0.2);
      assert(job.duration>1);assert(job.text.length>4);
      assert.match(await page.locator(`.job[data-job-id="${id}"]`).innerText(),/录音[\s\S]*耗时[\s\S]*转写时间/);
      const metadata=await page.locator('#resultMeta').innerText();
      for(const field of ['录音时长','转写耗时','提交时间','开始时间','转写时间（完成）'])assert(metadata.includes(field));
      assert(!metadata.includes('未记录'));
      results.push(job);
    }
    for(const job of [results[0],results[1],results[0]]){
      await page.locator(`.job[data-job-id="${job.id}"]`).click();
      await page.waitForFunction(text=>document.querySelector('#result').value===text,job.text);
      assert((await page.locator('#resultName').innerText()).includes(job.name));
      await page.waitForFunction(()=>{const y=document.querySelector('#resultPanel').getBoundingClientRect().top;return y>=-10&&y<100},null,{timeout:5000});
      await page.locator('#backRecords').click();
    }
    console.log('PASS new records include accurate timing; clicking switches between distinct results; mobile detail and back navigation work');
    await page.locator(`.job[data-job-id="${results[0].id}"]`).click();
    await page.waitForFunction(text=>document.querySelector('#result').value===text,results[0].text);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:'test-results/mobile-records.png',fullPage:true});
    await page.setViewportSize({width:1280,height:900});
    await page.screenshot({path:'test-results/desktop-records.png',fullPage:true});
    const downloadEvent=page.waitForEvent('download');await page.locator('#download').click();
    const download=await downloadEvent;await download.saveAs('test-results/records-transcript.txt');
    assert.equal(fs.readFileSync('test-results/records-transcript.txt','utf8'),results[0].text);
    await page.reload({waitUntil:'networkidle'});
    await page.locator('#appView').waitFor({state:'visible'});
    for(const job of results)assert.equal(await page.locator(`.job[data-job-id="${job.id}"]`).count(),1);
    const after=await (await page.request.get('https://80.238.236.1/api/jobs')).json();
    for(const old of before)assert(after.some(j=>j.id===old.id));
    assert.deepEqual(errors,[]);
    console.log('PASS records survive reload, existing records preserved, TXT download works, no browser errors');
  } finally {
    for(const id of created)await page.request.delete('https://80.238.236.1/api/jobs/'+id).catch(()=>{});
    await browser.close();
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
