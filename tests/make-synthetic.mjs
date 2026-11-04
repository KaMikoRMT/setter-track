// 產生測試用的合成影片（已知答案）：0.7x 廣角、近端底線後方角落、有人走動、三顆舉球。
// 用法：node tests/make-synthetic.mjs <輸出資料夾> [--short]
// 輸出：synthetic.mp4（H.264）與 truth.json（相機、校正點的像素位置、每一格球的位置、每段飛行）。
// 幾何全部用 app/index.html 的核心函式，不另外實作。
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const outDir = process.argv[2];
if (!outDir) { console.error('用法：node tests/make-synthetic.mjs <輸出資料夾> [--short]'); process.exit(2); }
const SHORT = process.argv.includes('--short');
fs.mkdirSync(outDir, { recursive: true });

const html = fs.readFileSync(path.join(here, '..', 'app', 'index.html'), 'utf8');
const begin = html.search(/\/\*\s*@core-begin\s*\*\//), end = /\/\*\s*@core-end\s*\*\//.exec(html).index;
const C = {};
vm.createContext(C);
vm.runInContext(html.slice(begin, end) + '\n;globalThis.core = { CONFIG, landmarkDefs, lineDefs, lookAtCamera, projectPoint, camCoords, rayFromPixel, ballAt, AX };', C);
const K = C.core;

const W = 1280, H = 720, FPS = 60;
const cam = K.lookAtCamera([-6.5, -12.5, 2.2], [0.5, -1, 1.6], 0.55 * W, W, H);
cam.k1 = -0.12; cam.k2 = 0.02;
const netH = K.CONFIG.NET_HEIGHT_DEFAULT;

// ---------- 球的飛行（世界座標） ----------
const G = K.CONFIG.G;
const flight = (kind, team, t0, t1, p0, p1, extra) => {
    const d = t1 - t0;
    const v0 = [(p1[0] - p0[0]) / d, (p1[1] - p0[1]) / d, (p1[2] - p0[2]) / d + 0.5 * G * d];
    return Object.assign({ kind, team, t0, t1, p0, v0, fit: { t0, p0, v0 } }, extra || {});
};
const flights = [
    flight('pass', 'near', 0.20, 1.20, [-1.0, -7.5, 0.9], [0.8, -0.6, 2.4]),
    flight('set', 'near', 1.20, 2.35, [0.8, -0.6, 2.4], [-3.7, -0.9, 3.0], { target: '大砲' }),
    flight('attack', 'near', 2.35, 2.73, [-3.7, -0.9, 3.0], [1.0, 5.5, 0.11]),
    flight('free', 'far', 3.60, 4.80, [0.5, 4.0, 2.6], [0.0, -5.0, 1.0]),
    flight('pass', 'near', 4.80, 5.70, [0.0, -5.0, 1.0], [0.6, -0.5, 2.45]),
    flight('set', 'near', 5.70, 6.60, [0.6, -0.5, 2.45], [3.9, -0.7, 2.95], { target: '背' }),
    flight('attack', 'near', 6.60, 6.95, [3.9, -0.7, 2.95], [-2.0, 6.0, 0.11]),
    flight('pass', 'far', 7.40, 8.40, [0.5, 7.0, 0.9], [-0.7, 0.6, 2.4]),
    flight('set', 'far', 8.40, 9.50, [-0.7, 0.6, 2.4], [3.7, 0.9, 3.0], { target: '大砲' }),
    flight('attack', 'far', 9.50, 9.85, [3.7, 0.9, 3.0], [-1.0, -5.5, 0.11]),
];
const DURATION = SHORT ? 3.0 : 10.2;
const NF = Math.round(DURATION * FPS);
const ballWorld = t => {
    for (const f of flights) if (t >= f.t0 && t < f.t1) return K.ballAt(f.fit, t);
    return null;
};

// ---------- 背景（相機固定，只算一次） ----------
let seed = 99;
const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
const bg = new Uint8ClampedArray(W * H * 3);
for (let v = 0; v < H; v++) for (let u = 0; u < W; u++) {
    const ray = K.rayFromPixel(cam, u + 0.5, v + 0.5);
    let col;
    if (ray.d[2] < -1e-4) {
        const s = -ray.o[2] / ray.d[2], x = ray.o[0] + ray.d[0] * s, y = ray.o[1] + ray.d[1] * s;
        if (Math.abs(x) > 16 || Math.abs(y) > 22) col = [88, 88, 96];
        else if (Math.abs(x) <= 4.5 && Math.abs(y) <= 9) { const w = 8 * Math.sin(y * 9 + Math.sin(x * 3)); col = [214 + w, 150 + w, 84 + w * 0.5]; }
        else { const w = 6 * Math.sin(y * 9); col = [196 + w, 162 + w, 110 + w]; }
    } else {
        const az = Math.atan2(ray.d[1], ray.d[0]), el = ray.d[2];
        const pillar = Math.abs(Math.sin(az * 9)) > 0.93;
        const g = el > 0.35 ? 70 : 120 - el * 60;
        col = pillar ? [175, 178, 182] : [g, g + 2, g + 8];
    }
    const i = (v * W + u) * 3;
    bg[i] = col[0]; bg[i + 1] = col[1]; bg[i + 2] = col[2];
}
// 抗鋸齒圓點
function disc(buf, cu, cv, r, rgb, alpha) {
    const a0 = alpha == null ? 1 : alpha;
    const x0 = Math.max(0, Math.floor(cu - r - 1)), x1 = Math.min(W - 1, Math.ceil(cu + r + 1));
    const y0 = Math.max(0, Math.floor(cv - r - 1)), y1 = Math.min(H - 1, Math.ceil(cv + r + 1));
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
        const d = Math.hypot(x + 0.5 - cu, y + 0.5 - cv);
        const cov = Math.max(0, Math.min(1, r + 0.5 - d)) * a0;
        if (cov <= 0) continue;
        const i = (y * W + x) * 3;
        buf[i] += (rgb[0] - buf[i]) * cov; buf[i + 1] += (rgb[1] - buf[i + 1]) * cov; buf[i + 2] += (rgb[2] - buf[i + 2]) * cov;
    }
}
function worldLine(buf, a, b, widthM, rgb, alpha, stepM) {
    const L = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]), n = Math.max(2, Math.ceil(L / (stepM || 0.02)));
    for (let i = 0; i <= n; i++) {
        const X = [a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n, a[2] + (b[2] - a[2]) * i / n];
        const q = K.projectPoint(cam, X);
        if (!q || q[0] < -10 || q[0] > W + 10 || q[1] < -10 || q[1] > H + 10) continue;
        const z = K.camCoords(cam, X)[2];
        disc(buf, q[0], q[1], Math.max(0.6, cam.f * widthM / 2 / z), rgb, alpha);
    }
}
const Wc = 4.5, Lc = 9, A = 3, nb = netH - 1, aH = netH + 0.8;
for (const [a, b] of [[[-Wc, -Lc, 0], [Wc, -Lc, 0]], [[Wc, -Lc, 0], [Wc, Lc, 0]], [[Wc, Lc, 0], [-Wc, Lc, 0]], [[-Wc, Lc, 0], [-Wc, -Lc, 0]],
    [[-Wc, 0, 0], [Wc, 0, 0]], [[-Wc, -A, 0], [Wc, -A, 0]], [[-Wc, A, 0], [Wc, A, 0]]]) worldLine(bg, a, b, 0.05, [40, 90, 200], 1);
