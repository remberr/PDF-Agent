import { useEffect, useMemo, useRef, useState } from "react";
import {
  Copy,
  FileStack,
  GitBranch,
  MessageSquareText,
  Plus,
  ScanText,
} from "lucide-react";

import {
  askQuestionStream,
  checkHealth,
  createSession,
  getSession,
  uploadPdfs,
} from "./api";
import { ChatPanel } from "./components/ChatPanel";
import { DocumentsPanel } from "./components/DocumentsPanel";
import { WorkflowPanel } from "./components/WorkflowPanel";
import { translations, type Translation } from "./i18n";
import type {
  AskResponse,
  BackendStatus,
  ConversationTurn,
  Language,
  MobileView,
  SessionDetail,
  WorkflowProgress,
} from "./types";

const SESSION_STORAGE_KEY = "pdf-agent-session";
const LANGUAGE_STORAGE_KEY = "pdf-agent-language";
const conversationKey = (sessionId: string) =>
  `pdf-agent-conversation-${sessionId}`;

function localizedError(
  error: unknown,
  t: Translation,
  fallback: string,
): string {
  if (!(error instanceof Error)) {
    return fallback;
  }

  if (error.message === "Cannot reach the PDF Agent API.") {
    return t.errors.apiUnavailable;
  }
  if (error.message.startsWith("Only PDF files are supported")) {
    return t.errors.pdfOnly;
  }
  if (error.message.startsWith("Please upload at least one PDF")) {
    return t.errors.addPdfFirst;
  }

  return error.message || fallback;
}

function readConversation(sessionId: string): ConversationTurn[] {
  try {
    const value = localStorage.getItem(conversationKey(sessionId));
    const parsed = value ? (JSON.parse(value) as ConversationTurn[]) : [];
    return Array.isArray(parsed)
      ? parsed.map((turn) => ({
          ...turn,
          pending: false,
          result: turn.result
            ? { ...turn.result, timings: turn.result.timings ?? {} }
            : undefined,
        }))
      : [];
  } catch {
    return [];
  }
}

function emptySession(sessionId: string): SessionDetail {
  return {
    session_id: sessionId,
    loaded_pdfs: [],
    message_count: 0,
    has_vectorstore: false,
    total_documents: 0,
  };
}

