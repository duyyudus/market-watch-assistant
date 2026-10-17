import { useEffect, useRef, useState } from "react";

import { api } from "../../api";
import type {
  DiscussionContextWindow,
  DiscussionMessage,
  DiscussionSource,
  DiscussionTimeframe,
} from "../../api";

const DISCUSSION_MESSAGE_LIMIT = 20;
const DISCUSSION_MESSAGE_CHARACTER_LIMIT = 8_000;
const DISCUSSION_CONTEXT_CHARACTER_LIMIT = 56_000;

export type DiscussionUiMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources?: DiscussionSource[];
  contextWindow?: DiscussionContextWindow | null;
};

export type DiscussionChatController = {
  timeframe: DiscussionTimeframe;
  // Configured longest window; null until loaded (or if the settings request fails).
  maxWindowDays: number | null;
  messages: DiscussionUiMessage[];
  draft: string;
  loading: boolean;
  error: string | null;
  setDraft: (value: string) => void;
  resetForTimeframe: (timeframe: DiscussionTimeframe) => void;
  startNewChat: () => void;
  // Sends the composer draft, or `preset` directly (leaving the draft untouched).
  sendMessage: (preset?: string) => Promise<void>;
};

function codePoints(value: string) {
  return Array.from(value);
}

function truncateCodePoints(value: string, maximum: number) {
  return codePoints(value).slice(0, maximum).join("");
}

function codePointLength(value: string) {
  return codePoints(value).length;
}

export function buildDiscussionRequestMessages(
  history: DiscussionMessage[],
  latestUserContent: string,
): DiscussionMessage[] {
  const latestMessage: DiscussionMessage = {
    role: "user",
    content: truncateCodePoints(latestUserContent, DISCUSSION_MESSAGE_CHARACTER_LIMIT),
  };
  const newestFirst: DiscussionMessage[] = [latestMessage];
  let remainingCharacters =
    DISCUSSION_CONTEXT_CHARACTER_LIMIT - codePointLength(latestMessage.content);

  for (let index = history.length - 1; index >= 0; index -= 1) {
    if (newestFirst.length >= DISCUSSION_MESSAGE_LIMIT || remainingCharacters <= 0) break;
    const message = history[index];
    const content = truncateCodePoints(
      message.content,
      Math.min(DISCUSSION_MESSAGE_CHARACTER_LIMIT, remainingCharacters),
    );
    if (!content) continue;
    newestFirst.push({ role: message.role, content });
    remainingCharacters -= codePointLength(content);
  }

  return newestFirst.reverse();
}

function discussionErrorMessage(error: unknown) {
  const message = error instanceof Error ? error.message : "Discussion is unavailable";
  if (/^422\b/.test(message)) {
    return "The discussion request could not be validated. Shorten your message or start a new chat.";
  }
  return message;
}

// In auto mode, the window the last answer found in the conversation. Sent separately
// so follow-ups keep it after the question that named it is trimmed from history.
function previousWindow(messages: DiscussionUiMessage[]) {
  const lastAnswer = [...messages].reverse().find((message) => message.role === "assistant");
  const contextWindow = lastAnswer?.contextWindow;
  return contextWindow &&
    (contextWindow.source === "inferred" || contextWindow.source === "carried")
    ? {
        previous_window_start: contextWindow.start,
        ...(contextWindow.end ? { previous_window_end: contextWindow.end } : {}),
      }
    : {};
}

export function useDiscussionChat(): DiscussionChatController {
  const [timeframe, setTimeframe] = useState<DiscussionTimeframe>("auto");
  const [maxWindowDays, setMaxWindowDays] = useState<number | null>(null);
  const [messages, setMessages] = useState<DiscussionUiMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nextMessageId = useRef(1);
  const requestInFlight = useRef(false);

  useEffect(() => {
    let cancelled = false;
    api
      .discussionSettings()
      .then((settings) => {
        if (!cancelled) setMaxWindowDays(settings.max_window_days);
      })
      .catch(() => {
        // Without settings the Max option is hidden; other timeframes still work.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function startNewChat() {
    setMessages([]);
    setDraft("");
    setError(null);
  }

  function resetForTimeframe(nextTimeframe: DiscussionTimeframe) {
    setTimeframe(nextTimeframe);
    startNewChat();
  }

  async function sendMessage(preset?: string) {
    const content = (preset ?? draft).trim();
    if (!content || requestInFlight.current) return;

    const previousMessages = messages;
    const userMessage: DiscussionUiMessage = {
      id: nextMessageId.current++,
      role: "user",
      content,
    };
    const requestMessages = buildDiscussionRequestMessages(
      messages.map(({ role, content: messageContent }) => ({
        role,
        content: messageContent,
      })),
      content,
    );
    setMessages((current) => [...current, userMessage].slice(-DISCUSSION_MESSAGE_LIMIT));
    if (preset === undefined) setDraft("");
    setError(null);
    requestInFlight.current = true;
    setLoading(true);

    try {
      const response = await api.discussionChat({
        timeframe,
        messages: requestMessages,
        ...(timeframe === "auto" ? previousWindow(messages) : {}),
      });
      const assistantMessage: DiscussionUiMessage = {
        id: nextMessageId.current++,
        role: "assistant",
        content: response.answer,
        sources: response.sources,
        contextWindow: response.context_window,
      };
      setMessages((current) =>
        [...current, assistantMessage].slice(-DISCUSSION_MESSAGE_LIMIT),
      );
    } catch (sendError) {
      setMessages(previousMessages);
      if (preset === undefined) setDraft(content);
      setError(discussionErrorMessage(sendError));
    } finally {
      requestInFlight.current = false;
      setLoading(false);
    }
  }

  return {
    timeframe,
    maxWindowDays,
    messages,
    draft,
    loading,
    error,
    setDraft,
    resetForTimeframe,
    startNewChat,
    sendMessage,
  };
}
