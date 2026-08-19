"""phase3_benchmark_tasks_traefik.py -- Phase 3 retrieval benchmark ground
truth for Traefik (docs/ARCF_RETRIEVAL_BENCHMARK_PLAN_2026-08-17.md Sec 3
schema).

Repository: https://github.com/traefik/traefik, shallow-cloned 2026-08-17
into arcf/.benchmark_repos/traefik. Commit at clone time:
b51bd71e1f794f8cca5d2da0b4d0b151dfa05793 (2026-08-11).

Every ground_truth_files entry below was confirmed by directly reading the
real cloned source (Read/Grep on arcf/.benchmark_repos/traefik), per the
plan's Sec 3 non-negotiable rule -- none were derived from ARCF's own
retrieval output, and none were guessed from a filename or the project's
README/docs. Every ambiguity claim (e.g. the 46-way "New" collision) was
independently confirmed via `grep -rn "^func New(" --include="*.go" pkg/
cmd/ | wc -l` against the real cloned tree, not carried over from Consul's
own already-documented ambiguity figures.

Traefik has no meaningful classical-inheritance hierarchy (Go has no
class inheritance) -- category J is deliberately not represented here,
per the plan's own instruction not to force a category that doesn't fit
a repository's real structure. Category K (diffuse-structure query) is
also omitted: every genuine multi-file relationship found during
authoring had an identifiable dominant entry point (a builder/manager
function), unlike Consul's known no-single-entry-point ambiguity cases --
forcing a K task here would have meant inventing a query rather than
grounding one in a real structural fact.

expected_traversal_depth below is this task list's own considered
estimate (0 = single-file/no expansion needed, 1 = one real hop from
structural to behavioral file, matching the plan's cross-referenced
`context.task_profile.classify_retrieval_task`/TRAVERSAL_DEPTH table
shape) -- the deterministic harness (phase3_deterministic_pass_
traefik_consul.py) additionally calls classify_retrieval_task() directly
on each task's real query text and records the actual function output
alongside this estimate, so the harness output is what's "recorded not
assumed" per the plan's own field comment, and any mismatch between this
estimate and the real classifier output is reported rather than
silently reconciled.
"""

