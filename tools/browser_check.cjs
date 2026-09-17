// Browser integration checks for this local application only.
// Set PLAYWRIGHT_MODULE if Playwright is installed outside the bundled runtime.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const base = process.env.SKILLMATCH_URL || 'http://127.0.0.1:8000';
const output = path.resolve('tmp/browser'); fs.mkdirSync(output, {recursive: true});
const credentials = fs.readFileSync('demo-credentials.txt', 'utf8');
const password = credentials.match(/Shared demo password: (.+)/)[1].trim();
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => { if (response.status() >= 500) errors.push(`${response.status()} ${response.url()}`); });
  const results = [];
  async function screenshot(name) { await page.screenshot({path: path.join(output, name + '.png'), fullPage: true}); }
  async function noOverflow() { assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Horizontal page overflow: ' + page.url()); }
  async function login(username) {
    await page.goto(base + '/accounts/login/');
    await page.getByLabel('Username').fill(username);
    await page.locator('#id_password').fill(password);
    await page.getByRole('button', {name: 'Sign in', exact:false}).click();
    await page.waitForURL(username === 'demo_seeker' ? '**/recommendations/' : '**/employer/jobs/');
  }
  await page.goto(base); await page.getByRole('heading', {level:1}).waitFor();
  await screenshot('landing-desktop'); await noOverflow(); results.push('Desktop landing renders');
  await login('demo_seeker');
  assert.equal(await page.locator('.result-card').count(), 10);
  await screenshot('recommendations-desktop'); await noOverflow();
  await page.getByText('Why this match?', {exact:true}).first().click();
  assert(await page.getByText('Certification multiplier', {exact:true}).first().isVisible());
  results.push('Seeker login, ten recommendations and expandable score breakdown');
  await page.getByRole('link', {name:'My profile', exact:true}).click();
  await page.locator('#skill-entry').fill('python'); await page.getByRole('button', {name:'+ Add skill', exact:true}).click();
  assert(await page.getByText('This skill is already added.', {exact:true}).isVisible());
  await page.locator('#skill-entry').fill('Browser test skill'); await page.getByRole('button', {name:'+ Add skill', exact:true}).click();
  await page.getByRole('button', {name:'Remove Browser test skill', exact:true}).click();
  await screenshot('profile-desktop');
  await page.getByRole('button', {name:'Save profile', exact:false}).click();
  await page.waitForURL('**/profiles/*/');
  assert(await page.getByText('Your profile has been saved.', {exact:true}).isVisible());
  results.push('Skill duplicate feedback, add/remove tags and persisted profile save');
  await page.getByRole('button', {name:'Sign out', exact:true}).click();
  await login('demo_employer');
  await screenshot('employer-desktop');
  await page.getByRole('link', {name:'Find candidates', exact:true}).click();
  await page.getByLabel('Job description or skill keywords').fill('Python Django SQL Git developer');
  await page.getByRole('button', {name:'Find candidates', exact:false}).click();
  assert.equal(await page.locator('.result-card').count(), 10);
  await screenshot('candidates-desktop'); await noOverflow();
  await page.getByRole('link', {name:'Next →', exact:true}).click();
  assert(await page.getByText('Page 2 of 3', {exact:true}).isVisible());
  assert(page.url().includes('q=Python'));
  results.push('Employer search, ranked candidates, query-preserving pagination');
  await page.getByRole('link', {name:'View profile ↗', exact:true}).first().click();
  await page.getByRole('heading', {name:'Professional summary', exact:true}).waitFor();
  results.push('Employer can inspect candidate profile');
  await page.setViewportSize({width:390,height:844});
  await page.goto(base + '/employer/jobs/'); await noOverflow(); await screenshot('employer-mobile');
  await page.goto(base + '/employer/candidates/?q=Python+Django'); await noOverflow(); await screenshot('candidates-mobile');
  await page.getByRole('button', {name:'Sign out ↪', exact:true}).click();
  await page.goto(base); await noOverflow(); await screenshot('landing-mobile');
  await page.goto(base + '/accounts/register/'); await noOverflow(); await screenshot('registration-mobile');
  await page.getByLabel('Role', {exact:false}).selectOption('employer');
  assert(await page.getByLabel('Company name (employers)', {exact:false}).isVisible());
  await page.getByLabel('Role', {exact:false}).selectOption('seeker');
  assert(!(await page.getByLabel('Company name (employers)', {exact:false}).isVisible()));
  results.push('390px mobile screens, mobile sign-out and conditional company field');
  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify({passed:results, errors}, null, 2));
  console.log(JSON.stringify({passed:results, errors, screenshots:output}, null, 2));
  await browser.close();
})().catch(error => {console.error(error); process.exit(1);});
