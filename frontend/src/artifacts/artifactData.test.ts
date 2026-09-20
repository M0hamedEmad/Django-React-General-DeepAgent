import { describe, expect, it } from "vitest";
import { collectWorkspaceItems } from "../Chat";
import type { ChatMessage, Part } from "../types";
import {
  artifactFromToolPart,
  artifactUrl,
  hasSourceView,
  previewKind,
} from "./artifactData";

function filePart(input: Record<string, unknown>, state = "output-available"): Part {
  return {
    type: "tool-present_file",
    toolCallId: "file-1",
    state,
    input,
    output: "File is ready for the user.",
  };
}

describe("file artifact data", () => {
  it("accepts only completed safe workspace paths", () => {
    expect(artifactFromToolPart(filePart({ path: "/reports/q3.pdf", title: "Q3" }), "thread-1")).toMatchObject({
      kind: "file",
      path: "/reports/q3.pdf",
      title: "Q3",
      threadId: "thread-1",
    });
    expect(artifactFromToolPart(filePart({ path: "/reports/q3.pdf" }, "output-error"), "thread-1")).toBeNull();
    expect(artifactFromToolPart(filePart({ path: "/../secret" }), "thread-1")).toBeNull();
    expect(artifactFromToolPart(filePart({ path: "/.venv/bin/python" }), "thread-1")).toBeNull();
  });

  it("encodes every URL segment and keeps download explicit", () => {
    const artifact = artifactFromToolPart(filePart({ path: "/Q3 report/a#b.pdf" }), "thread 1");
    expect(artifact).not.toBeNull();
    expect(artifactUrl(artifact!, true)).toBe("/api/threads/thread%201/files/Q3%20report/a%23b.pdf?download=1");
  });

  it("routes supported formats and falls back to download", () => {
    expect(previewKind("/dashboard.HTML")).toBe("html");
    expect(previewKind("/report.docx")).toBe("docx");
    expect(previewKind("/slides.pptx")).toBe("pptx");
    expect(previewKind("/archive.zip")).toBe("download");
  });

  it("offers raw source only when it differs from the normal preview", () => {
    expect(hasSourceView("/dashboard.html")).toBe(true);
    expect(hasSourceView("/notes.md")).toBe(true);
    expect(hasSourceView("/data.json")).toBe(true);
    expect(hasSourceView("/script.py")).toBe(true);
    expect(hasSourceView("/report.pdf")).toBe(false);
  });

  it("restores reports and files from checkpoint messages", () => {
    const messages = [{
      id: "assistant-1",
      role: "assistant",
      parts: [
        filePart({ path: "/report.pdf" }),
        {
          type: "tool-present_report",
          toolCallId: "report-1",
          state: "output-available",
          input: { title: "Summary", blocks: [{ type: "markdown", content: "Done" }] },
          output: "ready",
        },
      ],
    }] as ChatMessage[];

    expect(collectWorkspaceItems(messages, "thread-1").map((item) => item.kind)).toEqual(["file", "presentation"]);
  });
});
