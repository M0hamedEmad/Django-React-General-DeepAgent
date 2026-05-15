/** Compatibility wrapper for imports created before the workspace was generic. */
import { PresentationView } from "./generative-ui/Presentation";
import type { Report } from "./types";

export function ReportView({ report }: { report: Report }) {
  return <PresentationView presentation={report} />;
}
