#!/usr/bin/env node
// index.html 검증 — 커밋 전에 돌린다.
//   node tools/check-index.js
//
// 세 가지를 본다:
//   1) 대시보드 <script> 문법 (배열 항목 뒤 쉼표 빠짐을 잡는다)
//   2) 링크된 슬라이드 파일이 실제로 있는지
//   3) 그 파일의 <title>에 해당 주차 번호가 들어 있는지
//      — 주차를 옮길 때 파일·라벨만 바꾸고 href를 안 고치면 여기서 걸린다.

const fs = require('fs');

const html = fs.readFileSync('index.html', 'utf8');
const code = html.match(/<script>([\s\S]*?)<\/script>/)[1];

try {
  new Function(code);
} catch (e) {
  console.error('스크립트 문법 오류:', e.message);
  process.exit(1);
}

const arrayOf = (name) => {
  const m = code.match(new RegExp('var ' + name + ' = \\[([\\s\\S]*?)\\n  \\];'));
  if (!m) throw new Error(`배열을 찾지 못함: ${name}`);
  return new Function('return [' + m[1] + ']')();
};

const items = [...arrayOf('past'), ...arrayOf('phase1')];
let problems = 0;

for (const item of items) {
  for (const link of item.links || []) {
    if (!/^w[\d-]/.test(link.href)) continue;

    if (!fs.existsSync(link.href)) {
      console.error(`없는 파일: ${item.wk} → ${link.href}`);
      problems++;
      continue;
    }

    const page = fs.readFileSync(link.href, 'utf8');
    const title = (page.match(/<title>([^<]+)<\/title>/) || [])[1] || '';
    if (!title.includes(item.wk)) {
      console.error(`주차 엇갈림: ${item.wk} → ${link.href} (실제 내용: ${title})`);
      problems++;
    }
  }
}

if (problems) {
  console.error(`\n문제 ${problems}건`);
  process.exit(1);
}
console.log(`OK — 주차 ${items.length}개, 링크 전부 일치`);
