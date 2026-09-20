import {
  AlertTriangle,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Download,
  File,
  FileCode2,
  Loader2,
} from "lucide-react";
import { useEffect, useRef, useState, type RefObject } from "react";
import { Markdown } from "../Markdown";
import type { FileArtifact as FileArtifactType, Part } from "../types";
import {
  artifactFromToolPart,
  artifactUrl,
  fileExtension,
  previewKind,
  type PreviewKind,
} from "./artifactData";

type ArtifactMetadata = {
  size: number;
  contentType: string;
  previewAllowed: boolean;
  previewReason: string;
};

type LoadState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; value: T };

export function FileArtifactPart({ part, threadId, onOpen }: {
  part: Part;
  threadId: string;
  onOpen: (artifact: FileArtifactType) => void;
}) {
  const artifact = artifactFromToolPart(part, threadId);
  if (!artifact) {
    if (part.state === "output-error") {
      return <InlineFileError message={typeof part.errorText === "string" ? part.errorText : "The file could not be presented."} />;
    }
    return null;
  }
  const extension = fileExtension(artifact.path).toUpperCase() || "FILE";
  return (
    <div className="flex w-full max-w-md items-center gap-2 rounded-xl border border-line bg-app/70 p-2.5">
      <button
        type="button"
        onClick={() => onOpen(artifact)}
        className="group/file flex min-w-0 flex-1 items-center gap-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/25"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line bg-surface text-gray-600 shadow-[0_1px_1px_rgba(15,23,42,0.04)]">
          <FileCode2 size={17} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-gray-900">{artifact.title}</span>
          <span className="mt-0.5 block text-xs text-gray-500">{extension} · Open in workspace</span>
        </span>
        <ArrowUpRight size={15} className="text-gray-400 transition-transform group-hover/file:-translate-y-0.5 group-hover/file:translate-x-0.5" />
      </button>
      <a
        href={artifactUrl(artifact, true)}
        download
        title="Download file"
        aria-label={`Download ${artifact.title}`}
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-gray-500 hover:bg-gray-100 hover:text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/30"
      >
        <Download size={16} />
      </a>
    </div>
  );
}

export function FileArtifactView({ artifact, source = false }: { artifact: FileArtifactType; source?: boolean }) {
  const url = artifactUrl(artifact);
  const [metadata, setMetadata] = useState<LoadState<ArtifactMetadata>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    void loadMetadata(url).then(
      (value) => { if (!cancelled) setMetadata({ status: "ready", value }); },
      (error) => { if (!cancelled) setMetadata({ status: "error", message: errorMessage(error) }); },
    );
    return () => { cancelled = true; };
  }, [url]);

  if (metadata.status === "loading") return <Loading label="Loading file…" />;
  if (metadata.status === "error") return <PreviewUnavailable message={metadata.message} artifact={artifact} />;

  const info = metadata.value;
  return (
    <div className="mx-auto w-full max-w-[1040px] pb-12">
      <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
        <span>{fileExtension(artifact.path).toUpperCase() || "File"}</span>
        <span>{formatBytes(info.size)}</span>
        <span className="truncate">{artifact.path}</span>
      </div>
      {info.previewAllowed ? (
        source
          ? <SourcePreview url={url} />
          : <FilePreview artifact={artifact} kind={previewKind(artifact.path)} url={url} />
      ) : (
        <PreviewUnavailable message={info.previewReason || "A browser preview is not available for this file."} artifact={artifact} />
      )}
    </div>
  );
}

function FilePreview({ artifact, kind, url }: { artifact: FileArtifactType; kind: PreviewKind; url: string }) {
  switch (kind) {
    case "html": return <HtmlPreview title={artifact.title} url={url} />;
    case "markdown": return <MarkdownPreview url={url} />;
    case "source": return <SourcePreview url={url} wrap />;
    case "pdf": return <PdfPreview url={url} />;
    case "image": return <ImagePreview title={artifact.title} url={url} />;
    case "csv": return <CsvPreview url={url} />;
    case "json": return <JsonPreview url={url} />;
    case "docx": return <DocxPreview url={url} />;
    case "xlsx": return <XlsxPreview url={url} />;
    case "pptx": return <PptxPreview url={url} />;
    default: return <PreviewUnavailable message="A browser preview is not available for this file." artifact={artifact} />;
  }
}

function HtmlPreview({ title, url }: { title: string; url: string }) {
  return (
    <iframe
      title={title}
      src={url}
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      className="h-[calc(100vh-11rem)] min-h-[480px] w-full rounded-xl border border-line bg-white"
    />
  );
}

