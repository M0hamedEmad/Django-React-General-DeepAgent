import {
  BookOpen, Bot, Boxes, ChartColumn, FileChartColumn, Search, ShoppingCart, Sparkles, TriangleAlert, Users, Wrench, type LucideIcon,
} from "lucide-react";
import type { MentionKind } from "./types";

/** The icon names the backend's JSON may use. An unknown name gets a spark
 *  rather than nothing, so a typo in the file is visible, not silent. */
const ICONS: Record<string, LucideIcon> = {
  "file-chart-column": FileChartColumn,
  "chart-column": ChartColumn,
  "shopping-cart": ShoppingCart,
  "triangle-alert": TriangleAlert,
  "book-open": BookOpen,
  search: Search,
  users: Users,
  boxes: Boxes,
  wrench: Wrench,
  bot: Bot,
};

export function Icon({ name, size = 15, className }: { name?: string; size?: number; className?: string }) {
  const Glyph = (name && ICONS[name]) || Sparkles;
  return <Glyph size={size} className={className} />;
}

export const MENTION_ICON: Record<MentionKind, string> = { skill: "book-open", agent: "bot", tool: "wrench" };
