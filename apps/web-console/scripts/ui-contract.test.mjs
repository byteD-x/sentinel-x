import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import process from 'node:process'
import console from 'node:console'

const root = resolve(import.meta.dirname, '..')
const files = [
  'src/components/AppLayout.tsx',
  'src/pages/DashboardPage.tsx',
]

const requiredText = [
  '故障指挥台',
  '故障总览',
  '当前处置阶段',
  '优先处理',
  '全部故障',
  '请确认控制面在线后重试',
]

const mojibakePattern = /[鏁殰昏鎬櫙绋€]/u
const failures = []
const combined = files.map(file => readFileSync(resolve(root, file), 'utf8')).join('\n')

for (const file of files) {
  const content = readFileSync(resolve(root, file), 'utf8')

  if (mojibakePattern.test(content)) {
    failures.push(`${file} contains mojibake text`)
  }
}

for (const label of requiredText) {
  if (!combined.includes(label)) {
    failures.push(`UI contract is missing "${label}"`)
  }
}

if (failures.length) {
  console.error(failures.join('\n'))
  process.exit(1)
}

console.log('UI contract labels are readable.')
