# Reel cost and provider policy

Verified 2026-11-25 against the public OpenRouter endpoint catalogs. Listed rates below are USD per million input/output tokens, for individual Chat Completions requests. A scheduled batch product has a different interface and turnaround.

| Model and task | Route / tier | Input | Output |
|---|---|---:|---:|
| Claude Opus 5.5, medium reasoning, two editorial calls (select takes, then storyboard) | Amazon Bedrock, Azure global, Vertex global, Claude Platform on AWS, Anthropic standard | 4 | 20 |
| Claude Opus 5.5 | Anthropic Fast | 8 | 40 |
| Gemini 4 Argon, review of delivery and three references | Google AI Studio Flex | 1 | 5 |
| Gemini 4 Argon | Google AI Studio / Vertex global standard | 2 | 10 |
| Gemini 4 Argon | Google AI Studio / Vertex priority | 3.60 | 18 |

app/routing.py retrieves current endpoint prices before every paid request. The endpoint must attain both listed minima, be available, and fit the historical ceilings of $4/$20 for Opus and $1/$5 for Argon. Price ties use one compatible endpoint. The request pins its slug, sets a maximum input/output price, disallows fallback and selects the flex service tier when required. A catalog failure, a pricing trade-off or an unavailable minimum blocks the request. Billed totals depend on actual token usage, media, cache and reasoning.

The enforced per-job API budget is USD 2 across all attempts. Resuming a job keeps its ledger. The separate weekly limit on the OpenRouter key still applies.

Illustrative budget for one 60–90 s final reel, excluding local equipment, power and human time: assume both Opus calls together use 12,000 input and 4,000 billed output tokens ($0.128). Assume one Gemini review including all media uses 60,000 input and 1,200 billed output ($0.066). API total $0.194. These are example token counts, not an observed duration-to-token conversion. A second identical Gemini review adds $0.066; repeating both Opus calls and the review at the same volumes totals $0.388. A longer raw take, reference duration and higher frame sampling can change the total. No third model is required.

For the first real job retain usage.jsonl and cost.json under jobs/<id>/full; include failed calls and sum every attempt on the same reel. An unreported charge stays unknown. Report API cost separately from local compute and editorial labor. A real clip, the three references and a reel-specific OpenRouter key are required for a measured result.

Sources: https://openrouter.ai/api/v1/models/anthropic/claude-opus-5.5/endpoints and https://openrouter.ai/api/v1/models/google/gemini-4-argon/endpoints . Routing: https://openrouter.ai/docs/guides/routing/provider-selection .
