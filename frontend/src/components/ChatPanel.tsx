import { useEffect, useRef, type KeyboardEvent } from "react";
import {
  AlertCircle,
  ArrowUp,
  BookOpen,
  FileSearch,
  LoaderCircle,
  MessageSquareText,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { Translation } from "../i18n";
import type { ConversationTurn } from "../types";

interface ChatPanelProps {
  turns: ConversationTurn[];
  question: string;
  canAsk: boolean;
  asking: boolean;
  progressLabel?: string;
  onQuestionChange: (question: string) => void;
  onAsk: (question?: string) => void;
  t: Translation;
}

export function ChatPanel({
  turns,
  question,
  canAsk,
  asking,
  progressLabel,
  onQuestionChange,
  onAsk,
  t,
}: ChatPanelProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (canAsk && question.trim() && !asking) {
        onAsk();
      }
    }
  };

  return (
    <main className="chat-panel" aria-label={t.chat.title}>
      <div className="chat-heading">
        <div>
          <span className="eyebrow">{t.chat.workspace}</span>
          <h1>{t.chat.title}</h1>
        </div>
        <div className="retrieval-label">
          <FileSearch size={15} aria-hidden="true" />
          {t.chat.grounded}
        </div>
      </div>

      <div className="conversation" aria-live="polite">
        {turns.length === 0 && (
          <div className="empty-conversation">
            <div className="empty-mark" aria-hidden="true">
              <MessageSquareText size={26} />
            </div>
            <h2>{t.chat.start}</h2>
            <div className="suggestion-list">
              {t.chat.suggestions.map((suggestion) => (
                <button
                  type="button"
                  key={suggestion}
                  onClick={() => onAsk(suggestion)}
                  disabled={!canAsk || asking}
                >
                  {suggestion}
                  <ArrowUp size={15} aria-hidden="true" />
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn) => (
          <article className="turn" key={turn.id}>
            <div className="user-message">
              <span>{t.chat.you}</span>
              <p>{turn.question}</p>
            </div>

            <div className="assistant-message">
              <div className="assistant-label">
                <span className="assistant-avatar">PA</span>
                <strong>{t.chat.agent}</strong>
              </div>

              {turn.pending && (
                <div className="answer-loading">
                  <LoaderCircle className="spin" size={18} aria-hidden="true" />
                  {progressLabel ?? t.chat.running}
                </div>
              )}

              {turn.error && (
                <div className="answer-error">
                  <AlertCircle size={18} aria-hidden="true" />
                  {turn.error}
                </div>
              )}

              {turn.result && (
                <>
                  <div className="markdown-answer">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        a: ({ children, ...props }) => (
                          <a {...props} target="_blank" rel="noreferrer">
                            {children}
                          </a>
                        ),
                      }}
                    >
                      {turn.result.answer}
                    </ReactMarkdown>
                  </div>

                  {turn.result.sources.length > 0 && (
                    <div className="sources-block">
                      <div className="sources-title">
                        <BookOpen size={16} aria-hidden="true" />
                        {t.chat.sources}
                      </div>
                      {turn.result.sources.map((source) => (
                        <details className="source-item" key={source.citation_id}>
                          <summary>
                            <span>{source.source}</span>
                            <strong>
                              {t.chat.page} {source.page}
                            </strong>
                          </summary>
                          <p>{source.excerpt}</p>
                        </details>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </article>
        ))}
        <div ref={endRef} />
      </div>

      <div className="composer-wrap">
        <div className={`composer${canAsk ? "" : " disabled"}`}>
          <textarea
            value={question}
            onChange={(event) => onQuestionChange(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              canAsk ? t.chat.askPlaceholder : t.chat.addPdfPlaceholder
            }
            rows={1}
            disabled={!canAsk || asking}
            aria-label="Question"
          />
          <button
            className="send-button"
            type="button"
            onClick={() => onAsk()}
            disabled={!canAsk || !question.trim() || asking}
            title={t.chat.send}
            aria-label={t.chat.send}
          >
            {asking ? (
              <LoaderCircle className="spin" size={18} />
            ) : (
              <ArrowUp size={19} />
            )}
          </button>
        </div>
      </div>
    </main>
  );
}
