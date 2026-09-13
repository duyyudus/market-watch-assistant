import { Plus, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { api } from "../../api";

export function WatchedTopicsModal({ onClose }: { onClose: () => void }) {
  const [topics, setTopics] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const element = dialog.current;
    element?.showModal();
    let active = true;
    api.watchedTopics()
      .then((value) => {
        if (active) {
          setTopics(value.topics);
          setLoaded(true);
        }
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : "Failed to load topics");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      element?.close();
      previous?.focus();
    };
  }, []);

  async function save() {
    if (loading || saving || !loaded) return;
    const trimmed = topics.map((topic) => topic.trim());
    if (trimmed.some((topic) => !topic || [...topic].length > 300)) {
      setError("Each phrase must contain 1–300 characters.");
      return;
    }
    if (new Set(trimmed.map((topic) => topic.toLowerCase())).size !== trimmed.length) {
      setError("Topic phrases must be unique.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.updateWatchedTopics({ topics: trimmed });
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save topics");
    } finally {
      setSaving(false);
    }
  }

  return createPortal(
    <dialog
      ref={dialog}
      aria-labelledby="watched-topics-title"
      className="m-auto max-h-[85vh] w-[calc(100vw-2rem)] max-w-xl overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-950 p-5 text-zinc-200 shadow-2xl backdrop:bg-black/60"
      onCancel={(event) => {
        event.preventDefault();
        if (!saving) onClose();
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="watched-topics-title" className="text-lg font-semibold">Watched Topics</h2>
        <button
          aria-label="Close watched topics"
          className="btn btn-ghost btn-sm btn-square"
          disabled={saving}
          onClick={onClose}
          type="button"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <p className="my-3 text-sm text-zinc-400">
        Add phrases to follow in Daily synthesis. Changes apply on the next scheduled build or Rebuild.
      </p>
      {loading ? <p role="status">Loading topics…</p> : null}
      <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
        <fieldset disabled={loading || saving || !loaded} className="space-y-3">
          {topics.map((topic, index) => (
            <div className="flex items-center gap-2" key={index}>
              <input
                aria-label={`Topic ${index + 1}`}
                className="input input-bordered input-sm min-w-0 flex-1 bg-zinc-900"
                placeholder="e.g. rate decision next FOMC meeting"
                value={topic}
                onChange={(event) => setTopics(topics.map((value, position) =>
                  position === index ? event.target.value : value,
                ))}
              />
              <button
                aria-label={`Remove topic ${index + 1}`}
                className="btn btn-ghost btn-sm btn-square"
                type="button"
                onClick={() => setTopics(topics.filter((_, position) => position !== index))}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
          {loaded && topics.length === 0 ? (
            <p className="text-sm text-zinc-400">No watched topics yet.</p>
          ) : null}
          <button
            className="btn btn-outline btn-sm gap-1"
            disabled={topics.length >= 30}
            onClick={() => setTopics([...topics, ""])}
            type="button"
          >
            <Plus className="h-4 w-4" />Add topic
          </button>
          <span className="ml-3 text-xs text-zinc-500">{topics.length}/30 topics</span>
        </fieldset>
        {error ? <p className="mt-3 text-sm text-error" role="alert">{error}</p> : null}
        <div className="mt-5 flex justify-end gap-2">
          <button
            className="btn btn-ghost btn-sm"
            disabled={saving}
            onClick={onClose}
            type="button"
          >
            Cancel
          </button>
          <button
            className="btn btn-primary btn-sm"
            disabled={loading || saving || !loaded}
            type="submit"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </dialog>, document.body,
  );
}