BENCHMARK_TASKS_TRAEFIK = [
    {
        "id": "traefik_task1_healthcheck_launch",
        "repo": "traefik",
        "query": (
            "What does ServiceHealthChecker.Launch do in Traefik's health-check "
            "subsystem, and what triggers it?"
        ),
        "category": "A",
        # Confirmed: pkg/healthcheck/healthcheck.go:53 `type
        # ServiceHealthChecker struct`, :72 `func NewServiceHealthChecker(...)`,
        # :134 `func (shc *ServiceHealthChecker) Launch(ctx context.Context)`.
        # Single-file, unambiguous qualified target.
        "ground_truth_files": ["pkg/healthcheck/healthcheck.go"],
        "ground_truth_structural": ["pkg/healthcheck/healthcheck.go"],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": [
            "ServiceHealthChecker",
            "ServiceHealthChecker.Launch",
            "NewServiceHealthChecker",
        ],
        "expected_subsystem": "healthcheck",
        "expected_traversal_depth": 0,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "traefik_task2_retry_new_ambiguous",
        "repo": "traefik",
        "query": "What does the New function do in Traefik's retry middleware package?",
        "category": "B",
        # Confirmed: pkg/middlewares/retry/retry.go:96 `func New(ctx
        # context.Context, next http.Handler, config dynamic.Retry, listener
        # Listener, name string) (http.Handler, error)`. Ambiguity confirmed
        # via `grep -rn "^func New(" --include="*.go" pkg/ cmd/ | wc -l` ==
        # 46 -- 46 separate func New( definitions repo-wide (one per
        # middleware/provider/loadbalancer package), the same closed-boundary
        # shape as Consul's New/Register/Notify ambiguity (arcf_recall_gap_
        # closed), now independently reconfirmed on a second, unrelated Go
        # repository.
        "ground_truth_files": ["pkg/middlewares/retry/retry.go"],
        "ground_truth_structural": ["pkg/middlewares/retry/retry.go"],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": ["New", "retry.New"],
        "expected_subsystem": "middlewares.retry",
        "expected_traversal_depth": 0,
        "ambiguity_expected": True,
        "ambiguity_note": (
            "46 separate `func New(` definitions exist repo-wide across pkg/ "
            "and cmd/ (grep-confirmed 2026-08-17) -- the bare identifier "
            "'New' is a repo-wide 46-way ambiguity, the same shape as "
            "Consul's already-closed New/Register/Notify boundary."
        ),
        "negative": False,
    },
    {
        "id": "traefik_task3_ip_allowlist_vocabulary_mismatch",
        "repo": "traefik",
        "query": (
            "How does Traefik reject requests from client IP addresses that "
            "aren't on an approved list?"
        ),
        "category": "C",
        # Confirmed: pkg/middlewares/ipallowlist/ip_allowlist.go:21 `type
        # ipAllowLister struct`, :30 `func New(...)`, :88 `func reject(ctx
        # context.Context, statusCode int, rw http.ResponseWriter)`. Query
        # deliberately avoids the codebase's own vocabulary ("allowlist",
        # "IPAllowList", "ipAllowLister") in favor of "reject"/"approved
        # list", to test lexical-mismatch retrieval rather than a
        # near-verbatim identifier match.
        "ground_truth_files": ["pkg/middlewares/ipallowlist/ip_allowlist.go"],
        "ground_truth_structural": ["pkg/middlewares/ipallowlist/ip_allowlist.go"],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": ["ipAllowLister", "reject"],
        "expected_subsystem": "middlewares.ipallowlist",
        "expected_traversal_depth": 0,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "traefik_task4_wrr_loadbalancer_subsystem",
        "repo": "traefik",
        "query": (
            "How does Traefik's service manager build a weighted "
            "round-robin load-balancing handler that distributes traffic "
            "across a service's backend servers?"
        ),
        "category": "D",
        # Confirmed: pkg/server/service/service.go:298
        # `func (m *Manager) getWRRServiceHandler(...)` calls
        # `wrr.New(config.Sticky, config.HealthCheck != nil)` at line 304 and
        # `balancer.Add(...)` at line 310 -- a real, direct call into
        # pkg/server/service/loadbalancer/wrr/wrr.go:55 `func New(sticky
        # *dynamic.Sticky, wantsHealthCheck bool) *Balancer`.
        "ground_truth_files": [
            "pkg/server/service/service.go",
            "pkg/server/service/loadbalancer/wrr/wrr.go",
        ],
        "ground_truth_structural": ["pkg/server/service/service.go"],
        "ground_truth_behavioral": ["pkg/server/service/loadbalancer/wrr/wrr.go"],
        "ground_truth_symbols": [
            "Manager.getWRRServiceHandler",
            "wrr.New",
            "Balancer",
            "Balancer.Add",
        ],
        "expected_subsystem": "server.service.loadbalancer",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "traefik_task5_rule_parsing_muxer_crossfile",
        "repo": "traefik",
        "query": (
            "How does Traefik parse a routing rule like Host(`example.com`) "
            "and use it to decide whether an incoming HTTP request matches "
            "a router?"
        ),
        "category": "E",
        # Confirmed: pkg/rules/parser.go:31 `func NewParser(matchers
        # []string) (predicate.Parser, error)`, :22 `type Tree struct`,
        # :117 `func CheckRule(rule *Tree) error` -- the rule-language
        # parser (structural). pkg/muxer/http/mux.go imports
        # "github.com/traefik/traefik/v3/pkg/rules" and, at line 271,
        # `func (m *matchersTree) addRule(rule *rules.Tree, funcs
        # matcherBuilderFuncs) error` directly calls `rules.CheckRule(rule)`
        # (line 284) and consumes `rules.Tree` fields (Matcher/RuleLeft/
        # RuleRight/Value/Not) to build the live request-matching tree --
        # the real behavioral collaborator that turns a parsed rule into
        # request-matching logic.
        "ground_truth_files": ["pkg/rules/parser.go", "pkg/muxer/http/mux.go"],
        "ground_truth_structural": ["pkg/rules/parser.go"],
        "ground_truth_behavioral": ["pkg/muxer/http/mux.go"],
        "ground_truth_symbols": ["NewParser", "CheckRule", "Tree", "matchersTree.addRule"],
        "expected_subsystem": "rules+muxer",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "traefik_task6_middleware_chain_call_chain",
        "repo": "traefik",
        "query": (
            "What builds the retry middleware and circuit breaker handlers "
            "when Traefik constructs a router's middleware chain?"
        ),
        "category": "F",
        # Confirmed: pkg/server/middleware/middlewares.go:159
        # `return circuitbreaker.New(ctx, next, *config.CircuitBreaker,
        # middlewareName)` and :383 `return retry.New(ctx, next,
        # *config.Retry, retry.Listeners{}, middlewareName)`, both inside
        # the same middleware-construction switch/builder function -- a
        # real, direct two-callee call-chain from one builder file.
        "ground_truth_files": [
            "pkg/server/middleware/middlewares.go",
            "pkg/middlewares/retry/retry.go",
            "pkg/middlewares/circuitbreaker/circuit_breaker.go",
        ],
        "ground_truth_structural": ["pkg/server/middleware/middlewares.go"],
        "ground_truth_behavioral": [
            "pkg/middlewares/retry/retry.go",
            "pkg/middlewares/circuitbreaker/circuit_breaker.go",
        ],
        "ground_truth_symbols": ["retry.New", "circuitbreaker.New"],
        "expected_subsystem": "server.middleware",
        "expected_traversal_depth": 1,
        "ambiguity_expected": True,
        "ambiguity_note": (
            "Both callees are two of the same 46 repo-wide `func New(` "
            "definitions as task2 -- disambiguated only by package "
            "qualification (retry.New / circuitbreaker.New), not by the "
            "bare name."
        ),
        "negative": False,
    },
    {
        "id": "traefik_task7_transport_tls_config_driven",
        "repo": "traefik",
        "query": (
            "How does Traefik's transport manager decide whether to build "
            "a custom TLS configuration for a backend server, instead of "
            "using Go's default TLS settings?"
        ),
        "category": "H",
        # Confirmed: pkg/server/service/transport.go:159 `func (t
        # *TransportManager) createTLSConfig(cfg *dynamic.ServersTransport)
        # (*tls.Config, error)`; line 174 gates custom TLS config
        # construction on `cfg.InsecureSkipVerify || len(cfg.RootCAs) > 0 ||
        # len(cfg.ServerName) > 0 || len(cfg.Certificates) > 0 ||
        # cfg.PeerCertURI != "" || len(cfg.PeerCertSANs) > 0 ||
        # len(cfg.CipherSuites) > 0 || cfg.MaxVersion != "" ||
        # cfg.MinVersion != ""` -- behavior gated entirely by
        # ServersTransport config fields, not visible in the call graph
        # alone (a caller of createTLSConfig can't tell which branch will
        # execute without knowing the config values).
        "ground_truth_files": ["pkg/server/service/transport.go"],
        "ground_truth_structural": ["pkg/server/service/transport.go"],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": ["TransportManager.createTLSConfig", "InsecureSkipVerify"],
        "expected_subsystem": "server.service.transport",
        "expected_traversal_depth": 0,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "traefik_task8_plugin_builder_dynamic_dispatch",
        "repo": "traefik",
        "query": (
            "How does Traefik's plugin builder decide whether to load a "
            "plugin as a WASM module or as a Yaegi-interpreted Go plugin?"
        ),
        "category": "I",
        # Confirmed: pkg/plugins/builder.go:131 `func newMiddlewareBuilder(
        # ctx context.Context, goPath string, manifest *Manifest, moduleName
        # string, settings Settings) (middlewareBuilder, error)` switches on
        # `manifest.Runtime`: case runtimeWasm -> calls
        # `newWasmMiddlewareBuilder(...)` (defined pkg/plugins/
        # middlewarewasm.go:27); case runtimeYaegi, "" -> calls
        # `newYaegiMiddlewareBuilder(...)` (defined pkg/plugins/
        # middlewareyaegi.go:28). Real runtime-string-driven dispatch to one
        # of two different plugin-execution implementations behind the same
        # `middlewareBuilder` interface.
        "ground_truth_files": [
            "pkg/plugins/builder.go",
            "pkg/plugins/middlewarewasm.go",
            "pkg/plugins/middlewareyaegi.go",
        ],
        "ground_truth_structural": ["pkg/plugins/builder.go"],
        "ground_truth_behavioral": [
            "pkg/plugins/middlewarewasm.go",
            "pkg/plugins/middlewareyaegi.go",
        ],
        "ground_truth_symbols": [
            "newMiddlewareBuilder",
            "newWasmMiddlewareBuilder",
            "newYaegiMiddlewareBuilder",
        ],
        "expected_subsystem": "plugins",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "traefik_task9_negative_graphql",
        "repo": "traefik",
        "query": (
            "How does Traefik implement its own built-in GraphQL query "
            "resolver for the dashboard API?"
        ),
        "category": "L",
        # Confirmed absent: `grep -rli "graphql" --include="*.go" .` against
        # the real cloned Traefik tree returns zero matches. Traefik's
        # dashboard/API (pkg/api) is a plain REST/JSON API; no GraphQL
        # layer exists anywhere in the Go source.
        "ground_truth_files": [],
        "ground_truth_structural": [],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": [],
        "expected_subsystem": None,
        "expected_traversal_depth": 0,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": True,
    },
]
