/// <reference types="vite/client" />

declare module 'markdown-it' {
  const MarkdownIt: new (opts?: Record<string, unknown>) => {
    render(src: string): string
    utils: {
      escapeHtml(str: string): string
    }
  }
  export default MarkdownIt
}

declare module 'dompurify' {
  interface DOMPurify {
    sanitize(dirty: string): string
  }
  const DOMPurify: DOMPurify
  export default DOMPurify
}

interface ImportMetaEnv {
  readonly VITE_JAVA_API: string
  readonly VITE_PYTHON_API: string
  readonly VITE_INTERVIEW_MODE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
