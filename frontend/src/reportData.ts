import type { Part, Report } from "./types";
import { isRecord, reportFromToolPart as parseReport } from "./generative-ui/presentationData";

/** Compatibility entry point for the old report-specific imports. */
export function reportFromToolPart(part: Part): Report | null {
  return parseReport(part);
}

export { isRecord };