for (let x = -Wc; x <= Wc + 1e-9; x += 0.1) worldLine(bg, [x, 0, nb], [x, 0, netH], 0.006, [30, 30, 30], 0.6, 0.03);
for (let z = nb; z <= netH + 1e-9; z += 0.1) worldLine(bg, [-Wc, 0, z], [Wc, 0, z], 0.006, [30, 30, 30], 0.6, 0.03);
worldLine(bg, [-Wc, 0, netH - 0.035], [Wc, 0, netH - 0.035], 0.07, [245, 245, 245], 1);
worldLine(bg, [-Wc, 0, nb], [Wc, 0, nb], 0.05, [235, 235, 235], 1);
for (const x of [-Wc - 0.5, Wc + 0.5]) worldLine(bg, [x, 0, 0], [x, 0, netH + 0.1], 0.1, [200, 205, 210], 1);
for (const x of [-Wc, Wc]) for (let k = 0; k < 18; k++) worldLine(bg, [x, 0, nb + k * 0.1], [x, 0, nb + (k + 1) * 0.1], 0.02, k % 2 ? [250, 250, 250] : [220, 40, 40], 1);

// ---------- 人（在背景上走動，不擋球） ----------
const players = [];
for (let i = 0; i < 6; i++) players.push({ x: -3.5 + i * 1.4, y: -1.5 - (i % 3) * 2.5, ph: rnd() * 6, col: [30, 36, 64] });
for (let i = 0; i < 6; i++) players.push({ x: -3.5 + i * 1.4, y: 1.5 + (i % 3) * 2.5, ph: rnd() * 6, col: [225, 225, 228] });
function drawPlayer(buf, p, t) {
    const x = p.x + 0.6 * Math.sin(t * 0.9 + p.ph), y = p.y + 0.4 * Math.cos(t * 0.7 + p.ph);
    for (let k = 0; k <= 24; k++) {
        const z = 0.1 + k * 0.07, X = [x, y, z], q = K.projectPoint(cam, X);
        if (!q) continue;
        const zc = K.camCoords(cam, X)[2];
        disc(buf, q[0], q[1], cam.f * (k > 21 ? 0.11 : 0.18) / zc, k > 21 ? [120, 80, 60] : p.col, 1);
    }
}

