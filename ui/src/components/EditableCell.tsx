import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Pencil } from "lucide-react";

import { Button } from "./Button";
import { IconButton } from "./IconButton";

/** A table cell that shows its value, with an Edit button. Edit swaps in an input with Save
 * and Cancel. Enter saves, Escape cancels, and Save with no change does not call onSave. */
export function EditableCell({
  value,
  label,
  onSave,
  mono = false,
  placeholder = "Not set",
}: {
  value: string;
  /** What the cell holds, for screen readers, e.g. "Field name". */
  label: string;
  onSave: (next: string) => void;
  mono?: boolean;
  placeholder?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  function start() {
    setDraft(value);
    setEditing(true);
  }

  function save() {
    const next = draft.trim();
    setEditing(false);
    if (next !== value) onSave(next);
  }

  function cancel() {
    setDraft(value);
    setEditing(false);
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") save();
    if (e.key === "Escape") cancel();
  }

  if (!editing) {
    return (
      <div className="cell-view">
        <span className={mono ? "cell-view__text mono" : "cell-view__text"}>
          {value || <span className="muted">{placeholder}</span>}
        </span>
        <IconButton icon={Pencil} label={`Edit ${label}`} onClick={start} />
      </div>
    );
  }

  return (
    <div className="cell-edit">
      <input
        ref={inputRef}
        className="input"
        aria-label={label}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
      />
      <Button variant="primary" size="sm" onClick={save}>
        Save
      </Button>
      <Button variant="ghost" size="sm" onClick={cancel}>
        Cancel
      </Button>
    </div>
  );
}
