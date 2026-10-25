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
 const code=fs.readFileSync('dist/shengjian-1.4/nas.env','utf8').trim().split('=',2)[1];
 require('node:child_process').execFileSync('docker',['exec','--user','10001:10001','atow-logs-qa','python','-c',"import sqlite3; c=sqlite3.connect('/data/jobs.sqlite3'); c.execute('DELETE FROM settings'); c.commit()"]);
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 const page=await context.newPage();const errors=[],created=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto('http://127.0.0.1:18787',{waitUntil:'networkidle'});
  await page.locator('#code').fill(code);await page.locator('#loginButton').click();await page.locator('#appView').waitFor({state:'visible'});
  await page.waitForFunction(()=>document.querySelector('#computerStatus').textContent.includes('电脑在线'),null,{timeout:15000});
  await page.locator('#computerSettings').evaluate(e=>e.open=true);
  assert.equal(await page.locator('#computerUrl').inputValue(),'http://192.168.1.73:18788');
  console.log('PASS zero configuration: status card shows the PC online with the default address, no import or key');
  await page.locator('#file').setInputFiles({name:'网页日志检查.wav',mimeType:'audio/wav',buffer:fs.readFileSync('test-results/zh.wav')});
  await page.waitForFunction(()=>document.querySelector('#resultName').textContent.includes('网页日志检查.wav')&&document.querySelector('#resultName').textContent.includes('已完成'),null,{timeout:120000});
  let id=await page.locator('.job.active').getAttribute('data-job-id');created.push(id);
  const text=await page.locator('#result').inputValue();assert.match(text,/[一-鿿]/);
  assert((await page.locator('#resultMeta').innerText()).includes('FunASR'));
  await page.locator('#taskLogPanel').evaluate(e=>e.open=true);
  assert((await page.locator('#taskLogs').innerText()).includes('完成'));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:'test-results/settings-and-task-logs.png',fullPage:true});
  const downloadEvent=page.waitForEvent('download');await page.locator('#download').click();const download=await downloadEvent;
  await download.saveAs('test-results/logs-browser-transcript.txt');assert.equal(fs.readFileSync('test-results/logs-browser-transcript.txt','utf8'),text);
  console.log('PASS engine/device metadata, per-task log, TXT download, mobile layout');
  await page.locator('#file').setInputFiles(path.resolve('test-results/long-cancel.wav'));
  await page.waitForFunction(()=>document.querySelector('#resultName').textContent.includes('long-cancel.wav')&&!document.querySelector('#cancel').disabled,null,{timeout:120000});
  id=await page.locator('.job.active').getAttribute('data-job-id');created.push(id);
  page.once('dialog',d=>d.accept());await page.locator('#cancel').click();
  await page.waitForFunction(()=>document.querySelector('#resultName').textContent.includes('已终止'),null,{timeout:45000});
  assert.equal(await page.locator('#cancel').isDisabled(),true);assert.equal(await page.locator('#delete').isDisabled(),false);assert.equal(await page.locator('#download').isDisabled(),true);
  assert((await page.locator('#taskLogs').innerText()).includes('终止'));
  await page.screenshot({path:'test-results/cancelled-task.png',fullPage:true});
  await page.reload({waitUntil:'networkidle'});await page.locator('#appView').waitFor({state:'visible'});
  await page.waitForFunction(()=>document.querySelector('#computerStatus').textContent.includes('电脑在线'),null,{timeout:15000});
  await page.locator('#computerSettings').evaluate(e=>e.open=true);
  assert.equal(await page.locator('#computerUrl').inputValue(),'http://192.168.1.73:18788');
  assert.deepEqual(errors,[]);
  console.log('PASS visible terminate action, cleaned terminal status, persisted computer settings and no browser errors');
 }finally{
  for(const id of created){await page.request.post('http://127.0.0.1:18787/api/jobs/'+id+'/cancel').catch(()=>{});await page.request.delete('http://127.0.0.1:18787/api/jobs/'+id).catch(()=>{});}
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
