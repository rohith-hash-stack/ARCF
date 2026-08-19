"""phase3_benchmark_tasks_reuse_tier.py -- ARCF Retrieval Benchmark Plan
(docs/ARCF_RETRIEVAL_BENCHMARK_PLAN_2026-08-17.md), Phase 3, "reuse
tier" repos: Flask, spring-petclinic, vLLM.

These three repos already had real ARCF exposure (2026-08-12
validation_breadth_matrix_check.py run: Flask 85.7% fallback ratio,
spring-petclinic 50%, vllm 66.7%). Per the plan's §1 rationale, they
need only enough NEW tasks to fill query-taxonomy gaps (plan §2,
categories A-L) that run didn't probe -- that run only exercised
category A (exact symbol query: "Flask", "Owner"/"Person", "LLM"/
"CompletionChunk"), plus incidentally J (Owner extends Person).

6 new tasks below, covering categories B, E, F, H, L (two L instances,
one per a Python and a mixed-language repo, deliberately kept separate
since a negative-query harness's behavior can differ by language/
analyzer). None of these categories were exercised by the original run.

Ground truth was established by DIRECTLY READING the real source in
these repos' fresh clones (arcf/.benchmark_repos/{flask,spring-petclinic,
vllm}), per plan §3's non-negotiable rule (never derived from ARCF's own
retrieval output). Every claim below is grep-verified -- see each task's
own comment for the exact command.

Schema is plan §3's schema, plus one harness-only extra field,
`target_names`: plan §3 doesn't include this because ordinary ARCF usage
extracts target names from `query` via SLM-1 (IntentExtractor). This is
the *deterministic-only* pass (plan §7 step 1, hard "zero LLM calls"
constraint for this benchmark phase) -- so target_names are hand-picked
here from real, grepped symbol names, the exact same discipline
validation_breadth_matrix_check.py's own CASES list already uses (see
that file's `target_names` field and its own per-case grep comments).
"""

from __future__ import annotations

