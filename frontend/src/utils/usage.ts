import type { Language, UsageBreakdown } from "../types";

export function formatEstimatedCost(usage: UsageBreakdown, language: Language, unavailable: string): string {
  const cost = language === "zh" ? usage.estimated_cost_cny : usage.estimated_cost_usd;
  const available = language === "zh" ? usage.cost_estimate_cny_available : usage.cost_estimate_available;
  if (available !== true || typeof cost !== "number" || !Number.isFinite(cost) || cost < 0) {
    return unavailable;
  }
  const symbol = language === "zh" ? "¥" : "$";
  if (cost > 0 && cost < 0.000001) {
    return `<${symbol}0.000001`;
  }
  return `${symbol}${cost.toFixed(cost < 0.01 ? 6 : 4)}`;
}

export function formatCacheHit(
  usage: UsageBreakdown,
  labels: { cacheUnavailable: string; noLlmCalls: string },
): string {
  if (usage.llm_calls === 0) {
    return labels.noLlmCalls;
  }

  const rate = usage.cache_hit_rate;
  if (
    usage.cache_usage_available !== true ||
    usage.cache_status !== "available" ||
    (usage.cache_unavailable_calls ?? 0) > 0 ||
    usage.input_tokens <= 0 ||
    typeof rate !== "number" ||
    !Number.isFinite(rate) ||
    rate < 0 || rate > 1
  ) {
    return labels.cacheUnavailable;
  }

  const percent = rate * 100;
  if (percent > 0 && percent < 0.01) {
    return "<0.01%";
  }
  return `${Number(percent.toFixed(2))}%`;
}
