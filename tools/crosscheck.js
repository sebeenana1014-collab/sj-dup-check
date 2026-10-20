// 수집된 기사를 전부 서로 대조해 겹치는 쌍을 보여준다.
// 새 매체에 넘기기 전에 반드시 한 번 돌리고 상위 20쌍을 눈으로 확인할 것.
//   node tools/crosscheck.js [최소점수]
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'docs', 'index.html'), 'utf8');
const src = html.match(/<script>([\s\S]*)<\/script>/)[1];
const core = src.slice(src.indexOf('const UNIT'), src.indexOf('// ───── 데이터 ─────'));
const { fingerprint, score } = (new Function(core + '\nreturn {fingerprint, score};'))();

const data = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'docs', 'articles.json'), 'utf8'));
const d = data.articles;
const MIN = Number(process.argv[2]) || 40;
const fp = d.map(a => fingerprint(a.body));

console.log(`${data.site || ''} 기사 ${d.length}건 (${d[d.length - 1].date} ~ ${d[0].date})`);
const hits = [];
for (let i = 0; i < d.length; i++) for (let j = i + 1; j < d.length; j++) {
  const s = score(fp[i], fp[j]);
  if (s >= MIN) hits.push({ s, i, j });
}
hits.sort((a, b) => b.s - a.s);
console.log(`${MIN}점 이상 ${hits.length}쌍 / 전체 ${d.length * (d.length - 1) / 2}쌍\n`);
for (const h of hits.slice(0, 25)) {
  const A = d[h.i], B = d[h.j];
  console.log(`[${h.s}] ${A.date.slice(5, 16)} ${A.reporter} | ${A.title.slice(0, 52)}`);
  console.log(`      ${B.date.slice(5, 16)} ${B.reporter} | ${B.title.slice(0, 52)}\n`);
}
console.log('확인할 것: 같은 발표를 두 번 쓴 쌍이 상위에 있는가 / 정기 시리즈·연속 보도가 섞였는가');