PHASE3_REUSE_TIER_TASKS = [
    # -- Flask -----------------------------------------------------------
    {
        "id": "flask_route_registration",
        "repo": "flask",
        "query": "How does Flask's @app.route decorator register a view function with the app's URL map?",
        "category": "E",  # cross-file behavior query
        "target_names": ["route", "add_url_rule"],
        # grep: "def route(self, rule: str" src/flask/sansio/scaffold.py:344
        #   -- decorator body calls `self.add_url_rule(rule, endpoint, f, **options)`.
        # grep: "def add_url_rule(" src/flask/sansio/app.py:605
        #   -- the App-level override that actually builds the werkzeug
        #      Rule and adds it to self.url_map; sansio/scaffold.py:376 also
        #      declares add_url_rule (Blueprint's deferred-registration
        #      version), confirmed by reading both bodies directly.
        "ground_truth_files": ["src/flask/sansio/scaffold.py", "src/flask/sansio/app.py"],
        "ground_truth_structural": ["src/flask/sansio/scaffold.py"],
        "ground_truth_behavioral": ["src/flask/sansio/app.py"],
        "ground_truth_symbols": ["route", "add_url_rule"],
        "expected_subsystem": "routing",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "flask_graphql_negative",
        "repo": "flask",
        "query": "How does Flask implement built-in GraphQL subscription resolvers?",
        "category": "L",  # negative / no-match query
        "target_names": ["GraphQL", "subscription"],
        # grep -rli "graphql" src/flask -> 0 matches, confirmed directly.
        # Flask has no GraphQL support of any kind; this is a genuine
        # false-target query, not a paraphrase of something real.
        "ground_truth_files": [],
        "ground_truth_structural": [],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": [],
        "expected_subsystem": None,
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": True,
    },
    # -- spring-petclinic --------------------------------------------------
    {
        "id": "petclinic_visit_booking_chain",
        "repo": "spring-petclinic",
        "query": "What happens when a new visit is booked for a pet -- what does VisitController.processNewVisitForm call to persist it?",
        "category": "F",  # call-chain query
        "target_names": ["VisitController", "processNewVisitForm", "addVisit"],
        # grep: "processNewVisitForm" .../owner/VisitController.java --
        #   body calls `owner.addVisit(petId, visit)` then `this.owners.save(owner)`.
        # grep: "public void addVisit(Integer petId" .../owner/Owner.java:164
        #   -- Owner.addVisit looks up the Pet and calls `pet.addVisit(visit)`.
        # grep: "public void addVisit(Visit visit)" .../owner/Pet.java:81
        #   -- confirmed directly, a real 3-file call chain.
        "ground_truth_files": [
            "src/main/java/org/springframework/samples/petclinic/owner/VisitController.java",
            "src/main/java/org/springframework/samples/petclinic/owner/Owner.java",
            "src/main/java/org/springframework/samples/petclinic/owner/Pet.java",
        ],
        "ground_truth_structural": [
            "src/main/java/org/springframework/samples/petclinic/owner/VisitController.java",
        ],
        "ground_truth_behavioral": [
            "src/main/java/org/springframework/samples/petclinic/owner/Owner.java",
            "src/main/java/org/springframework/samples/petclinic/owner/Pet.java",
        ],
        "ground_truth_symbols": ["processNewVisitForm", "addVisit"],
        "expected_subsystem": "owner/visit booking",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "petclinic_database_config",
        "repo": "spring-petclinic",
        "query": "Which database does spring-petclinic use by default, and how is that determined?",
        "category": "H",  # configuration-driven behavior
        "target_names": ["application.properties", "database"],
        # cat src/main/resources/application.properties -- confirmed
        # directly: `database=h2`, driving
        # `spring.sql.init.schema-locations=classpath*:db/${database}/schema.sql`.
        # No single Java symbol is the target here -- deliberately, this is
        # the config-indirection case the plan's failure taxonomy (§6,
        # "Configuration indirection") needs a real example of.
        "ground_truth_files": ["src/main/resources/application.properties"],
        "ground_truth_structural": ["src/main/resources/application.properties"],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": [],
        "expected_subsystem": "configuration",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": "No code symbol target -- config-key lookup, not AST resolution; expected to stress-test ARCF's config-driven-behavior handling (category H has no dedicated mechanism today).",
        "negative": False,
    },
    # -- vLLM ---------------------------------------------------------------
    {
        "id": "vllm_generate_ambiguous",
        "repo": "vllm",
        "query": "What does the generate method do?",
        "category": "B",  # ambiguous symbol query
        "target_names": ["generate"],
        # grep -rn "def generate(" --include=*.py . (excluding tests/) -> 9
        # real matches across the source tree, including at least 3
        # distinct class-method definitions in the engine layers:
        # vllm/entrypoints/llm.py:418 (LLM.generate, offline API),
        # vllm/v1/engine/async_llm.py (AsyncLLM.generate),
        # vllm/engine/protocol.py (EngineClient.generate, abstract).
        # Confirmed directly, real ambiguity -- not the closed 150+-way
        # Consul boundary, but a genuine same-named-method case this repo
        # actually has.
        "ground_truth_files": ["vllm/entrypoints/llm.py"],
        "ground_truth_structural": ["vllm/entrypoints/llm.py"],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": ["generate"],
        "expected_subsystem": "entrypoints",
        "expected_traversal_depth": 1,
        "ambiguity_expected": True,
        "ambiguity_note": "'generate' has >=9 real same-named method definitions repo-wide (llm.py, async_llm.py, protocol.py, and others) -- confirmed by grep, not the closed recall-gap's own Consul figures.",
        "negative": False,
    },
    {
        "id": "vllm_federated_learning_negative",
        "repo": "vllm",
        "query": "How does vLLM implement built-in support for federated learning across multiple data centers?",
        "category": "L",  # negative / no-match query
        "target_names": ["federated", "FederatedLearning"],
        # grep -rli "federated learning" --include=*.py . -> 0 matches,
        # confirmed directly. vLLM has distributed/tensor-parallel serving
        # but no federated-learning training feature of any kind.
        "ground_truth_files": [],
        "ground_truth_structural": [],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": [],
        "expected_subsystem": None,
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": True,
    },
]
