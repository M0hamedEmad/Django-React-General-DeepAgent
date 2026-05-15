import { Icon } from "./icons";
import type { Command } from "./types";

/** The chips under the empty page's message box: the commands the backend
 *  placed on the hero. Each one fills the composer with its prompt. */
export function Suggestions({ commands, onPick }: { commands: Command[]; onPick: (prompt: string) => void }) {
  if (commands.length === 0) return null;
  return (
    <div className="mt-6 flex flex-wrap justify-center gap-2">
      {commands.map((c) => (
        <button
          key={c.id}
          type="button"
          title={c.hint}
          onClick={() => onPick(c.prompt)}
          className="flex items-center gap-2 rounded-full border border-line bg-surface px-3.5 py-1.5 text-sm text-gray-700 hover:border-gray-300 hover:bg-app"
        >
          <span className="text-gray-500">
            <Icon name={c.icon} />
          </span>
          {c.label}
        </button>
      ))}
    </div>
  );
}
