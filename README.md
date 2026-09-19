<h1 align="center">llm-gateway (Python · httpx · Anthropic API)</h1>
<p align="center"><i>Limits enforced before the request leaves, not reconciled after the bill arrives</i></p>

<p align="center">
  <a href="#the-order-is-the-design">The order is the design</a> &middot;
  <a href="#routing-is-where-the-money-is">Routing</a> &middot;
  <a href="#guardrails-redaction-matters-more-than-blocking">Guardrails</a> &middot;
  <a href="#caching-is-exact-match-deliberately">Caching</a> &middot;
  <a href="#budgets-are-checked-before-the-call">Budgets</a> &middot;
  <a href="#problems-hit-while-building-this">Problems hit</a>
</p>

<p align="center">
  <a href="https://github.com/hammas159/llm-gateway/actions/workflows/ci.yml"><img src="https://github.com/hammas159/llm-gateway/actions/workflows/ci.yml/badge.svg" alt="ci"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-1%20(httpx)-success" alt="deps">
  <img src="https://img.shields.io/badge/stack-httpx%20%C2%B7%20Streamlit-orange" alt="stack">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="license"></a>
</p>

---

## The order is the design

```mermaid
flowchart LR
    R["request"] --> G["guardrails<br/>redact PII"]
    G --> C{"cache hit?"}
    C -->|"yes"| H["return cached"]
    C -->|"no"| B{"within budget?"}
    B -->|"no"| X["refuse"]
    B -->|"yes"| RT["route to a provider"]
    RT --> P["provider call"]
    P -->|"fails"| FB["fallback chain"]
    FB --> P
    P --> OUT["response"]

    style X fill:#dc2626,color:#fff
    style H fill:#16a34a,color:#fff
```

**The order is the design.** Redaction happens before caching, so a cache key never contains
PII. The budget is checked before the call, not after it - which is the difference between a
limit and a report.


```
guardrails(in) → budget → cache → route → call with fallback → guardrails(out) → record
```

Each position is a decision:

- **Guardrails first**, so a blocked request costs nothing.
- **Budget before cache**, so a tenant over their limit stops being served. Serving
  them from cache would hide the breach.
- **Cache before routing**, because a hit makes the routing decision irrelevant.
- **Guardrails again on the way out**, because a model can echo a secret that reached
  it from a retrieved document rather than from the prompt.

## Routing is where the money is

Most requests are easy and a small minority are hard. A flat model choice pays the
hard-request price for all of them — usually a bigger loss than any prompt
optimisation can recover.

```python
gateway.complete(Request(prompt="hi"))
# -> local-small   (free)

gateway.complete(Request(prompt="Analyse the trade-offs of this architecture"))
# -> frontier      (paid, and worth it)
```

Difficulty is estimated **deterministically** from the request. A model-based
classifier would be more accurate and would add a model call to every request — the
exact cost the router exists to avoid.

A tenant restricted to one model still gets an answer to a hard question, on the best
model they are permitted. Refusing there would mean a tenant on a small plan cannot
ask anything difficult; silently upgrading them to a model they do not pay for would
be worse. Both cases are tests.

## Guardrails: redaction matters more than blocking

Blocking prompt injection is a losing arms race. **Not forwarding an API key to a
third party is a control that actually holds.**

```python
check_input("here is my key AKIAIOSFODNN7EXAMPLE")
# -> "here is my key [REDACTED_AWS_KEY]"      never reaches the provider
```

Detected: AWS keys, GitHub tokens, OpenAI/Anthropic keys, Slack tokens, private keys,
JWTs. Optional PII redaction covers email, cards, phone numbers and **CNIC** — the
Pakistani national ID format, which no off-the-shelf tool looks for.

Injection attempts are **blocked, not sanitised**. A rewritten attack that looks
harmless is worse than a refusal, because it hides that anyone tried. Blocked requests
are still logged for the same reason.

## Caching is exact-match, deliberately

Semantic caching sounds better and is an excellent way to serve a confidently wrong
answer. *"Is X safe for children"* and *"is X safe for adults"* embed almost
identically and require opposite replies.

So normalisation is whitespace and case only. A cache hit is also recorded at **zero
cost** — reporting the original price would inflate every spend figure in the system.

## Budgets are checked before the call

```python
def test_budget_is_checked_before_the_call_not_after():
    """A budget reconciled afterwards is an invoice, not a limit."""
    ...
    assert provider.calls == 0
```

Spend uses a rolling window rather than calendar days: a limit that resets at midnight
UTC is a limit that can be doubled at 23:59.

## Testing

**51 tests (44 core + 7 for the optional Streamlit demo), no API key, no network, no model.**

Everything worth testing in a gateway is a *provider behaviour* — succeeding, failing,
rate-limiting, being expensive. Faking the providers makes the entire policy layer
verifiable in milliseconds, which is why this project is tested far more thoroughly
than systems that need a live model to exercise anything.

```bash
make test
```

