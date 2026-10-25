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
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  let jobId;
  const context = await browser.newContext({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true, deviceScaleFactor: 1});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  try {
    const response = await page.goto('https://80.238.236.1', {waitUntil: 'networkidle'});
    assert.equal(response.status(), 200);
    assert.match(response.headers()['permissions-policy'], /microphone=\(\)/);
    await page.locator('#code').fill(code);
    await page.locator('#loginButton').click();
    await page.locator('#appView').waitFor({state: 'visible'});
    assert.equal(await page.locator('#record').count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.locator('#file').setInputFiles(path.resolve('test-results/zh.wav'));
    await page.waitForFunction(() => document.querySelector('#resultName').textContent.includes('已完成'), null, {timeout: 120000});
    const text = await page.locator('#result').inputValue();
    assert(text.length > 4);
    assert.match(text, /[\u4e00-\u9fff]/);
    jobId = await page.locator('#jobs .job.active').evaluate(async () => {
      const jobs = await (await fetch('/api/jobs')).json();
      return jobs.find(j => j.name === 'zh.wav').id;
    });
    await page.screenshot({path: 'test-results/mobile-transcript.png', fullPage: true});
    const downloading = page.waitForEvent('download');
    await page.locator('#download').click();
    const downloaded = await downloading;
    await downloaded.saveAs('test-results/downloaded-transcript.txt');
    assert.equal(fs.readFileSync('test-results/downloaded-transcript.txt', 'utf8'), text);
    console.log('PASS mobile HTTPS / login / file upload / Chinese result / TXT download / no recording controls / no horizontal overflow');
    await page.reload({waitUntil: 'networkidle'});
    await page.locator('#appView').waitFor({state: 'visible'});
    assert.equal(await page.locator('#result').inputValue(), text);
    console.log('PASS session and transcript survive page reload');
    assert.deepEqual(errors, []);
  } finally {
    if (jobId) await page.evaluate(async id => {await fetch('/api/jobs/' + id, {method: 'DELETE'});}, jobId).catch(() => {});
    await browser.close();
  }
})().catch(e => {console.error(e); process.exitCode = 1;});
