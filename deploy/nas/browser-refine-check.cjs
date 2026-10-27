// Run from the workspace against the Phase B QA container (stub LLM running inside it).
// Template: deploy/nas/browser-settings-check.cjs (login, setInputFiles upload, polling, console errors).
const {chromium} = require('C:/Users/nzy189/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');

(async()=>{
 const code=fs.readFileSync('dist/shengjian-1.4/nas.env','utf8').trim().split('=',2)[1];
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 await context.grantPermissions(['clipboard-write']);
 const page=await context.newPage();const errors=[],created=[];let passed=0;
 page.on('pageerror',e=>errors.push('pageerror: '+e.message));
 page.on('console',m=>{if(m.type()==='error')errors.push('console: '+m.text())});
 const ok=name=>{passed++;console.log('PASS '+name)};
 try{
  // 1. login, AI refine card visible with switch, address, model, key inputs and test button
  await page.goto('http://127.0.0.1:18787',{waitUntil:'networkidle'});
  await page.locator('#code').fill(code);await page.locator('#loginButton').click();await page.locator('#appView').waitFor({state:'visible'});
  await page.locator('#llmSettings').evaluate(e=>e.open=true);
  await page.locator('#llmEnabled').waitFor({state:'visible'});
  for(const sel of ['#llmUrl','#llmModel','#llmKey','#saveLlm','#testLlm'])assert.equal(await page.locator(sel).isVisible(),true,sel);
  ok('1 AI refine card visible with switch, address, model, key inputs and test-connection button');
  // 2. fill stub config via UI, save, then test connection updates the status text
  await page.locator('#llmUrl').fill('http://127.0.0.1:18789/v1');
  await page.locator('#llmModel').fill('stub-ok');
  await page.locator('#llmKey').fill('sk-qa123');
  await page.locator('#saveLlm').click();
  await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('已保存'),null,{timeout:10000});
  await page.locator('#testLlm').click();
  await page.waitForFunction(()=>{const s=document.querySelector('#llmStatus');return s.textContent.includes('连接成功')&&s.className.includes('ok')},null,{timeout:30000});
  ok('2 stub config saved via UI and connection test updates the status text');
  // 3. upload zh.wav, poll until transcription done and refine done
  await page.locator('#file').setInputFiles({name:'网页提炼检查.wav',mimeType:'audio/wav',buffer:fs.readFileSync('test-results/zh.wav')});
  await page.waitForFunction(()=>document.querySelector('#resultName').textContent.includes('已完成'),null,{timeout:120000});
  const id=await page.locator('.job.active').getAttribute('data-job-id');created.push(id);
  await page.waitForFunction(()=>!document.querySelector('#copySummary').disabled&&document.querySelector('#refinedText').value.length>0,null,{timeout:120000});
  ok('3 upload reaches done and auto refine reaches done');
  // 4. tabs appear, default on AI content, both fields filled, both marked AI 生成
  assert.equal(await page.locator('#refineTabs').isVisible(),true);
  assert.equal(await page.locator('#tabAi').evaluate(e=>e.classList.contains('active')),true);
  assert.equal(await page.locator('#aiPane').isVisible(),true);
  assert.equal(await page.locator('#result').isVisible(),false);
  assert.equal(await page.locator('#refinedText').inputValue(),'这是优化后的测试原文');
  assert.equal(await page.locator('#summaryText').inputValue(),'- 测试要点');
  const tags=await page.locator('#aiPane .ai-tag').all();
  assert.equal(tags.length,2,'ai-tag count');
  for(const tag of tags){assert.equal(await tag.isVisible(),true);assert.equal(await tag.textContent(),'AI 生成');}
  ok('4 detail tabs default to AI content; refined text and summary filled, both tagged AI 生成');
  // 5. raw tab shows the original transcript, switching back restores AI content
  await page.locator('#tabRaw').click();
  assert.equal(await page.locator('#result').isVisible(),true);
  assert.match(await page.locator('#result').inputValue(),/[一-鿿]/);
  assert.equal(await page.locator('#aiPane').isVisible(),false);
  await page.locator('#tabAi').click();
  assert.equal(await page.locator('#refinedText').isVisible(),true);
  assert.equal(await page.locator('#result').isVisible(),false);
  ok('5 raw tab shows original transcript and switching back keeps AI content');
  // 6. summary copy and download usable; retry refine hidden in done state
  assert.equal(await page.locator('#copySummary').isDisabled(),false);
  assert.equal(await page.locator('#downloadSummary').isDisabled(),false);
  assert.equal(await page.locator('#retryRefine').isHidden(),true);
  await page.locator('#copySummary').click();
  await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('已复制概要'),null,{timeout:10000});
  const downloadEvent=page.waitForEvent('download');await page.locator('#downloadSummary').click();const download=await downloadEvent;
  await download.saveAs('test-results/refine-browser-summary.txt');
  assert.equal(fs.readFileSync('test-results/refine-browser-summary.txt','utf8'),'- 测试要点');
  ok('6 summary copy and download work; retry refine hidden in done state');
  // 7. 390x844 viewport has no horizontal overflow
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=390),true,'scrollWidth '+await page.evaluate(()=>document.documentElement.scrollWidth));
  ok('7 390px viewport has no horizontal overflow');
  // 8. tabs and cards lay out normally on mobile
  assert.equal(await page.locator('#refineTabs').isVisible(),true);
  const tabWidth=await page.locator('#refineTabs').evaluate(e=>e.getBoundingClientRect().width);
  assert.ok(tabWidth>0&&tabWidth<=390,'tabs width '+tabWidth);
  assert.equal(await page.locator('#aiPane').isVisible(),true);
  await page.screenshot({path:'test-results/refine-browser.png',fullPage:true});
  ok('8 tabs and cards lay out normally on mobile');
  // 9. no browser console errors during the whole flow
  assert.deepEqual(errors,[]);
  ok('9 no browser console errors during the whole flow');
  console.log('Browser refine check ALL '+passed+' PASS');
 }finally{
  if(page)for(const id of created){await page.request.post('http://127.0.0.1:18787/api/jobs/'+id+'/cancel').catch(()=>{});await page.request.delete('http://127.0.0.1:18787/api/jobs/'+id).catch(()=>{});}
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
