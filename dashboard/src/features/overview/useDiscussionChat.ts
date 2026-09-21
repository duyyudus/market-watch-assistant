import { useRef, useState } from "react";

import { api } from "../../api";
import type {
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
};

export type DiscussionChatController = {
  timeframe: DiscussionTimeframe;
  messages: DiscussionUiMessage[];
  draft: string;
  loading: boolean;
  error: string | null;
  setDraft: (value: string) => void;
  resetForTimeframe: (timeframe: DiscussionTimeframe) => void;
  startNewChat: () => void;
  sendMessage: () => Promise<void>;
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

export function useDiscussionChat(): DiscussionChatController {
  const [timeframe, setTimeframe] = useState<DiscussionTimeframe>("24h");
  const [messages, setMessages] = useState<DiscussionUiMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nextMessageId = useRef(1);
  const requestInFlight = useRef(false);

  function startNewChat() {
    setMessages([]);
    setDraft("");
    setError(null);
  }

  function resetForTimeframe(nextTimeframe: DiscussionTimeframe) {
    setTimeframe(nextTimeframe);
    startNewChat();
  }

  async function sendMessage() {
    const content = draft.trim();
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
    setDraft("");
    setError(null);
    requestInFlight.current = true;
    setLoading(true);

    try {
      const response = await api.discussionChat({ timeframe, messages: requestMessages });
      const assistantMessage: DiscussionUiMessage = {
        id: nextMessageId.current++,
        role: "assistant",
        content: response.answer,
        sources: response.sources,
      };
      setMessages((current) =>
        [...current, assistantMessage].slice(-DISCUSSION_MESSAGE_LIMIT),
      );
    } catch (sendError) {
      setMessages(previousMessages);
      setDraft(content);
      setError(discussionErrorMessage(sendError));
    } finally {
      requestInFlight.current = false;
      setLoading(false);
    }
  }

  return {
    timeframe,
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
