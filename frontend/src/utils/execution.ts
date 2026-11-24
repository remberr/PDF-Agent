import type { AskResponse } from '../types';
import type { Translation } from '../i18n';

export function executionNotice(result: AskResponse, t: Translation): string {
  const execution = result.execution;
  if (!execution) return t.errors.executionUnknown;
  if (execution.persistence === 'failed') return t.errors.generatedNotSaved;
  if (execution.status === 'cancelled') return t.errors.cancelled;
  if (execution.status === 'degraded') return t.errors.degraded;
  if (execution.status === 'failed') return t.errors.analysisFailed;
  return '';
}