| Covered | |
|---|---|
| Routing | difficulty estimation, tier selection, pinning, allowlists |
| Fallback | provider down, provider rate-limiting, everything down |
| Cache | normalisation, bypass, per-model isolation, zero-cost hits |
| Guardrails | 5 injection styles, 3 secret formats, output redaction, CNIC |
| Budgets | spend ceiling, rate ceiling, tenant isolation, pre-call enforcement |

## Providers

`ollama` (local, free) · `anthropic` · `huggingface` — behind one interface, all
optional. Prices live as data, not code, so they can be corrected without touching
logic.

Adding a provider means implementing one method.

## Layout

```
src/gateway/
  gateway.py            the pipeline; the order is the design
  types.py              Request, Response, Usage
  policy/router.py      difficulty estimation and tier selection
  policy/budget.py      rolling-window spend and rate limits
  policy/guardrails.py  injection blocking, secret and PII redaction
  cache/store.py        exact-match TTL cache
  providers/base.py     the interface, including self-pricing
  providers/real.py     ollama, anthropic, huggingface
tests/fakes.py          providers that fail, rate-limit, and cost money on demand
```

## Limits

- Difficulty estimation is heuristic. It is right often enough to save money and will
  occasionally send an easy request to an expensive model.
- The cache is in-process. Redis-backed is the obvious next step for multi-instance
  deployments.
- Prices change. Check them before quoting a figure.
- Injection patterns catch common phrasings, not novel attacks. They are a filter, not
  a guarantee — which is why redaction, not blocking, is the control that carries the
  weight here.

## Keywords

LLM gateway &middot; API gateway &middot; rate limiting &middot; budget enforcement &middot; cost control &middot; PII redaction &middot; guardrails &middot; prompt injection &middot; fallback chains &middot; provider routing &middot; response caching &middot; LLMOps &middot; observability &middot; httpx &middot; Streamlit &middot; production LLM &middot; token accounting

## License

MIT

---

## Run it yourself

```bash
git clone https://github.com/hammas159/llm-gateway
cd llm-gateway

uv sync --all-groups     # or: pip install -e ".[dev]"
make test                # 51 tests, no API key, no network, no model
```

Every test runs against fake providers, so a reviewer can verify the whole policy layer
without an account anywhere. To route real traffic, add a provider:

```bash
ollama pull qwen2.5:3b-instruct       # local, free
export ANTHROPIC_API_KEY=...          # optional, for the frontier tier
```

```python
from gateway import Gateway, Request
from gateway.providers.real import AnthropicProvider, OllamaProvider

gateway = Gateway(providers=[OllamaProvider(), AnthropicProvider()])
gateway.complete(Request(prompt="hi", tenant="acme"))            # -> local, $0.00
gateway.complete(Request(prompt="Analyse this architecture..."))  # -> frontier
gateway.stats()   # cost per model, cache hit rate, fallback rate
```

### Input / Output

![input](docs/images/input.png)

`python demo.py`

![output](docs/images/output.png)

Five behaviours in one run: the router sends an easy question to `local-small` and a hard
one to `frontier`, the repeated question is served from cache, the secret is redacted
before it leaves the process, and the injection attempt is blocked.

The blocked request is still written to the gateway's log. A refusal nobody can see is
indistinguishable from a request that never arrived.

Uses the same fake providers the tests use — no API key, no network, but real prices, so
the $0.084 is the actual cost of that one routing decision.

## Problems hit while building this

**A tenant restricted to one model could not ask a hard question at all.** The router
picked a difficulty tier, filtered its preferred models against the tenant's allowlist,
found nothing, and raised. So a customer on a small-model plan got an error instead of
an answer whenever their question looked complex.

Both obvious fixes are wrong: refusing locks the tenant out of hard questions, and
silently upgrading charges them for a model they never bought. *Fixed* by falling back
to the best model the tenant **is** permitted, with the genuinely-unknown-model case
still failing loudly. Both branches are now tests.

**Semantic caching was rejected on purpose.** It was the obvious upgrade and it is a
good way to serve a confidently wrong answer — *"is X safe for children"* and *"is X
safe for adults"* embed almost identically and need opposite replies. The cache
normalises whitespace and case only, and a cache hit is recorded at **zero cost**,
because reporting the original price on a hit inflates every spend figure in the system.

**Every Pakistani CNIC was being reported to a compliance audit as a credit card.**
Found by building the demo above and clicking the CNIC sample. A CNIC is 13 digits with
separators, so `credit_card`'s `(?:\d[ -]?){13,19}` matches it too — and it sat *before*
`cnic` in `PII_PATTERNS`, so it claimed the match first. The data was still redacted, so
nothing leaked; the *label* was wrong, which is the part a data-protection report is
made of.

The existing test could not catch it, and that is the more useful half of the lesson:

```python
def test_cnic_is_recognised(self):
    out = check_input("my cnic is 35202-1234567-1", redact_pii=True)
    assert "35202-1234567-1" not in out.text      # passes either way
```

It asserted the digits were *gone*, which is true whichever pattern fired. *Fixed* by
ordering specific patterns before general ones, and by asserting the finding label
(`out.findings == ["redacted:cnic"]`) rather than just the absence of the text — the
version of the test that actually fails against the old code.