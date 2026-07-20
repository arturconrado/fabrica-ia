"use client";

import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { BookOpen, Database, FilePlus2, Search, ShieldCheck } from "lucide-react";

import { apiGet, apiPost } from "@/lib/api";


type KnowledgeBase = {
  id: string;
  name: string;
  description: string;
  status: string;
  retrieval_version: string;
};

type KnowledgeDocument = {
  id: string;
  title: string;
  source_type: string;
  source_ref: string;
  status: string;
  checksum: string;
  content?: string;
};

type RetrievalResult = {
  chunk_id: string;
  document_id: string;
  document_title: string;
  source_ref: string;
  chunk_index: number;
  score: number;
  score_components: { vector: number; lexical: number; title: number; exact_bonus: number };
  content: string;
};

type QueryResponse = {
  query_id: string;
  knowledge_base_id: string;
  answer_mode: string;
  answer: string;
  results: RetrievalResult[];
};


function idempotencyKey(prefix: string) {
  const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}:${random}`;
}


export function KnowledgeWorkspace() {
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [selectedBaseId, setSelectedBaseId] = useState("");
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [baseName, setBaseName] = useState("");
  const [baseDescription, setBaseDescription] = useState("");
  const [documentTitle, setDocumentTitle] = useState("");
  const [documentContent, setDocumentContent] = useState("");
  const [sourceRef, setSourceRef] = useState("");
  const [question, setQuestion] = useState("");
  const [generateAnswer, setGenerateAnswer] = useState(false);
  const [queryResult, setQueryResult] = useState<QueryResponse | null>(null);
  const [documentPreview, setDocumentPreview] = useState<KnowledgeDocument | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  function loadBases(preferredId = "") {
    return apiGet<KnowledgeBase[]>("/api/v1/knowledge-bases").then((rows) => {
      setBases(rows);
      setSelectedBaseId((current) => preferredId || current || rows[0]?.id || "");
    });
  }

  function loadDocuments(baseId: string) {
    if (!baseId) {
      setDocuments([]);
      return Promise.resolve();
    }
    return apiGet<KnowledgeDocument[]>(`/api/v1/knowledge-bases/${baseId}/documents`).then(setDocuments);
  }

  useEffect(() => {
    loadBases().catch((error: Error) => setMessage(error.message));
  }, []);

  useEffect(() => {
    loadDocuments(selectedBaseId).catch((error: Error) => setMessage(error.message));
    setQueryResult(null);
    setDocumentPreview(null);
  }, [selectedBaseId]);

  async function createBase(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const created = await apiPost<KnowledgeBase>(
        "/api/v1/knowledge-bases",
        { name: baseName, description: baseDescription },
        { idempotencyKey: idempotencyKey("knowledge-base") }
      );
      setBaseName("");
      setBaseDescription("");
      await loadBases(created.id);
      setMessage("Base de conhecimento criada somente para o tenant ativo.");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function addDocument(event: FormEvent) {
    event.preventDefault();
    if (!selectedBaseId) return;
    setBusy(true);
    setMessage("");
    try {
      await apiPost<KnowledgeDocument>(
        `/api/v1/knowledge-bases/${selectedBaseId}/documents`,
        {
          title: documentTitle,
          content: documentContent,
          source_type: "operator",
          source_ref: sourceRef,
          metadata: { ingestion_channel: "operator_ui" }
        },
        { idempotencyKey: idempotencyKey("knowledge-document") }
      );
      setDocumentTitle("");
      setDocumentContent("");
      setSourceRef("");
      await loadDocuments(selectedBaseId);
      setMessage("Documento indexado com chunking semântico e isolamento por tenant.");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function runQuery(event: FormEvent) {
    event.preventDefault();
    if (!selectedBaseId) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await apiPost<QueryResponse>(
        `/api/v1/knowledge-bases/${selectedBaseId}/query`,
        { question, top_k: 5, generate_answer: generateAnswer },
        { idempotencyKey: idempotencyKey("knowledge-query") }
      );
      setQueryResult(result);
      setMessage(result.results.length ? "Recuperação concluída dentro do tenant ativo." : "Nenhuma evidência relevante encontrada nesta base.");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function viewDocument(documentId: string) {
    if (!selectedBaseId) return;
    setMessage("");
    try {
      setDocumentPreview(await apiGet<KnowledgeDocument>(`/api/v1/knowledge-bases/${selectedBaseId}/documents/${documentId}`));
    } catch (error) {
      setMessage((error as Error).message);
    }
  }

  async function archiveDocument(documentId: string) {
    if (!selectedBaseId) return;
    setBusy(true);
    setMessage("");
    try {
      await apiPost<KnowledgeDocument>(
        `/api/v1/knowledge-bases/${selectedBaseId}/documents/${documentId}/archive`,
        undefined,
        { idempotencyKey: idempotencyKey("knowledge-archive") }
      );
      setDocumentPreview(null);
      await loadDocuments(selectedBaseId);
      setMessage("Documento arquivado e removido do índice de recuperação.");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const selectedBase = bases.find((base) => base.id === selectedBaseId);

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-950"><BookOpen className="h-6 w-6" /> Knowledge &amp; RAG</h1>
          <p className="mt-1 text-sm text-slate-600">Documentos, índice e consultas são limitados ao cliente selecionado no topo.</p>
        </div>
        <div className="inline-flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-800">
          <ShieldCheck className="h-4 w-4" /> Tenant-isolated
        </div>
      </header>

      {message && <div className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">{message}</div>}

      <div className="grid gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
        <aside className="space-y-4">
          <section className="panel p-4">
            <h2 className="flex items-center gap-2 font-semibold"><Database className="h-4 w-4" /> Bases deste cliente</h2>
            <select
              className="mt-3 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
              value={selectedBaseId}
              onChange={(event) => setSelectedBaseId(event.target.value)}
            >
              <option value="">Selecione uma base</option>
              {bases.map((base) => <option key={base.id} value={base.id}>{base.name}</option>)}
            </select>
            {selectedBase && (
              <div className="mt-3 rounded-md bg-slate-50 p-3 text-xs text-slate-600">
                <div>{selectedBase.description || "Sem descrição."}</div>
                <div className="mt-2 font-mono">{selectedBase.retrieval_version}</div>
              </div>
            )}
          </section>

          <form className="panel space-y-3 p-4" onSubmit={createBase}>
            <h2 className="font-semibold">Nova base</h2>
            <input className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" placeholder="Nome" value={baseName} onChange={(event) => setBaseName(event.target.value)} required />
            <textarea className="min-h-20 w-full rounded-md border border-slate-300 px-3 py-2 text-sm" placeholder="Descrição" value={baseDescription} onChange={(event) => setBaseDescription(event.target.value)} />
            <button disabled={busy} className="w-full rounded-md bg-slate-950 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">Criar base isolada</button>
          </form>
        </aside>

        <div className="space-y-5">
          <section className="panel p-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="flex items-center gap-2 font-semibold"><FilePlus2 className="h-4 w-4" /> Ingestão de conhecimento</h2>
              <span className="text-xs text-slate-500">Texto/Markdown · imutável · auditado</span>
            </div>
            <form className="mt-4 grid gap-3" onSubmit={addDocument}>
              <div className="grid gap-3 md:grid-cols-2">
                <input className="rounded-md border border-slate-300 px-3 py-2 text-sm" placeholder="Título do documento" value={documentTitle} onChange={(event) => setDocumentTitle(event.target.value)} required disabled={!selectedBaseId} />
                <input className="rounded-md border border-slate-300 px-3 py-2 text-sm" placeholder="Referência da fonte (opcional)" value={sourceRef} onChange={(event) => setSourceRef(event.target.value)} disabled={!selectedBaseId} />
              </div>
              <textarea className="min-h-44 rounded-md border border-slate-300 px-3 py-2 font-mono text-sm" placeholder="Cole aqui o conteúdo autorizado deste cliente..." value={documentContent} onChange={(event) => setDocumentContent(event.target.value)} required disabled={!selectedBaseId} />
              <button disabled={busy || !selectedBaseId} className="justify-self-start rounded-md bg-cyan-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Indexar documento</button>
            </form>
            <div className="mt-4 space-y-2">
              {documents.map((document) => (
                <div key={document.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-slate-200 px-3 py-2 text-sm">
                  <div><div className="font-medium">{document.title}</div><div className="text-xs text-slate-500">{document.source_type} · {document.checksum.slice(0, 12)}</div></div>
                  <div className="flex items-center gap-2">
                    <button type="button" onClick={() => viewDocument(document.id)} className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50">Visualizar</button>
                    {document.status !== "archived" && <button type="button" disabled={busy} onClick={() => archiveDocument(document.id)} className="rounded border border-rose-200 px-2 py-1 text-xs text-rose-700 hover:bg-rose-50 disabled:opacity-50">Arquivar</button>}
                    <span className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs text-emerald-800">{document.status}</span>
                  </div>
                </div>
              ))}
              {selectedBaseId && !documents.length && <div className="text-sm text-slate-500">Nenhum documento indexado nesta base.</div>}
            </div>
            {documentPreview && (
              <div className="mt-4 rounded-md border border-cyan-200 bg-cyan-50 p-4">
                <div className="flex items-center justify-between gap-3"><h3 className="font-medium">{documentPreview.title}</h3><button type="button" className="text-xs text-slate-600" onClick={() => setDocumentPreview(null)}>Fechar</button></div>
                <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap text-sm text-slate-700">{documentPreview.content}</pre>
              </div>
            )}
          </section>

          <section className="panel p-4">
            <h2 className="flex items-center gap-2 font-semibold"><Search className="h-4 w-4" /> Consulta RAG</h2>
            <form className="mt-4 space-y-3" onSubmit={runQuery}>
              <textarea className="min-h-24 w-full rounded-md border border-slate-300 px-3 py-2 text-sm" placeholder="Faça uma pergunta sobre este cliente..." value={question} onChange={(event) => setQuestion(event.target.value)} required disabled={!selectedBaseId} />
              <div className="flex flex-wrap items-center justify-between gap-3">
                <label className="flex items-center gap-2 text-sm text-slate-600">
                  <input type="checkbox" checked={generateAnswer} onChange={(event) => setGenerateAnswer(event.target.checked)} />
                  Gerar resposta com LLM (exige opt-in do cliente)
                </label>
                <button disabled={busy || !selectedBaseId} className="rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Buscar conhecimento</button>
              </div>
            </form>

            {queryResult?.answer && <div className="mt-4 rounded-md border border-cyan-200 bg-cyan-50 p-4 text-sm whitespace-pre-wrap">{queryResult.answer}</div>}
            <div className="mt-4 space-y-3">
              {queryResult?.results.map((result, index) => (
                <article key={result.chunk_id} className="rounded-md border border-slate-200 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="font-medium">[SOURCE {index + 1}] {result.document_title}</div>
                    <div className="text-xs text-slate-500">score {result.score.toFixed(3)} · vector {result.score_components.vector.toFixed(3)} · lexical {result.score_components.lexical.toFixed(3)}</div>
                  </div>
                  <div className="mt-3 whitespace-pre-wrap text-sm text-slate-700">{result.content}</div>
                </article>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
