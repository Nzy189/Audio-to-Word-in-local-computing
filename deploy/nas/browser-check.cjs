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

(async()=>{
 const code=fs.readFileSync('dist/shengjian-z2pro/nas.env','utf8').split(/\r?\n/).find(line=>line.startsWith('ACCESS_CODE=')).slice(12);
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 const page=await context.newPage();const errors=[];let jobId;
 page.on('pageerror',e=>errors.push(e.message));
 try{
  const response=await page.goto('http://127.0.0.1:18787',{waitUntil:'networkidle'});
  assert.equal(response.status(),200);assert.equal(response.headers()['permissions-policy'],'microphone=(), camera=()');
  await page.locator('#code').fill(code);await page.locator('#loginButton').click();await page.locator('#appView').waitFor({state:'visible'});
  const cookies=await context.cookies();assert(cookies.some(c=>c.name==='atow_session'&&c.httpOnly&&!c.secure));
  await page.locator('#file').setInputFiles({name:'NAS-browser-check.wav',mimeType:'audio/wav',buffer:fs.readFileSync('test-results/zh.wav')});
  await page.waitForFunction(()=>document.querySelector('#resultName').textContent.includes('NAS-browser-check.wav')&&document.querySelector('#resultName').textContent.includes('已完成'),null,{timeout:120000});
  jobId=await page.locator('.job.active').getAttribute('data-job-id');
  const text=await page.locator('#result').inputValue();assert.match(text,/[\u4e00-\u9fff]/);
  const meta=await page.locator('#resultMeta').innerText();assert(meta.includes('转写耗时')&&meta.includes('转写时间（完成）')&&meta.includes('执行设备')&&meta.includes('5080'));
  const downloadEvent=page.waitForEvent('download');await page.locator('#download').click();const download=await downloadEvent;
  await download.saveAs('test-results/nas-browser-transcript.txt');assert.equal(fs.readFileSync('test-results/nas-browser-transcript.txt','utf8'),text);
  await page.reload({waitUntil:'networkidle'});await page.locator('#appView').waitFor({state:'visible'});
  await page.locator(`.job[data-job-id="${jobId}"]`).click();
  await page.waitForFunction(text=>document.querySelector('#result').value===text,text);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:'test-results/nas-mobile.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS mobile browser / HTTP login / ARM64 file upload / record details / TXT download / session after reload / no microphone');
 }finally{
  if(jobId)await page.request.delete('http://127.0.0.1:18787/api/jobs/'+jobId).catch(()=>{});
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