function ImagePreview({ title, url }: { title: string; url: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <SimpleError message="The image could not be decoded." />;
  return <img src={url} alt={title} onError={() => setFailed(true)} className="mx-auto max-h-[calc(100vh-11rem)] max-w-full rounded-xl border border-line bg-white object-contain" />;
}

function MarkdownPreview({ url }: { url: string }) {
  const text = useRemoteText(url);
  if (text.status === "loading") return <Loading label="Loading Markdown…" />;
  if (text.status === "error") return <SimpleError message={text.message} />;
  return <div className="rounded-xl border border-line bg-surface p-5"><Markdown text={text.value} /></div>;
}

function SourcePreview({ url, wrap = false }: { url: string; wrap?: boolean }) {
  const text = useRemoteText(url);
  if (text.status === "loading") return <Loading label="Loading source…" />;
  if (text.status === "error") return <SimpleError message={text.message} />;
  return <pre className={`max-h-[calc(100vh-11rem)] overflow-auto rounded-xl border border-slate-800 bg-slate-950 p-4 text-[13px] leading-6 text-slate-100 ${wrap ? "whitespace-pre-wrap break-words" : ""}`}><code>{text.value}</code></pre>;
}

function JsonPreview({ url }: { url: string }) {
  const text = useRemoteText(url);
  if (text.status === "loading") return <Loading label="Loading JSON…" />;
  if (text.status === "error") return <SimpleError message={text.message} />;
  try {
    return <pre className="max-h-[calc(100vh-11rem)] overflow-auto rounded-xl border border-slate-800 bg-slate-950 p-4 text-[13px] leading-6 text-slate-100"><code>{JSON.stringify(JSON.parse(text.value), null, 2)}</code></pre>;
  } catch {
    return <SimpleError message="The JSON file is not valid." />;
  }
}

function CsvPreview({ url }: { url: string }) {
  const [state, setState] = useState<LoadState<{ rows: string[][]; limited: boolean }>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const text = await fetchText(url);
      const Papa = (await import("papaparse")).default;
      const parsed = Papa.parse<string[]>(text, { preview: 1001, skipEmptyLines: false });
      if (parsed.errors.length) throw new Error("The CSV file could not be parsed.");
      const rows = parsed.data.slice(0, 1000).map((row) => row.slice(0, 100));
      return { rows, limited: parsed.data.length > 1000 || parsed.data.some((row) => row.length > 100) };
    })().then(
      (value) => { if (!cancelled) setState({ status: "ready", value }); },
      (error) => { if (!cancelled) setState({ status: "error", message: errorMessage(error) }); },
    );
    return () => { cancelled = true; };
  }, [url]);
  if (state.status === "loading") return <Loading label="Loading CSV…" />;
  if (state.status === "error") return <SimpleError message={state.message} />;
  return <DataTable rows={state.value.rows} limited={state.value.limited} />;
}

function XlsxPreview({ url }: { url: string }) {
  type Sheet = { sheet: string; data: unknown[][] };
  const [state, setState] = useState<LoadState<Sheet[]>>({ status: "loading" });
  const [selected, setSelected] = useState(0);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const response = await checkedFetch(url);
      const blob = await response.blob();
      const module = await import("read-excel-file/browser");
      const workbook = await module.default(blob);
      return workbook as Sheet[];
    })().then(
      (value) => { if (!cancelled) setState({ status: "ready", value }); },
      (error) => { if (!cancelled) setState({ status: "error", message: errorMessage(error) }); },
    );
    return () => { cancelled = true; };
  }, [url]);
  if (state.status === "loading") return <Loading label="Loading workbook…" />;
  if (state.status === "error") return <SimpleError message={state.message} />;
  const sheet = state.value[selected];
  if (!sheet) return <SimpleError message="The workbook has no readable sheets." />;
  const rows = sheet.data.slice(0, 1000).map((row) => row.slice(0, 100).map(displayCell));
  const limited = sheet.data.length > 1000 || sheet.data.some((row) => row.length > 100);
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-1.5">
        {state.value.map((item, index) => (
          <button key={`${item.sheet}:${index}`} type="button" onClick={() => setSelected(index)} className={`rounded-lg px-3 py-1.5 text-xs ${selected === index ? "bg-emerald-600 text-white" : "border border-line bg-surface text-gray-600 hover:bg-gray-50"}`}>{item.sheet || `Sheet ${index + 1}`}</button>
        ))}
      </div>
      <DataTable rows={rows} limited={limited} />
    </div>
  );
}

