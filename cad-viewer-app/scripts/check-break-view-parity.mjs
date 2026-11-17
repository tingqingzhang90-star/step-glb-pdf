// 前后端断裂几何对拍:读 tests/fixtures/break_view_cases.json,
// 逐项核对 breakView.js 与 src/drawing/break_view.py 的输出。
// 运行: node cad-viewer-app/scripts/check-break-view-parity.mjs
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  parseBreakSpec, breakShift, projectCoord, clampCoord, projectPoint,
  clipRanges, wavePoints, pointsToPath, effectiveContentBox, wavePaths
} from '../src/views/breakView.js'

const here = dirname(fileURLToPath(import.meta.url))
const cases = JSON.parse(readFileSync(
  join(here, '../../tests/fixtures/break_view_cases.json'), 'utf-8'))
const specs = cases.specs.map(parseBreakSpec)
specs.forEach((s, i) => assert.ok(s, `spec ${i} 解析失败`))

const close = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-3, `${msg}: ${a} != ${b}`)

assert.equal(breakShift(specs[0]), 54)
assert.equal(breakShift(specs[1]), 45)

for (const c of cases.project) {
  const spec = specs[c.spec]
  const got = projectCoord(c.value, spec)
  if (c.projected === null) assert.equal(got, null, `project(${c.value}) 应被裁剪`)
  else close(got, c.projected, `project(${c.value})`)
  close(clampCoord(c.value, spec), c.clamped, `clamp(${c.value})`)
}

for (const c of cases.points) {
  const got = projectPoint(...c.point, specs[c.spec])
  close(got.x, c.expected[0], `point x ${c.point}`)
  close(got.y, c.expected[1], `point y ${c.point}`)
}

for (const c of cases.clip) {
  const got = clipRanges(specs[c.spec], c.canvas)
  assert.equal(got.length, c.expected.length)
  got.forEach((row, i) => row.forEach((v, j) => close(v, c.expected[i][j], `clip[${i}][${j}]`)))
}
assert.deepEqual(clipRanges(null, 400), [[0, 400, 0]])

for (const c of cases.waves) {
  const [left, right] = wavePoints(specs[c.spec], c.crossLo, c.crossHi)
  c.sample.forEach((idx, n) => {
    close(left[idx][0], c.left[n][0], `wave left x[${idx}]`)
    close(left[idx][1], c.left[n][1], `wave left y[${idx}]`)
    close(right[idx][0], c.right[n][0], `wave right x[${idx}]`)
    close(right[idx][1], c.right[n][1], `wave right y[${idx}]`)
  })
}
assert.deepEqual(wavePoints(null, 0, 10), [[], []])
assert.equal(pointsToPath([[1, 2], [3, 4]]), 'M1.00,2.00 L3.00,4.00')

const box = effectiveContentBox({ x: 20, y: 10, width: 380, height: 60 }, specs[0])
assert.equal(box.width, 326)
assert.equal(box.height, 60)
const paths = wavePaths({ break: cases.specs[0], contentBBox: { x: 0, y: 10, width: 400, height: 20 } })
assert.equal(paths.length, 2)
assert.ok(paths.every(p => p.startsWith('M')))
assert.equal(parseBreakSpec({ axis: 'z', cutA: 1, cutB: 2, pxPerMm: 1 }), null)

console.log(`breakView parity OK: ${cases.project.length} projections, ${cases.points.length} points, ${cases.waves.length} wave sets`)
