import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import python from 'highlight.js/lib/languages/python'
import java from 'highlight.js/lib/languages/java'
import go from 'highlight.js/lib/languages/go'
import rust from 'highlight.js/lib/languages/rust'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import sql from 'highlight.js/lib/languages/sql'
import c from 'highlight.js/lib/languages/c'
import cpp from 'highlight.js/lib/languages/cpp'
import csharp from 'highlight.js/lib/languages/csharp'
import php from 'highlight.js/lib/languages/php'
import ruby from 'highlight.js/lib/languages/ruby'
import yaml from 'highlight.js/lib/languages/yaml'
import markdown from 'highlight.js/lib/languages/markdown'

const SUPPORTED_LANGS: Array<[string, unknown]> = [
  ['javascript', javascript],
  ['typescript', typescript],
  ['python', python],
  ['java', java],
  ['go', go],
  ['rust', rust],
  ['bash', bash],
  ['shell', bash],
  ['json', json],
  ['xml', xml],
  ['html', xml],
  ['css', css],
  ['sql', sql],
  ['c', c],
  ['cpp', cpp],
  ['csharp', csharp],
  ['php', php],
  ['ruby', ruby],
  ['yaml', yaml],
  ['markdown', markdown],
]

for (const [name, lang] of SUPPORTED_LANGS) {
  hljs.registerLanguage(name, lang as any)
}

const md = new MarkdownIt({
  html: true,
  breaks: true,
  linkify: true,
  highlight: (str: string, lang: string) => {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(str, { language: lang, ignoreIllegals: true }).value}</code></pre>`
      } catch {
        /* 语法高亮失败时走普通转义 */
      }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(str)}</code></pre>`
  },
})

function rewriteCoverUrl(url: string): string {
  if (!url) return url
  // 提取 sourceName（兼容 /ai/media/cover?sourceName= 与网关 getResource 两种格式）
  const m = url.match(/sourceName=([^&"' )]+)/)
  if (m) return `/ai/media/cover?sourceName=${m[1]}`
  return url
}

export function renderMarkdown(content: string): string {
  // markdown 图片：改写为同源代理地址（经前端 nginx /ai/media 到后端）
  const withProxy = md.render(content).replace(/<img [^>]*src="([^"]+)"/g, (_all, url) => {
    const proxy = rewriteCoverUrl(url)
    return `<img src="${proxy}"`
  })
  return DOMPurify.sanitize(withProxy)
}
