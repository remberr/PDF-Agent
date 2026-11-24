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
  ApiError,
  askQuestionStream,
  checkHealth,
  createSession,
  deleteSession,
  getSession,
  uploadPdfs,
} from "./api";
import { RequestScope, readConversation, safeStorage } from './requestScope';
import { executionNotice } from './utils/execution';
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

const SESSION_STORAGE_KEY = "pdf-agent-session-v2";
const LANGUAGE_STORAGE_KEY = "pdf-agent-language";
const conversationKey = (sessionId: string) =>
  `pdf-agent-conversation-${sessionId}`;

async function openSession(signal: AbortSignal): Promise<SessionDetail> {
  const created = await createSession(signal);
  // Confirm the browser retained the server-issued cookie before storing the locator.
  return getSession(created.session_id, signal);
}

function localizedError(
  error: unknown,
  t: Translation,
  fallback: string,
): string {
  if (!(error instanceof Error)) {
    return fallback;
  }

  if (error.name === 'AbortError') return t.errors.cancelled;
  if (error.message.startsWith('Invalid ')) return t.errors.invalidResponse;
  if (error.message === 'The workflow ended without a complete result.') return t.errors.streamInterrupted;
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
  const requests = useRef(new RequestScope());
  const [storageWarning, setStorageWarning] = useState(false);
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
    safeStorage('get', LANGUAGE_STORAGE_KEY) === "zh" ? "zh" : "en",
  );
  const t = translations[language];

  useEffect(() => {
    const scope = requests.current;
    const lease = scope.start('bootstrap');
    const current = () => scope.isCurrent(lease);
    const bootstrap = async () => {
      try { await checkHealth(lease.signal); if (current()) setBackendStatus('online'); }
      catch { if (current()) setBackendStatus('offline'); }
      if (!current()) return;
      const stored = safeStorage('get', SESSION_STORAGE_KEY);
      if (typeof stored === 'string' && /^[a-f0-9]{32}$/.test(stored)) {
        try {
          const restored = await getSession(stored, lease.signal);
          if (!current()) return;
          setSession(restored); setTurns(readConversation(stored));
          return;
        } catch (error) {
          if (!current()) return;
          if (!(error instanceof ApiError) || error.status !== 404) {
            // Preserve the session and cached turns on transport/temporary errors.
            setSession(emptySession(stored)); setTurns(readConversation(stored));
            setBackendStatus('offline'); setUploadError(translations[language].errors.apiUnavailable);
            return;
          }
          if (safeStorage('get', SESSION_STORAGE_KEY) === stored) safeStorage('remove', SESSION_STORAGE_KEY);
          setUploadError(translations[language].errors.sessionUnavailable);
          return;
        }
      }
      try {
        const created = await openSession(lease.signal);
        if (!current()) return;
        if (safeStorage('set', SESSION_STORAGE_KEY, created.session_id) === false) setStorageWarning(true);
        setSession(created); setTurns([]);
      } catch (error) {
        if (!current()) return;
        setBackendStatus('offline');
        setUploadError(error instanceof ApiError && [403, 404].includes(error.status)
          ? translations[language].errors.cookieUnavailable : translations[language].errors.createSession);
      }
    };
    void bootstrap().finally(() => { if (current()) setConversationReady(true); scope.finish(lease); });
    return () => scope.invalidate();
  }, []);

  useEffect(() => {
    if (session && conversationReady && safeStorage('set', conversationKey(session.session_id), JSON.stringify(turns)) === false) {
      setStorageWarning(true);
    }
  }, [conversationReady, session, turns]);

  useEffect(() => {
    if (safeStorage('set', LANGUAGE_STORAGE_KEY, language) === false) setStorageWarning(true);
    document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
  }, [language]);

  const latestResult = useMemo<AskResponse | undefined>(() => turns.at(-1)?.result, [turns]);

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

  const cancelAsk = () => {
    requests.current.cancel('ask');
    setAsking(false);
    setTurns(current => current.map(turn => turn.pending ? {...turn, pending: false, error: t.errors.cancelled} : turn));
    setWorkflowProgress(current => current ? {...current, status: 'failed', node_statuses: {
      ...current.node_statuses, [current.node]: {status: 'cancelled', reason: 'cancelled'},
    }} : current);
  };

  const loseSession = (sessionId: string) => {
    requests.current.invalidate();
    if (safeStorage('get', SESSION_STORAGE_KEY) === sessionId
      && safeStorage('remove', SESSION_STORAGE_KEY) === false) setStorageWarning(true);
    setSession(null); setTurns([]); setQuestion(''); setWorkflowProgress(undefined);
    setUploading(false); setAsking(false); setUploadError(t.errors.sessionUnavailable);
  };

  const handleNewSession = async () => {
    const scope = requests.current;
    if (scope.has('session-change') || scope.has('bootstrap')) return;
    if ((turns.length > 0 || session?.loaded_pdfs.length || session?.message_count)
      && !window.confirm(t.session.confirmNew)) return;
    scope.invalidate(); cancelAsk();
    setUploading(false); setUploadError(''); setQuestion(''); setWorkflowProgress(undefined);
    const lease = scope.start('session-change');
    try {
      const previousSessionId = session?.session_id;
      const created = await openSession(lease.signal);
      if (!scope.isCurrent(lease)) return;
      let previousDeletionFailed = false;
      if (previousSessionId) {
        try { await deleteSession(previousSessionId, lease.signal); }
        catch { previousDeletionFailed = true; }
        if (!scope.isCurrent(lease)) return;
        if (safeStorage('remove', conversationKey(previousSessionId)) === false) setStorageWarning(true);
      }
      if (safeStorage('set', SESSION_STORAGE_KEY, created.session_id) === false) setStorageWarning(true);
      setSession(created); setTurns([]);
      if (previousDeletionFailed) setUploadError(t.errors.previousDeletionUnconfirmed);
      setBackendStatus('online'); setMobileView('documents'); setConversationReady(true);
    } catch (error) {
      if (scope.isCurrent(lease)) {
        setBackendStatus('offline');
        setUploadError(error instanceof ApiError && [403, 404].includes(error.status)
          ? t.errors.cookieUnavailable : localizedError(error, t, t.errors.createSession));
      }
    } finally { scope.finish(lease); }
  };

  const retrySession = async () => {
    if (!session) return;
    const scope = requests.current;
    if (scope.has('ask') || scope.has('upload') || scope.has('session-change')) return;
    const lease = scope.start('restore', session.session_id);
    try {
      const restored = await getSession(lease.sessionId, lease.signal);
      if (!scope.isCurrent(lease)) return;
      setSession(current => current?.session_id === lease.sessionId ? restored : current);
      setBackendStatus('online'); setUploadError('');
    } catch (error) {
      if (!scope.isCurrent(lease)) return;
      if (error instanceof ApiError && error.status === 404) loseSession(lease.sessionId);
      else setUploadError(localizedError(error, t, t.errors.apiUnavailable));
    } finally { scope.finish(lease); }
  };

  const handleUpload = async (files: File[]) => {
    const scope = requests.current;
    if (!session || !files.length || scope.has('upload') || scope.has('ask') || scope.has('session-change')) return;
    scope.cancel('restore');
    const lease = scope.start('upload', session.session_id);
    setUploading(true); setUploadError(''); setWorkflowProgress(undefined);
    try {
      const response = await uploadPdfs(lease.sessionId, files, lease.signal);
      if (!scope.isCurrent(lease)) return;
      if (response.session_id !== lease.sessionId) throw new Error('Invalid upload response.');
      setSession(current => current?.session_id === lease.sessionId ? {...current,
        loaded_pdfs: response.loaded_pdfs, total_documents: response.total_documents, has_vectorstore: true} : current);
      setBackendStatus('online'); setMobileView('chat');
    } catch (error) {
      if (!scope.isCurrent(lease)) return;
      if (error instanceof ApiError && error.status === 404) loseSession(lease.sessionId);
      else setUploadError(localizedError(error, t, t.errors.uploadFailed));
    }
    finally { if (scope.isCurrent(lease)) setUploading(false); scope.finish(lease); }
  };

  const handleAsk = async (suggestedQuestion?: string) => {
    const scope = requests.current;
    if (!session?.has_vectorstore || scope.has('ask') || scope.has('upload') || scope.has('session-change')) return;
    scope.cancel('restore');
    const submittedQuestion = (suggestedQuestion ?? question).trim();
    if (!submittedQuestion) return;
    const lease = scope.start('ask', session.session_id);
    const turnId = crypto.randomUUID();
    setQuestion(''); setAsking(true); setWorkflowProgress(undefined);
    setTurns(current => [...current, {id: turnId, question: submittedQuestion, pending: true}]);
    try {
      const result = await askQuestionStream(lease.sessionId, submittedQuestion,
        progress => { if (scope.isCurrent(lease)) setWorkflowProgress(progress); }, lease.signal);
      if (!scope.isCurrent(lease)) return;
      setTurns(current => current.map(turn => turn.id === turnId ? {
        ...turn, result, pending: false, error: executionNotice(result, t) || undefined,
      } : turn));
      if (result.execution?.persistence === 'saved') {
        setSession(current => current?.session_id === lease.sessionId ? {...current, message_count: current.message_count + 2} : current);
      }
      setBackendStatus('online');
    } catch (error) {
      if (!scope.isCurrent(lease)) return;
      if (error instanceof ApiError && error.status === 404) {
        loseSession(lease.sessionId);
        return;
      }
      setTurns(current => current.map(turn => turn.id === turnId ? {...turn, pending: false,
        error: localizedError(error, t, t.errors.analysisFailed)} : turn));
      setWorkflowProgress(current => current ? {...current, status: 'failed', node_statuses: {
        ...current.node_statuses, [current.node]: {status: 'failed', reason: 'transport_interrupted'},
      }} : current);
    } finally { if (scope.isCurrent(lease)) setAsking(false); scope.finish(lease); }
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

      {storageWarning && <p role="alert">{t.errors.storageUnavailable}</p>}
      {!session && uploadError && <p role="alert">{uploadError}</p>}
      {backendStatus === 'offline' && session && <button type="button" onClick={retrySession}>{t.session.retryRestore}</button>}
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
            uploadError={session ? uploadError : ''}
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
            onCancel={cancelAsk}
            t={t}
          />
        </div>
        <div className={mobileView === "workflow" ? "mobile-active" : ""}>
          <WorkflowPanel
            language={language}
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
