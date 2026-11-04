// 無頭瀏覽器實測：開合成影片 → 點校正點 → 標記一顆舉球 → 檢視 → 截圖。
// 用法：node tests/ui-check.mjs <合成影片資料夾（make-synthetic.mjs 的輸出）> [截圖資料夾]
// 需要 Playwright（require('playwright')）。
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const here = path.dirname(fileURLToPath(import.meta.url));
const synDir = process.argv[2];
const shotDir = process.argv[3] || synDir;
if (!synDir) { console.error('用法：node tests/ui-check.mjs <合成影片資料夾> [截圖資料夾]'); process.exit(2); }
const truth = JSON.parse(fs.readFileSync(path.join(synDir, 'truth.json'), 'utf8'));
const mp4 = path.join(synDir, 'synthetic.mp4');
const appUrl = 'file://' + path.join(here, '..', 'app', 'index.html');
const detPath = path.join(synDir, 'detections.json');

let failed = 0;
const check = (cond, msg) => { console.log(`${cond ? '  ✓' : '  ✗'} ${msg}`); if (!cond) failed++; };
const errors = [];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
page.on('pageerror', e => errors.push(String(e)));
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
await page.goto(appUrl);
await page.setInputFiles('#fileVideo', mp4);
await page.waitForFunction(() => window.__setterTrack.S.ready, null, { timeout: 15000 });

const toPage = async (u, v) => {
    const r = await page.locator('#overlay').boundingBox();
    return { x: r.x + u / truth.video.w * r.width, y: r.y + v / truth.video.h * r.height };
};
// 模擬人手點擊：加上約 0.8 px 的誤差（固定亂數種子，結果可重現）
let seed = 7;
const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
const gauss = () => Math.sqrt(-2 * Math.log(Math.max(rnd(), 1e-12))) * Math.cos(2 * Math.PI * rnd());
const clickVideo = async (u, v) => { const p = await toPage(u + 0.8 * gauss(), v + 0.8 * gauss()); await page.mouse.click(p.x, p.y); };
const waitSeek = () => page.waitForFunction(() => { const v = document.getElementById('video'); return !v.seeking && v.readyState >= 2; });

// ---------- ① 場地校正 ----------
await page.check('#chkWide');
for (const lm of truth.landmarks.filter(l => l.visible)) {
    await page.click(`[data-sel="point:${lm.id}"]`);
    await clickVideo(lm.u, lm.v);
}
for (const id of ['sideL', 'sideR', 'nearBack', 'farBack', 'mid', 'netTop']) {
    const pts = truth.lineSamples[id] || [];
    if (!pts.length) continue;
    await page.click(`[data-sel="line:${id}"]`);
    for (const q of pts.filter((_, i) => i % 2 === 0)) await clickVideo(q.u, q.v);
}
await page.waitForFunction(() => window.__setterTrack.S.project.calib.cam);
await page.waitForTimeout(200);
const cal = await page.evaluate(() => { const c = window.__setterTrack.S.project.calib; return { rms: c.rms, f: c.cam.f, R: c.cam.R, t: c.cam.t }; });
const center = c => { const R = c.R, t = c.t; return [-(R[0] * t[0] + R[3] * t[1] + R[6] * t[2]), -(R[1] * t[0] + R[4] * t[1] + R[7] * t[2]), -(R[2] * t[0] + R[5] * t[1] + R[8] * t[2])]; };
const cc = center(cal), ct = center(truth.cam);
const cErr = Math.hypot(cc[0] - ct[0], cc[1] - ct[1], cc[2] - ct[2]);
check(cal.rms < 1.5, `校正誤差 ${cal.rms.toFixed(2)} px（點擊加了 0.8 px 雜訊）`);
check(cErr < 0.3, `相機位置誤差 ${cErr.toFixed(3)} m`);
await page.screenshot({ path: path.join(shotDir, 'shot-1280-calib.png') });

// ---------- ② 標記舉球（第一顆：往 4 號位） ----------
await page.click('[data-tab=mark]');
await page.click('[data-act=newSet]');
const set = truth.flights.find(f => f.kind === 'set');
const fps = truth.video.fps;
await page.evaluate(t => window.__setterTrack.seek(t), (Math.ceil(set.t0 * fps) + 1 + 0.5) / fps);
await waitSeek();
let clicks = 0;
for (let guard = 0; guard < 40; guard++) {
    const t = await page.evaluate(() => document.getElementById('video').currentTime);
    const n = Math.round(t * fps - 0.5);
    if (n / fps >= set.t1 - 0.5 / fps) break;
    const b = truth.ballPx.find(x => x.frame === n);
    if (!b) break;
    await clickVideo(b.u, b.v);
    clicks++;
    await page.waitForFunction(prev => document.getElementById('video').currentTime > prev + 1e-4, t);
    await waitSeek();
}
await page.screenshot({ path: path.join(shotDir, 'shot-1280-mark.png') });
await page.keyboard.press('Enter');
const d = await page.evaluate(() => { const x = window.__setterTrack.derived()[0]; return x && x.metrics ? { target: x.metrics.target, apex: x.metrics.apexZ, flight: x.metrics.flight, team: x.metrics.team, rms: x.fit.rms, n: x.set.marks.length } : null; });
const G = 9.81, vz = set.v0[2], apexTrue = set.p0[2] + vz * vz / (2 * G);
check(d && d.n === clicks && clicks >= 15, `標了 ${clicks} 點`);
check(d && d.target === '大砲' && d.team === 'us', `目標區 ${d && d.target}、${d && d.team}`);
check(d && Math.abs(d.apex - apexTrue) < 0.15, `最高點 ${d && d.apex.toFixed(2)} m（答案 ${apexTrue.toFixed(2)}）`);
check(d && d.rms < 2, `擬合誤差 ${d && d.rms.toFixed(2)} px`);

