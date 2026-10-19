import {
  Check,
  CircleDot,
  GitBranch,
  LoaderCircle,
  RotateCw,
  SearchCheck,
  ShieldCheck,
  Users,
} from "lucide-react";
import type { ReactNode } from "react";

import type { Translation } from "../i18n";
import type { AskResponse, Language, WorkflowProgress } from "../types";
import { formatCacheHit, formatEstimatedCost } from "../utils/usage";

interface WorkflowPanelProps {
  result?: AskResponse;
  progress?: WorkflowProgress;
  t: Translation;
  language: Language;
}

function NoteList({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) {
    return null;
  }

  return (
    <div className="note-group">
      <strong>{title}</strong>
      {items.map((item, index) => (
        <p key={`${title}-${index}`}>{item}</p>
      ))}
    </div>
  );
}

function formatDuration(milliseconds?: number): string {
  if (milliseconds === undefined) {
    return "--";
  }

  if (milliseconds < 1000) {
    return `${Math.round(milliseconds)} ms`;
  }

  return `${(milliseconds / 1000).toFixed(2)} s`;
}

export function WorkflowPanel({ result, progress, t, language }: WorkflowPanelProps) {
  const notes = result?.collaboration_notes;
  const steps = result?.steps ?? progress?.steps ?? [];
  const timings = result?.timings ?? progress?.timings ?? {};
  const usage = result?.usage ?? progress?.usage;
  const collaborationStatus = notes?.status ?? "waiting";
  const collaborationLabel =
    t.workflow.statuses[collaborationStatus] ?? collaborationStatus;
  const completedNodes = progress?.completed_nodes ?? [];

  const nodeState = (node: string): string => {
    if (progress?.node === node && progress.status === "running") {
      return "running";
    }
    if (progress?.node === node && progress.status === "failed") {
      return "failed";
    }
    if (completedNodes.includes(node)) {
      return "complete";
    }
    if (result) {
      if (node === "collaboration" && result.steps.length <= 1) {
        return "skipped";
      }
      return "complete";
    }
    return "";
  };

  const nodeStatus = (node: string, completedLabel: string): string => {
    const state = nodeState(node);
    if (state === "running") {
      return t.workflow.statuses.running;
    }
    if (state === "failed") {
      return t.workflow.statuses.failed;
    }
    if (state === "complete") {
      return completedLabel;
    }
    if (state === "skipped") {
      return t.workflow.statuses.skipped;
    }
    return t.workflow.waiting;
  };

  const nodeIcon = (node: string, fallback: ReactNode) => {
    const state = nodeState(node);
    if (state === "running") {
      return <LoaderCircle className="spin" size={15} />;
    }
    if (state === "complete") {
      return <Check size={15} />;
    }
    return fallback;
  };

  const showRevision = steps.length > 1;
  const hasTrace = Boolean(result || progress);
  const timingOrder = [
    "planner",
    ...steps,
    "specialists",
    "collaboration",
    "revision",
    "reviewer",
    "total",
  ];
  const timingEntries = timingOrder
    .filter((key, index) => timingOrder.indexOf(key) === index)
    .filter((key) => timings[key] !== undefined);

  const timingLabel = (key: string): string => {
    const labels: Record<string, string> = {
      planner: t.workflow.planner,
      specialists: t.workflow.specialists,
      collaboration: t.workflow.collaboration,
      revision: t.workflow.revision,
      reviewer: t.workflow.reviewer,
      total: t.workflow.total,
    };
    return labels[key] ?? t.workflow.steps[key] ?? key;
  };

  return (
    <aside className="panel workflow-panel" aria-label={t.workflow.title}>
      <div className="panel-heading workflow-heading">
        <div>
          <span className="eyebrow">{t.workflow.trace}</span>
          <h2>{t.workflow.title}</h2>
        </div>
        <GitBranch size={19} aria-hidden="true" />
      </div>

      <div className="workflow-rail">
        <div className={`workflow-node ${nodeState("planner")}`}>
          <div className="node-icon">
            {nodeIcon("planner", <CircleDot size={15} />)}
          </div>
          <div>
            <strong>{t.workflow.planner}</strong>
            <span>
              {nodeStatus("planner", t.workflow.routeSelected)}
            </span>
          </div>
        </div>

        <div className={`workflow-node ${nodeState("specialists")}`}>
          <div className="node-icon">
            {nodeIcon("specialists", <SearchCheck size={15} />)}
          </div>
          <div>
            <strong>{t.workflow.specialists}</strong>
            {steps.length > 0 ? (
              <div className="agent-tags">
                {steps.map((step) => (
                  <span key={step}>{t.workflow.steps[step] ?? step}</span>
                ))}
              </div>
            ) : (
              <span>{t.workflow.waiting}</span>
            )}
          </div>
        </div>

        <div className={`workflow-node ${nodeState("collaboration")}`}>
          <div className="node-icon">
            {nodeIcon("collaboration", <Users size={15} />)}
          </div>
          <div>
            <strong>{t.workflow.collaboration}</strong>
            <span className={`status-text ${collaborationStatus}`}>
              {result
                ? collaborationLabel
                : nodeStatus("collaboration", t.workflow.statuses.completed)}
            </span>
          </div>
        </div>

        {showRevision && (
          <div
            className={`workflow-node revision-node ${nodeState("revision")}`}
          >
            <div className="node-icon">
              {nodeIcon("revision", <RotateCw size={15} />)}
            </div>
            <div>
              <strong>{t.workflow.revision}</strong>
              <span>
                {result
                  ? `${result.revision_count} ${t.workflow.retry}`
                  : nodeStatus("revision", t.workflow.statuses.completed)}
              </span>
            </div>
          </div>
        )}

        <div
          className={`workflow-node final-node ${nodeState("reviewer")}`}
        >
          <div className="node-icon">
            {nodeIcon("reviewer", <ShieldCheck size={15} />)}
          </div>
          <div>
            <strong>{t.workflow.reviewer}</strong>
            <span>{nodeStatus("reviewer", t.workflow.answerDelivered)}</span>
          </div>
        </div>
      </div>

      {hasTrace && (
        <div className="workflow-summary">
          <div className="trace-metrics">
            <div>
              <span>{t.workflow.agents}</span>
              <strong>{steps.length}</strong>
            </div>
            <div>
              <span>{t.workflow.sources}</span>
              <strong>{result?.sources.length ?? 0}</strong>
            </div>
            <div>
              <span>{t.workflow.retries}</span>
              <strong>{result?.revision_count ?? progress?.revision_count ?? 0}</strong>
            </div>
            <div>
              <span>{t.workflow.total}</span>
              <strong>{formatDuration(timings.total)}</strong>
            </div>
          </div>

          {timingEntries.length > 0 && (
            <div className="timing-list">
              <strong>{t.workflow.runtime}</strong>
              {timingEntries.map((key) => (
                <div key={key}>
                  <span>{timingLabel(key)}</span>
                  <time>{formatDuration(timings[key])}</time>
                </div>
              ))}
            </div>
          )}

          {usage && (
            <div className="usage-observability">
              <strong>{t.workflow.usage}</strong>
              <div className="usage-metrics">
                <div>
                  <span>{t.workflow.calls}</span>
                  <strong>{usage.llm_calls}</strong>
                </div>
                <div>
                  <span>{t.workflow.tokens}</span>
                  <strong>{usage.total_tokens.toLocaleString()}</strong>
                </div>
                <div>
                  <span>{t.workflow.cacheHit}</span>
                  <strong>{formatCacheHit(usage, t.workflow)}</strong>
                </div>
                <div>
                  <span>{t.workflow.estimatedCost}</span>
                  <strong>
                    {formatEstimatedCost(usage, language, t.workflow.unavailable)}
                  </strong>
                </div>
              </div>

              {Object.keys(usage.by_operation).length > 0 && (
                <div className="usage-operation-list">
                  <strong>{t.workflow.operations}</strong>
                  {Object.entries(usage.by_operation).map(
                    ([operation, item]) => (
                      <div key={operation}>
                        <span>
                          {t.workflow.usageOperations[operation] ?? operation}
                        </span>
                        <span>{item.total_tokens.toLocaleString()} tok</span>
                        <strong>
                          {formatEstimatedCost(item, language, t.workflow.unavailable)}
                        </strong>
                      </div>
                    ),
                  )}
                </div>
              )}
            </div>
          )}

          <NoteList title={t.workflow.issues} items={notes?.issues} />
          <NoteList
            title={t.workflow.missingInformation}
            items={notes?.missing_information}
          />
          <NoteList
            title={t.workflow.recommendations}
            items={notes?.recommendations}
          />
          <NoteList
            title={t.workflow.requestedSteps}
            items={notes?.next_steps}
          />
        </div>
      )}
    </aside>
  );
}