function DocxPreview({ url }: { url: string }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!ready || !frame.current?.contentDocument) return;
    let cancelled = false;
    const document = frame.current.contentDocument;
    document.body.replaceChildren();
    void (async () => {
      const response = await checkedFetch(url);
      const blob = await response.blob();
      const { renderAsync } = await import("docx-preview");
      if (cancelled) return;
      await renderAsync(blob, document.body, document.head, {
        breakPages: true,
        renderHeaders: true,
        renderFooters: true,
        renderFootnotes: true,
        renderEndnotes: true,
        renderAltChunks: false,
        useBase64URL: true,
      });
    })().catch((reason) => { if (!cancelled) setError(errorMessage(reason)); });
    return () => { cancelled = true; };
  }, [ready, url]);
  if (error) return <SimpleError message={error} />;
  return <iframe ref={frame} title="Word document preview" sandbox="allow-same-origin" srcDoc="<!doctype html><html><head></head><body></body></html>" onLoad={() => setReady(true)} className="h-[calc(100vh-11rem)] min-h-[540px] w-full rounded-xl border border-line bg-white" />;
}

function PdfPreview({ url }: { url: string }) {
  type PdfModule = typeof import("react-pdf");
  const [module, setModule] = useState<PdfModule | null>(null);
  const [pages, setPages] = useState(0);
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [width, container] = useContainerWidth();
  useEffect(() => {
    let cancelled = false;
    void import("react-pdf").then((loaded) => {
      loaded.pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
      if (!cancelled) setModule(loaded);
    }, (reason) => { if (!cancelled) setError(errorMessage(reason)); });
    return () => { cancelled = true; };
  }, []);
  if (error) return <SimpleError message={error} />;
  if (!module) return <Loading label="Loading PDF viewer…" />;
  const { Document, Page } = module;
  return (
    <div ref={container} className="min-w-0">
      <PageControls current={page} total={pages} onChange={setPage} label="Page" />
      <div className="flex justify-center overflow-auto rounded-xl border border-line bg-gray-100 p-3">
        <Document file={url} onLoadSuccess={({ numPages }) => { setPages(numPages); setPage(1); }} onLoadError={(reason) => setError(errorMessage(reason))} loading={<Loading label="Loading PDF…" />}>
          <Page pageNumber={page} width={Math.max(280, Math.min(width - 26, 920))} renderAnnotationLayer={false} renderTextLayer={false} />
        </Document>
      </div>
    </div>
  );
}

function PptxPreview({ url }: { url: string }) {
  type PptxModule = typeof import("@office-kit/pptx");
  type Deck = Awaited<ReturnType<PptxModule["loadPresentation"]>>;
  type Slide = ReturnType<PptxModule["getSlides"]>[number];
  const [deck, setDeck] = useState<{ presentation: Deck; slides: Slide[] } | null>(null);
  const [imageUrls, setImageUrls] = useState<string[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setDeck(null);
    setImageUrls([]);
    setError("");
    void (async () => {
      const response = await checkedFetch(url);
      const bytes = new Uint8Array(await response.arrayBuffer());
      const pptx = await import("@office-kit/pptx");
      const presentation = await pptx.loadPresentation(bytes);
      const slides = pptx.getSlides(presentation);
      if (!slides.length) throw new Error("The presentation contains no slides.");
      return { presentation, slides };
    })().then(
      (value) => { if (!cancelled) setDeck(value); },
      (reason) => { if (!cancelled) setError(errorMessage(reason)); },
    );
    return () => { cancelled = true; };
  }, [url]);

  useEffect(() => {
    if (!deck) return;
    let cancelled = false;
    const objectUrls: string[] = [];
    const releaseObjectUrls = () => objectUrls.splice(0).forEach((objectUrl) => URL.revokeObjectURL(objectUrl));
    void (async () => {
      const preview = await import("@office-kit/pptx-preview");
      const rendered = deck.slides.map((slide) => {
        const svg = preview.renderSlideToSvg(deck.presentation, slide);
        const objectUrl = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
        objectUrls.push(objectUrl);
        return objectUrl;
      });
      if (cancelled) releaseObjectUrls();
      else setImageUrls(rendered);
    })().catch((reason) => {
      releaseObjectUrls();
      if (!cancelled) setError(errorMessage(reason));
    });
    return () => {
      cancelled = true;
      releaseObjectUrls();
    };
  }, [deck]);

  if (error) return <SimpleError message={error} />;
  if (!deck || imageUrls.length !== deck.slides.length) return <Loading label="Rendering presentation…" />;
  return (
    <div className="space-y-8">
      {imageUrls.map((imageUrl, index) => (
        <figure key={imageUrl} className="scroll-mt-5">
          <figcaption className="mb-2 text-xs font-medium text-gray-500">Slide {index + 1} of {deck.slides.length}</figcaption>
          <div className="overflow-hidden rounded-xl border border-line bg-gray-100 p-3">
            <img src={imageUrl} alt={`Slide ${index + 1}`} className="block w-full bg-white shadow-sm" />
          </div>
        </figure>
      ))}
    </div>
  );
}