// ---------- 匯入自動偵測（有 detections.json 才測） ----------
if (fs.existsSync(detPath)) {
    await page.click('#btnProject');
    const [chooser] = await Promise.all([page.waitForEvent('filechooser'), page.click('[data-act=importDet]')]);
    await chooser.setFiles(detPath);
    await page.waitForFunction(() => window.__setterTrack.S.project.candidates.length > 0);
    const likes = await page.locator('text=全部加入像舉球的').count();
    check(likes === 1, '偵測結果匯入後有「全部加入像舉球的」');
    if (likes) {
        await page.click('text=全部加入像舉球的');
        // 第一顆已經手動標過，跟它重疊的候選不會再列出；所以「手動＋自動」要剛好是三顆舉球
        const ds = await page.evaluate(() => window.__setterTrack.derived().map(x => ({ src: x.set.src, target: x.metrics.target, team: x.metrics.team, t: x.tVideo })));
        console.log('     全部舉球：', JSON.stringify(ds));
        const sets = truth.flights.filter(f => f.kind === 'set');
        const match = (x, s) => Math.abs(x.t - s.t0) < 0.25 && x.target === s.target && x.team === (s.team === 'near' ? 'us' : 'them');
        const found = sets.filter(s => ds.some(x => match(x, s)));
        const wrong = ds.filter(x => !sets.some(s => match(x, s)));
        check(found.length === sets.length, `三顆舉球都找到，目標區與隊伍都對（${found.length}/${sets.length}）`);
        check(ds.filter(x => x.src === 'auto').length === 2, `自動加入 2 顆（第 1 顆已手動標過，不重複）`);
        check(wrong.length === 0, `沒有誤判（${wrong.length}）`);
    }
}

// ---------- 匯出訓練標註（detector/tests/test_dataset.py 會用） ----------
await page.click('#btnProject');
const [dl] = await Promise.all([page.waitForEvent('download'), page.click('[data-act=exportLabels]')]);
await dl.saveAs(path.join(synDir, 'labels.json'));
const L = JSON.parse(fs.readFileSync(path.join(synDir, 'labels.json'), 'utf8'));
const nMarks = await page.evaluate(() => window.__setterTrack.derived().reduce((n, d) => n + (d.fit ? d.fit.inliers.filter(Boolean).length : 0), 0));
check(L.app === 'setter-track-labels' && L.labels.length === nMarks && L.labels.every(l => l.r > 1), `匯出訓練標註 ${L.labels.length} 個球的位置`);

// ---------- ③ 檢視 ----------
await page.click('[data-tab=view]');
await page.click('[data-pick]');
await page.click('[data-grade=good]');
await page.fill('#noteBox', '<b>測試</b>註解');
await page.locator('#noteBox').blur();
const g = await page.evaluate(() => { const s = window.__setterTrack.S; const x = s.project.sets.find(y => y.id === s.selId); return { grade: x.grade, note: x.note }; });
check(g.grade === 'good' && g.note === '<b>測試</b>註解', '評等與註解存得住');
check((await page.locator('#tabBody b:has-text("測試")').count()) === 0, '註解有跳脫，不會變成 HTML');
await page.screenshot({ path: path.join(shotDir, 'shot-1280-view.png') });
await page.click('[data-v="mode:front"]');
await page.screenshot({ path: path.join(shotDir, 'shot-1280-front.png') });
await page.click('[data-v="mode:side"]');
await page.screenshot({ path: path.join(shotDir, 'shot-1280-side.png') });
await page.click('[data-v="mode:video"]');
await page.screenshot({ path: path.join(shotDir, 'shot-1280-videoview.png') });

// ---------- 重新整理後資料還在 ----------
await page.reload();
await page.setInputFiles('#fileVideo', mp4);
await page.waitForFunction(() => window.__setterTrack.S.ready);
const after = await page.evaluate(() => ({ n: window.__setterTrack.S.project.sets.length, cam: !!window.__setterTrack.S.project.calib.cam }));
check(after.n >= 1 && after.cam, `重新開啟同一支影片，資料還在（${after.n} 顆）`);

// ---------- 手機尺寸 ----------
for (const [w, h] of [[390, 844], [360, 560]]) {
    await page.setViewportSize({ width: w, height: h });
    for (const tab of ['calib', 'mark', 'view']) {
        await page.click(`[data-tab=${tab}]`);
        await page.waitForTimeout(150);
        const sw = await page.evaluate(() => document.documentElement.scrollWidth);
        check(sw <= w, `${w}×${h} ${tab}：沒有橫向捲動（${sw}）`);
        await page.screenshot({ path: path.join(shotDir, `shot-${w}-${tab}.png`), fullPage: tab !== 'calib' });
    }
}

check(errors.length === 0, `主控台沒有錯誤${errors.length ? '：' + errors.join(' | ') : ''}`);
await browser.close();
console.log(failed ? `\n${failed} 項失敗` : '\n全部通過');
process.exit(failed ? 1 : 0);
