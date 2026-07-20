import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";


export function MarkdownViewer({ content }: { content: string }) {
  return (
    <div className="max-h-[620px] overflow-auto rounded-xl border border-line bg-[rgb(var(--panel-soft))] p-4 text-sm leading-6 text-ink">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className="mb-4 text-xl font-semibold">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-3 mt-6 text-lg font-semibold">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-2 mt-5 font-semibold">{children}</h3>,
          p: ({ children }) => <p className="my-3 text-[rgb(var(--muted))]">{children}</p>,
          ul: ({ children }) => <ul className="my-3 list-disc space-y-1 pl-5 text-[rgb(var(--muted))]">{children}</ul>,
          ol: ({ children }) => <ol className="my-3 list-decimal space-y-1 pl-5 text-[rgb(var(--muted))]">{children}</ol>,
          table: ({ children }) => <div className="my-4 overflow-x-auto"><table className="w-full border-collapse text-left text-xs">{children}</table></div>,
          th: ({ children }) => <th className="border border-line bg-[rgb(var(--panel-raised))] px-3 py-2 font-semibold">{children}</th>,
          td: ({ children }) => <td className="border border-line px-3 py-2 text-[rgb(var(--muted))]">{children}</td>,
          code: ({ children }) => <code className="rounded bg-black/25 px-1.5 py-0.5 font-mono text-xs text-blue-200">{children}</code>,
          pre: ({ children }) => <pre className="my-4 overflow-auto rounded-lg bg-black/30 p-4 font-mono text-xs text-blue-100">{children}</pre>
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
