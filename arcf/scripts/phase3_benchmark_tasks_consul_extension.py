"""phase3_benchmark_tasks_consul_extension.py -- Phase 3 retrieval
benchmark ground truth EXTENSION for Consul (docs/
ARCF_RETRIEVAL_BENCHMARK_PLAN_2026-08-17.md Sec 3 schema).

Additive to scripts/validate_llm_grounding.py's existing BENCHMARK_TASKS
(6 tasks, unmodified, not duplicated here) -- per the plan's own
instruction to extend, not replace. Existing 6 tasks' categories, mapped
for this extension's own gap analysis (not stored in BENCHMARK_TASKS
itself, which predates this plan's category taxonomy):
  task1 (Catalog.Register)            -> A (exact symbol)
  task2 (Agent cache -> Notify)       -> E (cross-file, known ambiguity)
  task3 (Agent Config struct)         -> A (exact symbol / type contract)
  task4 (ACL BindingRuleList/binder)  -> F (call/dependency chain)
  task5 (New in agent/cache)          -> B (ambiguous common name)
  task6 (Prepopulate sibling caller)  -> E (cross-file, sibling package)
Gaps the existing 6 don't reach: C, D, G, H, I, J, K, L. This extension
adds D, I, and L (at minimum one L, per the plan's explicit instruction),
picked for real, independently-grepped structural facts rather than
forcing every remaining letter.

Repository: https://github.com/hashicorp/consul, re-cloned 2026-08-17 into
arcf/.benchmark_repos/consul (fresh clone for this phase, not reusing any
prior session's checkout). Commit at re-clone time:
2397ff0d763d34f2fe37fe59fde6a7f7fc430a3e (2026-08-14). Spot-check performed
against this fresh clone: all 7 files/symbols validate_llm_grounding.py's
existing BENCHMARK_TASKS depends on (agent/consul/catalog_endpoint.go,
agent/cache/cache.go, agent/cache/watch.go, agent/config/config.go,
agent/consul/acl_endpoint.go, agent/consul/auth/binder.go,
agent/auto-config/tls.go) still exist at their expected paths, and the
specific symbols/line numbers those tasks' own comments cite (Catalog.
Register, Cache.New, Cache.Notify, Config struct, ACL.BindingRuleList,
Binder.Bind, Cache.Prepopulate, and tls.go's Prepopulate call site) were
independently re-grepped and match exactly -- zero drift found.

Every ground_truth_files entry below was confirmed by directly reading
the real freshly-cloned source, per the plan's Sec 3 non-negotiable rule.
"""

BENCHMARK_TASKS_CONSUL_EXTENSION = [
    {
        "id": "consul_task7_ca_provider_dynamic_dispatch",
        "repo": "consul",
        "query": (
            "How does Consul's CA manager decide which certificate "
            "authority provider implementation -- Consul's built-in CA, "
            "Vault, or AWS -- to instantiate for a datacenter's Connect CA?"
        ),
        "category": "I",
        # Confirmed: agent/connect/ca/provider.go:65 `type Provider
        # interface` (the dispatch target's common interface, implemented
        # separately by ConsulProvider/VaultProvider/AWSProvider in the
        # same package). agent/consul/leader_connect_ca.go:458 `func (c
        # *CAManager) newProvider(conf *structs.CAConfiguration) (ca.
        # Provider, error)` switches on `conf.Provider`: case
        # structs.ConsulCAProvider -> ca.NewConsulProvider(...); case
        # structs.VaultCAProvider -> ca.NewVaultProvider(...); case
        # structs.AWSCAProvider -> ca.NewAWSProvider(...) -- a genuine
        # config-string-driven dynamic dispatch to one of three interface
        # implementations, the same mechanism shape as Traefik's plugin
        # builder (traefik_task8) on a completely different repository.
        "ground_truth_files": [
            "agent/connect/ca/provider.go",
            "agent/consul/leader_connect_ca.go",
        ],
        "ground_truth_structural": [
            "agent/connect/ca/provider.go",
            "agent/consul/leader_connect_ca.go",
        ],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": [
            "Provider",
            "CAManager.newProvider",
            "ca.NewConsulProvider",
            "ca.NewVaultProvider",
            "ca.NewAWSProvider",
        ],
        "expected_subsystem": "consul.connect.ca",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "consul_task8_autopilot_subsystem",
        "repo": "consul",
        "query": (
            "How does Consul's autopilot subsystem monitor cluster server "
            "health and expose that state through the operator API?"
        ),
        "category": "D",
        # Confirmed: agent/consul/autopilot.go:35 `type AutopilotDelegate
        # struct` implementing AutopilotConfig/KnownServers/
        # FetchServerStats/NotifyState/RemoveFailedServer; :80 `func (s
        # *Server) initAutopilot(config *Config)` wires it up (structural,
        # the subsystem's own entry point). agent/consul/
        # operator_autopilot_endpoint.go:145 `func (op *Operator)
        # AutopilotState(...)` at line 163 directly calls
        # `op.srv.autopilot.GetState()` -- the real collaborator that
        # surfaces the subsystem's state through Consul's RPC/HTTP operator
        # API (behavioral).
        "ground_truth_files": [
            "agent/consul/autopilot.go",
            "agent/consul/operator_autopilot_endpoint.go",
        ],
        "ground_truth_structural": ["agent/consul/autopilot.go"],
        "ground_truth_behavioral": ["agent/consul/operator_autopilot_endpoint.go"],
        "ground_truth_symbols": [
            "AutopilotDelegate",
            "Server.initAutopilot",
            "Operator.AutopilotState",
        ],
        "expected_subsystem": "consul.autopilot",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "consul_task9_negative_graphql",
        "repo": "consul",
        "query": "How does Consul implement a built-in GraphQL query resolver for its HTTP API?",
        "category": "L",
        # Confirmed absent: `grep -rli "graphql" --include="*.go" .`
        # against the real freshly-cloned Consul tree returns zero matches.
        # Consul's HTTP API (agent/*_endpoint.go) is plain REST/RPC-backed
        # JSON; no GraphQL layer exists anywhere in the Go source. Same
        # negative-query construction discipline as
        # negative_query_fpr_real_consul_check.py's "hallucinated_
        # identifier"/"out_of_scope_concept" categories -- a real,
        # independently-verified absence, not an assumed one.
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
