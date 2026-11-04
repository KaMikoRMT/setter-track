// 用法：node tests/selftest.mjs
// 把 app/index.html 裡 /* @core-begin */ 與 /* @core-end */ 中間的純邏輯抽出來，
// 在 Node 的 vm 裡執行 runSelfTests()；任何一項失敗就以非零代碼結束。
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const file = process.argv[2] || path.join(here, '..', 'app', 'index.html');
const html = fs.readFileSync(file, 'utf8');

const begin = html.search(/\/\*\s*@core-begin\s*\*\//);
const endMatch = /\/\*\s*@core-end\s*\*\//.exec(html);
if (begin < 0 || !endMatch) {
    console.error('找不到 /* @core-begin */ 與 /* @core-end */ 標記');
    process.exit(2);
}
const core = html.slice(begin, endMatch.index);

// 核心區塊不能碰 DOM 和 window：沙箱裡只給最基本的內建物件
const sandbox = {};
vm.createContext(sandbox);
const t0 = Date.now();
vm.runInContext(core + '\n;globalThis.__run = runSelfTests;', sandbox, { filename: 'core' });
const out = sandbox.__run();

for (const r of out.results) {
    console.log(`${r.ok ? '  ✓' : '  ✗'} ${r.name}${r.ok ? '' : `\n      ${r.error}`}`);
}
console.log(`\n${out.passed}/${out.total} 通過${out.failed ? `，${out.failed} 項失敗` : ''}（${Date.now() - t0} ms）`);
process.exit(out.failed ? 1 : 0);
