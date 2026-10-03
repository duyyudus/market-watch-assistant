import { useState } from "react";

const DISCUSSION_PRESETS_STORAGE_KEY = "mw-discussion-presets";
const DEFAULT_DISCUSSION_PRESETS = ["What's new today?"];
export const DISCUSSION_PRESET_CHARACTER_LIMIT = 200;
export const DISCUSSION_PRESET_LIMIT = 12;

function loadPresets(): string[] {
  try {
    const stored = localStorage.getItem(DISCUSSION_PRESETS_STORAGE_KEY);
    if (stored === null) return DEFAULT_DISCUSSION_PRESETS;
    const parsed: unknown = JSON.parse(stored);
    if (!Array.isArray(parsed)) return DEFAULT_DISCUSSION_PRESETS;
    return parsed
      .filter((value): value is string => typeof value === "string" && value.trim() !== "")
      .slice(0, DISCUSSION_PRESET_LIMIT);
  } catch {
    return DEFAULT_DISCUSSION_PRESETS;
  }
}

// Saved starter questions for the Discussion panel. Kept in localStorage so they
// outlive the temporary chat; an explicitly emptied list stays empty.
export function useDiscussionPresets() {
  const [presets, setPresets] = useState<string[]>(loadPresets);

  function persist(next: string[]) {
    setPresets(next);
    try {
      localStorage.setItem(DISCUSSION_PRESETS_STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Storage unavailable: presets still work for this session.
    }
  }

  function addPreset(value: string) {
    const preset = value.trim().slice(0, DISCUSSION_PRESET_CHARACTER_LIMIT);
    if (!preset || presets.includes(preset) || presets.length >= DISCUSSION_PRESET_LIMIT) {
      return false;
    }
    persist([...presets, preset]);
    return true;
  }

  function removePreset(preset: string) {
    persist(presets.filter((existing) => existing !== preset));
  }

  return { presets, addPreset, removePreset };
}
