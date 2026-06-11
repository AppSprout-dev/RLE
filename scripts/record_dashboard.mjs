// Record the RLE dashboard replaying a run, via Playwright video capture.
// Usage: node record_dashboard.mjs <url> <seconds> <outDir> [width] [height]
import { chromium } from 'playwright';

const [url = 'http://localhost:3001', secs = '28', outDir = 'D:/RLE_media/capture/video',
  w = '1920', h = '1080'] = process.argv.slice(2);

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: Number(w), height: Number(h) },
  recordVideo: { dir: outDir, size: { width: Number(w), height: Number(h) } },
});
const page = await ctx.newPage();
// Seed an RLE-focused widget layout so the 5 RLE widgets render on load.
const rlePreset = [{
  name: 'RLE',
  layout: [
    { i: 'rleAgentStatus', x: 0, y: 0, w: 4, h: 2, isBounded: true },
    { i: 'rleScoreTimeline', x: 4, y: 0, w: 8, h: 2, isBounded: true },
    { i: 'rleAgentLog', x: 0, y: 2, w: 6, h: 3, isBounded: true },
    { i: 'rleHelixPhase', x: 6, y: 2, w: 3, h: 3, isBounded: true },
    { i: 'rleConflictResolution', x: 9, y: 2, w: 3, h: 3, isBounded: true },
  ],
  cardSettings: {},
}];
await page.addInitScript((preset) => {
  localStorage.setItem('dashboard_presets', JSON.stringify(preset));
  localStorage.setItem('last_selected_preset', 'RLE');
}, rlePreset);
await page.goto(url, { waitUntil: 'networkidle' });
// Connect screen: fill the server URL, then connect.
const urlInput = page.locator('input').first();
if (await urlInput.isVisible().catch(() => false)) {
  await urlInput.fill('http://localhost:8765/api/v1');
  await page.getByRole('button', { name: /^connect$/i }).first().click();
  await page.waitForTimeout(5000);
}
await page.waitForTimeout(Number(secs) * 1000);
const path = await page.video().path();
await ctx.close();
await browser.close();
console.log('saved:', path);
