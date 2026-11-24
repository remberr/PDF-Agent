import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { WorkflowPanel } from '../src/components/WorkflowPanel.tsx';
import { translations } from '../src/i18n.ts';
import type { AskResponse } from '../src/types.ts';

function response(): AskResponse {
  return {answer:'answer',steps:['qa'],sources:[],collaboration_notes:{},revision_count:0,timings:{},
    usage:{llm_calls:0,input_tokens:0,output_tokens:0,total_tokens:0,cache_hit_tokens:0,cache_miss_tokens:0,
      estimated_cost_usd:0,cache_hit_rate:0,currency:'USD',cost_estimate_available:false,pricing_tiers:[],by_model:{},by_operation:{}}};
}
test('legacy result does not imply every workflow node completed', () => {
  const html = renderToStaticMarkup(createElement(WorkflowPanel, {result:response(), language:'en', t:translations.en}));
  assert.ok(!html.includes('workflow-node final-node complete'));
  assert.ok(html.includes('Unconfirmed'));
});
test('failed and degraded outcomes render accurately in both languages', () => {
  for (const language of ['en','zh'] as const) {
    const result = response();
    result.execution = {status:'failed',generation_status:'degraded',reason:'persistence_failed',persistence:'failed',
      node_statuses:{reviewer:{status:'degraded',reason:'model_unavailable'}}};
    const html = renderToStaticMarkup(createElement(WorkflowPanel, {result,language,t:translations[language]}));
    assert.ok(html.includes('workflow-node final-node degraded'));
    assert.ok(html.includes(translations[language].workflow.statuses.degraded));
    assert.ok(html.includes(translations[language].errors.generatedNotSaved));
    assert.ok(!html.includes(translations[language].workflow.answerDelivered));
  }
});
