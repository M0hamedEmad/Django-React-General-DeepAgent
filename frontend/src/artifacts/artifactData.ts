import type { FileArtifact, Part } from "../types";
import { isRecord } from "../generative-ui/presentationData";

const FILE_PART = "tool-present_file";

const MARKDOWN = new Set(["md", "markdown"]);
const IMAGES = new Set(["png", "jpg", "jpeg", "svg"]);
const SOURCE = new Set([
  "css", "go", "h", "ini", "java", "js", "jsx", "log", "mjs", "php",
  "py", "rb", "rs", "sh", "sql", "toml", "ts", "tsx", "txt", "xml",
  "yaml", "yml",
]);

export type PreviewKind =
  | "html"
  | "markdown"
  | "source"
  | "pdf"
  | "image"
  | "csv"
  | "json"
  | "docx"
  | "xlsx"
  | "pptx"
  | "download";

export function isFileArtifactPart(part: Part): boolean {
  return part.type === FILE_PART;
}

export function artifactFromToolPart(part: Part, threadId: string): FileArtifact | null {
  if (part.type !== FILE_PART || part.state !== "output-available") return null;
  const input = isRecord(part.input) ? part.input : {};
  if (!safeVirtualPath(input.path)) return null;
  const path = input.path;
  const title = typeof input.title === "string" && input.title.trim()
    ? input.title.trim()
    : fileName(path);
  return {
    kind: "file",
    id: typeof part.toolCallId === "string" ? part.toolCallId : `file:${path}`,
    threadId,
    path,
    title,
  };
}

export function previewKind(path: string): PreviewKind {
  const extension = fileExtension(path);
  if (extension === "html" || extension === "htm") return "html";
  if (MARKDOWN.has(extension)) return "markdown";
  if (SOURCE.has(extension)) return "source";
  if (extension === "pdf") return "pdf";
  if (IMAGES.has(extension)) return "image";
  if (extension === "csv") return "csv";
  if (extension === "json") return "json";
  if (extension === "docx") return "docx";
  if (extension === "xlsx") return "xlsx";
  if (extension === "pptx") return "pptx";
  return "download";
}

export function hasSourceView(path: string): boolean {
  return ["html", "markdown", "source", "csv", "json"].includes(previewKind(path));
}

export function artifactUrl(artifact: FileArtifact, download = false): string {
  const encodedPath = artifact.path
    .split("/")
    .filter(Boolean)
    .map(encodeURIComponent)
    .join("/");
  const base = `/api/threads/${encodeURIComponent(artifact.threadId)}/files/${encodedPath}`;
  return download ? `${base}?download=1` : base;
}

export function fileExtension(path: string): string {
  const name = fileName(path);
  const index = name.lastIndexOf(".");
  return index > 0 ? name.slice(index + 1).toLowerCase() : "";
}

export function fileName(path: string): string {
  return path.split("/").filter(Boolean).at(-1) ?? "file";
}

function safeVirtualPath(value: unknown): value is string {
  if (typeof value !== "string" || !value.startsWith("/") || value.includes("\0") || value.includes("\\")) return false;
  const parts = value.split("/").filter(Boolean);
  return parts.length > 0 && parts.every((part) => part !== "." && part !== ".." && !part.startsWith("."));
}
