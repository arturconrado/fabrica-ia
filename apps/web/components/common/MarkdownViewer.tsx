export function MarkdownViewer({ content }: { content: string }) {
  return <pre className="mono max-h-[520px] overflow-auto whitespace-pre-wrap rounded-md bg-slate-950 p-4 text-xs leading-5 text-slate-100">{content}</pre>;
}