function App() {
  const bootstrapStarted = useRef(false);
  const [backendStatus, setBackendStatus] =
    useState<BackendStatus>("checking");
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [conversationReady, setConversationReady] = useState(false);
  const [question, setQuestion] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [asking, setAsking] = useState(false);
  const [workflowProgress, setWorkflowProgress] =
    useState<WorkflowProgress>();
  const [mobileView, setMobileView] = useState<MobileView>("chat");
  const [copied, setCopied] = useState(false);
  const [language, setLanguage] = useState<Language>(() =>
    localStorage.getItem(LANGUAGE_STORAGE_KEY) === "zh" ? "zh" : "en",
  );
  const t = translations[language];

  useEffect(() => {
    if (bootstrapStarted.current) {
      return;
    }
    bootstrapStarted.current = true;

    const bootstrap = async () => {
      try {
        await checkHealth();
        setBackendStatus("online");
      } catch {
        setBackendStatus("offline");
      }

      const storedSessionId = localStorage.getItem(SESSION_STORAGE_KEY);
      if (storedSessionId) {
        try {
          const restoredSession = await getSession(storedSessionId);
          setSession(restoredSession);
          setTurns(readConversation(storedSessionId));
          setConversationReady(true);
          return;
        } catch {
          localStorage.removeItem(SESSION_STORAGE_KEY);
        }
      }

      try {
        const created = await createSession();
        localStorage.setItem(SESSION_STORAGE_KEY, created.session_id);
        setSession(emptySession(created.session_id));
        setTurns([]);
      } catch {
        setBackendStatus("offline");
      } finally {
        setConversationReady(true);
      }
    };

    void bootstrap();
  }, []);

  useEffect(() => {
    if (session && conversationReady) {
      localStorage.setItem(
        conversationKey(session.session_id),
        JSON.stringify(turns),
      );
    }
  }, [conversationReady, session, turns]);

  useEffect(() => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  }, [language]);

  const latestResult = useMemo<AskResponse | undefined>(() => {
    for (let index = turns.length - 1; index >= 0; index -= 1) {
      if (turns[index].result) {
        return turns[index].result;
      }
    }
    return undefined;
  }, [turns]);

  const progressLabel = useMemo(() => {
    if (!workflowProgress) {
      return undefined;
    }

    const nodeNames: Record<string, string> = {
      planner: t.workflow.planner,
      specialists: t.workflow.specialists,
      controller: t.workflow.controller,
      collaboration: t.workflow.collaboration,
      revision: t.workflow.revision,
      reviewer: t.workflow.reviewer,
    };
    const nodeName = nodeNames[workflowProgress.node] ?? t.workflow.title;
    const status =
      t.workflow.statuses[workflowProgress.status] ?? workflowProgress.status;
    return `${nodeName} · ${status}`;
  }, [t, workflowProgress]);

  const handleNewSession = async () => {
    if (turns.length > 0 && !window.confirm(t.session.confirmNew)) {
      return;
    }

    setUploadError("");
    setQuestion("");
    setWorkflowProgress(undefined);
    try {
      const created = await createSession();
      localStorage.setItem(SESSION_STORAGE_KEY, created.session_id);
      setSession(emptySession(created.session_id));
      setTurns([]);
      setBackendStatus("online");
      setMobileView("documents");
    } catch (error) {
      setBackendStatus("offline");
      setUploadError(localizedError(error, t, t.errors.createSession));
    }
  };

  const handleUpload = async (files: File[]) => {
    if (!session || files.length === 0) {
      return;
    }

    setUploading(true);
    setUploadError("");
    setWorkflowProgress(undefined);
    try {
      const response = await uploadPdfs(session.session_id, files);
      setSession((current) =>
        current
          ? {
              ...current,
              loaded_pdfs: response.loaded_pdfs,
              total_documents: response.total_documents,
              has_vectorstore: true,
            }
          : current,
      );
      setBackendStatus("online");
      setMobileView("chat");
    } catch (error) {
      setUploadError(localizedError(error, t, t.errors.uploadFailed));
    } finally {
      setUploading(false);
    }
  };

  const handleAsk = async (suggestedQuestion?: string) => {
    if (!session || !session.has_vectorstore || asking) {
      return;
    }

    const submittedQuestion = (suggestedQuestion ?? question).trim();
    if (!submittedQuestion) {
      return;
    }

    const turnId = crypto.randomUUID();
    const pendingTurn: ConversationTurn = {
      id: turnId,
      question: submittedQuestion,
      pending: true,
    };

    setQuestion("");
    setAsking(true);
    setWorkflowProgress(undefined);
    setTurns((current) => [...current, pendingTurn]);

    try {
      const result = await askQuestionStream(
        session.session_id,
        submittedQuestion,
        setWorkflowProgress,
      );
      setTurns((current) =>
        current.map((turn) =>
          turn.id === turnId ? { ...turn, result, pending: false } : turn,
        ),
      );
      setSession((current) =>
        current
          ? { ...current, message_count: current.message_count + 2 }
          : current,
      );
      setBackendStatus("online");
    } catch (error) {
      setTurns((current) =>
        current.map((turn) =>
          turn.id === turnId
            ? {
                ...turn,
                pending: false,
                error: localizedError(error, t, t.errors.analysisFailed),
              }
            : turn,
        ),
      );
    } finally {
      setAsking(false);
    }
  };

  const copySessionId = async () => {
    if (!session) {
      return;
    }
    await navigator.clipboard.writeText(session.session_id);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <ScanText size={21} />
          </div>
          <div>
            <strong>PDF Agent</strong>
            <span>{t.brandSubtitle}</span>
          </div>
        </div>

        <div className="header-actions">
          <div className={`backend-status ${backendStatus}`}>
            <span className="status-dot" />
            {backendStatus === "online"
              ? t.api.online
              : backendStatus === "offline"
                ? t.api.offline
                : t.api.connecting}
          </div>

          <div className="language-switch" aria-label={t.languageLabel}>
            <button
              type="button"
              className={language === "zh" ? "active" : ""}
              onClick={() => setLanguage("zh")}
              aria-pressed={language === "zh"}
            >
              中
            </button>
            <button
              type="button"
              className={language === "en" ? "active" : ""}
              onClick={() => setLanguage("en")}
              aria-pressed={language === "en"}
            >
              EN
            </button>
          </div>

          {session && (
            <button
              className="session-button"
              type="button"
              onClick={copySessionId}
              title={t.session.copy}
            >
              <span>
                {copied
                  ? t.session.copied
                  : `${t.session.label} ${session.session_id.slice(0, 8)}`}
              </span>
              <Copy size={14} aria-hidden="true" />
            </button>
          )}

          <button
            className="icon-button"
            type="button"
            onClick={handleNewSession}
            title={t.session.new}
            aria-label={t.session.new}
          >
            <Plus size={19} />
          </button>
        </div>
      </header>

      <nav className="mobile-tabs" aria-label={t.nav.label}>
        <button
          className={mobileView === "documents" ? "active" : ""}
          type="button"
          onClick={() => setMobileView("documents")}
        >
          <FileStack size={17} />
          {t.nav.documents}
        </button>
        <button
          className={mobileView === "chat" ? "active" : ""}
          type="button"
          onClick={() => setMobileView("chat")}
        >
          <MessageSquareText size={17} />
          {t.nav.analysis}
        </button>
        <button
          className={mobileView === "workflow" ? "active" : ""}
          type="button"
          onClick={() => setMobileView("workflow")}
        >
          <GitBranch size={17} />
          {t.nav.workflow}
        </button>
      </nav>

      <div className="workspace">
        <div className={mobileView === "documents" ? "mobile-active" : ""}>
          <DocumentsPanel
            session={session}
            uploading={uploading}
            uploadError={uploadError}
            onUpload={handleUpload}
            t={t}
          />
        </div>
        <div className={mobileView === "chat" ? "mobile-active" : ""}>
          <ChatPanel
            turns={turns}
            question={question}
            canAsk={Boolean(session?.has_vectorstore)}
            asking={asking}
            progressLabel={progressLabel}
            onQuestionChange={setQuestion}
            onAsk={handleAsk}
            t={t}
          />
        </div>
        <div className={mobileView === "workflow" ? "mobile-active" : ""}>
          <WorkflowPanel
            result={asking ? undefined : latestResult}
            progress={workflowProgress}
            t={t}
          />
        </div>
      </div>
    </div>
  );
}

export default App;