function PageControls({ current, total, onChange, label }: { current: number; total: number; onChange: (page: number) => void; label: string }) {
  if (total <= 1) return null;
  return (
    <div className="mb-3 flex items-center justify-center gap-3 text-sm text-gray-600">
      <button type="button" disabled={current <= 1} onClick={() => onChange(current - 1)} className="rounded-full border border-line bg-surface p-1.5 disabled:opacity-35"><ChevronLeft size={16} /></button>
      <span>{label} {current} of {total}</span>
      <button type="button" disabled={current >= total} onClick={() => onChange(current + 1)} className="rounded-full border border-line bg-surface p-1.5 disabled:opacity-35"><ChevronRight size={16} /></button>
    </div>
  );
}

function DataTable({ rows, limited }: { rows: string[][]; limited: boolean }) {
  if (!rows.length) return <SimpleError message="This file contains no rows." />;
  return (
    <div>
      {limited && <p className="mb-2 text-xs text-amber-700">Preview limited to 1,000 rows and 100 columns. Download the file for complete data.</p>}
      <div className="max-h-[calc(100vh-13rem)] overflow-auto rounded-xl border border-line bg-surface">
        <table className="min-w-full border-collapse text-xs">
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex} className={rowIndex === 0 ? "bg-gray-50 font-medium" : ""}>
                {row.map((cell, columnIndex) => <td key={columnIndex} className="max-w-64 border-r border-b border-line px-2.5 py-2 whitespace-nowrap">{cell}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PreviewUnavailable({ message, artifact }: { message: string; artifact: FileArtifactType }) {
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-950">
      <div className="flex items-start gap-3"><AlertTriangle size={18} className="mt-0.5 shrink-0 text-amber-600" /><div><h3 className="font-semibold">Preview unavailable</h3><p className="mt-1 text-amber-900/75">{message}</p></div></div>
      <a href={artifactUrl(artifact, true)} download className="mt-4 inline-flex items-center gap-2 rounded-lg bg-amber-900 px-3 py-2 text-xs font-medium text-white hover:bg-amber-800"><Download size={14} />Download file</a>
    </div>
  );
}

function InlineFileError({ message }: { message: string }) {
  return <div className="flex max-w-md items-start gap-2 rounded-lg border border-red-100 bg-red-50/60 p-2.5 text-xs text-red-700"><AlertTriangle size={14} className="mt-0.5 shrink-0" /><span>{message}</span></div>;
}

function SimpleError({ message }: { message: string }) {
  return <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"><AlertTriangle size={16} className="mt-0.5 shrink-0" /><div><h3 className="font-semibold">Preview unavailable</h3><p className="mt-1">{message}</p></div></div>;
}

function Loading({ label }: { label: string }) {
  return <div className="flex min-h-32 items-center justify-center gap-2 text-sm text-gray-500"><Loader2 size={16} className="animate-spin text-emerald-600" />{label}</div>;
}

function useRemoteText(url: string): LoadState<string> {
  const [state, setState] = useState<LoadState<string>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    void fetchText(url).then(
      (value) => { if (!cancelled) setState({ status: "ready", value }); },
      (error) => { if (!cancelled) setState({ status: "error", message: errorMessage(error) }); },
    );
    return () => { cancelled = true; };
  }, [url]);
  return state;
}

function useContainerWidth(): [number, RefObject<HTMLDivElement | null>] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(760);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [width, ref];
}

async function loadMetadata(url: string): Promise<ArtifactMetadata> {
  const response = await checkedFetch(url, { method: "HEAD" });
  return {
    size: Number(response.headers.get("Content-Length") ?? 0),
    contentType: response.headers.get("Content-Type") ?? "application/octet-stream",
    previewAllowed: response.headers.get("X-Artifact-Preview") === "available",
    previewReason: response.headers.get("X-Artifact-Preview-Reason") ?? "",
  };
}

async function fetchText(url: string): Promise<string> {
  return (await checkedFetch(url)).text();
}

async function checkedFetch(url: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(url, { credentials: "same-origin", ...init });
  if (response.status === 401) {
    location.href = `/accounts/login/?next=${encodeURIComponent(location.pathname)}`;
    throw new Error("Login required.");
  }
  if (!response.ok) throw new Error(`The server returned ${response.status}.`);
  return response;
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : "The file format may be invalid or unsupported.";
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "Unknown size";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function displayCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (value instanceof Date) return value.toLocaleString();
  return String(value);
}