// ---------- 逐格輸出 ----------
const noise = new Int8Array(W * H * 3 + 7919);
for (let i = 0; i < noise.length; i++) noise[i] = Math.round((rnd() - 0.5) * 6);
const mp4 = path.join(outDir, 'synthetic.mp4');
const ff = spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', `${W}x${H}`, '-r', String(FPS), '-i', '-',
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-preset', 'veryfast', mp4], { stdio: ['pipe', 'inherit', 'inherit'] });
const ballPx = [];
const frame = new Uint8ClampedArray(W * H * 3);
for (let f = 0; f < NF; f++) {
    const t = f / FPS;
    frame.set(bg);
    for (const p of players) drawPlayer(frame, p, t);
    const X = ballWorld(t);
    if (X) {
        const q = K.projectPoint(cam, X);
        if (q && q[0] > -20 && q[0] < W + 20 && q[1] > -20 && q[1] < H + 20) {
            const r = Math.max(1.2, cam.f * K.CONFIG.BALL_R / K.camCoords(cam, X)[2]);
            disc(frame, q[0], q[1], r, [236, 204, 52], 1);
            disc(frame, q[0] - r * 0.25, q[1] + r * 0.2, r * 0.45, [40, 80, 190], 0.55);
            ballPx.push({ frame: f, t, u: q[0], v: q[1], r });
        }
    }
    const off = (f * 7919) % 7919;
    for (let i = 0; i < frame.length; i++) frame[i] += noise[i + off];
    const ok = ff.stdin.write(Buffer.from(frame.buffer, frame.byteOffset, frame.byteLength));
    if (!ok) await new Promise(r => ff.stdin.once('drain', r));
}
ff.stdin.end();
await new Promise((res, rej) => ff.on('close', c => (c === 0 ? res() : rej(new Error('ffmpeg 失敗 ' + c)))));

const inImage = q => q && q[0] >= 0 && q[0] < W && q[1] >= 0 && q[1] < H;
const landmarks = K.landmarkDefs(netH).map(d => { const q = K.projectPoint(cam, d.X); return { id: d.id, u: q ? q[0] : null, v: q ? q[1] : null, visible: inImage(q) }; });
const lineSamples = {};
for (const d of K.lineDefs(netH)) {
    const arr = [];
    for (let i = 1; i < 10; i++) {
        const X = [0, 0, 0];
        for (const [k, v] of Object.entries(d.fixed)) X[K.AX[k]] = v;
        X[K.AX[d.free]] = d.range[0] + (d.range[1] - d.range[0]) * i / 10;
        const q = K.projectPoint(cam, X);
        if (inImage(q)) arr.push({ u: q[0], v: q[1] });
    }
    lineSamples[d.id] = arr;
}
fs.writeFileSync(path.join(outDir, 'truth.json'), JSON.stringify({
    video: { name: 'synthetic.mp4', w: W, h: H, fps: FPS, frames: NF },
    cam, netH, landmarks, lineSamples,
    flights: flights.filter(f => f.t0 < DURATION).map(({ fit, ...f }) => f),
    ballPx,
}, null, 1));
console.log(`已輸出 ${mp4}（${NF} 格）與 truth.json；看得到的校正點 ${landmarks.filter(l => l.visible).length} 個，球出現在 ${ballPx.length} 格`);
