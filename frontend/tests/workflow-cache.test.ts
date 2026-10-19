import assert from "node:assert/strict";
import test from "node:test";
import { formatCacheHit, formatEstimatedCost } from "../src/utils/usage.ts";

const labels = { cacheUnavailable: "统计不可用", noLlmCalls: "无 LLM 调用" };
const base = {
  llm_calls: 1, input_tokens: 100, output_tokens: 10, total_tokens: 110,
  cache_hit_tokens: 0, cache_miss_tokens: 100, estimated_cost_usd: 0,
  cache_hit_rate: 0, cache_status: "available" as const,
  cache_usage_available: true, cache_unavailable_calls: 0,
};

test("real zero, missing statistics and no calls have distinct labels", () => {
  assert.equal(formatCacheHit(base, labels), "0%");
  assert.equal(formatCacheHit({ ...base, cache_usage_available: false }, labels), "统计不可用");
  assert.equal(formatCacheHit({ ...base, llm_calls: 0 }, labels), "无 LLM 调用");
});

test("partial and legacy statistics never pretend to be zero", () => {
  assert.equal(formatCacheHit({ ...base, cache_unavailable_calls: 1 }, labels), "统计不可用");
  assert.equal(formatCacheHit({ ...base, cache_status: undefined }, labels), "统计不可用");
  assert.equal(formatCacheHit({ ...base, input_tokens: 0 }, labels), "统计不可用");
  for (const cache_hit_rate of [NaN, Infinity, -1, 1.1, undefined]) {
    assert.equal(formatCacheHit({ ...base, cache_hit_rate }, labels), "统计不可用");
  }
});

test("positive low cache hit rates are not rounded down to zero", () => {
  assert.equal(formatCacheHit({ ...base, cache_hit_rate: .25 }, labels), "25%");
  assert.equal(formatCacheHit({ ...base, cache_hit_rate: .0001 }, labels), "0.01%");
  assert.equal(formatCacheHit({ ...base, cache_hit_rate: .000001 }, labels), "<0.01%");
});

test("language switches between independently computed official costs", () => {
  const usage = { ...base, estimated_cost_usd: .0003906, estimated_cost_cny: .002604,
    cost_estimate_available: true, cost_estimate_cny_available: true };
  const snapshot = JSON.stringify(usage);
  assert.equal(formatEstimatedCost(usage, "zh", "不可估算"), "¥0.002604");
  assert.equal(formatEstimatedCost(usage, "en", "Unavailable"), "$0.000391");
  assert.equal(formatEstimatedCost(usage, "zh", "不可估算"), "¥0.002604");
  assert.equal(JSON.stringify(usage), snapshot);
});

test("old results do not convert dollars or pretend CNY is free", () => {
  assert.equal(formatEstimatedCost({ ...base, cost_estimate_available: true }, "en", "Unavailable"), "$0.000000");
  assert.equal(formatEstimatedCost({ ...base, cost_estimate_available: true }, "zh", "不可估算"), "不可估算");
  assert.equal(formatEstimatedCost({ ...base, estimated_cost_cny: 0, cost_estimate_cny_available: true }, "zh", "不可估算"), "¥0.000000");
});

test("total and per-operation currency availability is independent", () => {
  const usage = { ...base, estimated_cost_cny: .004, cost_estimate_cny_available: true,
    cost_estimate_available: false };
  assert.equal(formatEstimatedCost(usage, "zh", "不可估算"), "¥0.004000");
  assert.equal(formatEstimatedCost(usage, "en", "Unavailable"), "Unavailable");
  for (const estimated_cost_cny of [null, NaN, Infinity, -1]) {
    assert.equal(formatEstimatedCost({ ...usage, estimated_cost_cny }, "zh", "不可估算"), "不可估算");
  }
});
