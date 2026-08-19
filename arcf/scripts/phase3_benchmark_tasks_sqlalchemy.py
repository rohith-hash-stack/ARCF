"""phase3_benchmark_tasks_sqlalchemy.py -- Phase 3 retrieval benchmark
ground truth for SQLAlchemy (docs/ARCF_RETRIEVAL_BENCHMARK_PLAN_2026-08-17.md
Sec 3 schema).

Repository: https://github.com/sqlalchemy/sqlalchemy, shallow-cloned
2026-08-17 into arcf/.benchmark_repos/sqlalchemy. Commit at clone time:
111a05a35b9fb4e6683bd18d3064634e002233f6 (2026-08-13).

Every ground_truth_files entry below was confirmed by directly reading
the real cloned source (Read/Grep on arcf/.benchmark_repos/sqlalchemy),
per the plan's Sec 3 non-negotiable rule -- none were derived from
ARCF's own retrieval output, and none were guessed from a filename.

SQLAlchemy is the plan's deliberate stress case for query category I
(dynamic-dispatch / interface-based). Tasks 2, 3, and 4 below are all
category I, each targeting a genuinely different dynamic-dispatch
mechanism (metaclass-driven class interception, descriptor-protocol
attribute access, and __new__-based constructor redirection) so the
category isn't represented by three near-duplicates of the same
mechanism.
"""

BENCHMARK_TASKS_SQLALCHEMY = [
    {
        "id": "sqla_task1_engine_connect",
        "repo": "sqlalchemy",
        "query": "What does Engine.connect do and what object does it return?",
        "category": "A",
        # Confirmed: lib/sqlalchemy/engine/base.py:3237 `def connect(self) ->
        # Connection:` returns `self._connection_cls(self)`; Connection class
        # itself defined at line 90 in the same file.
        "ground_truth_files": ["lib/sqlalchemy/engine/base.py"],
        "ground_truth_structural": ["lib/sqlalchemy/engine/base.py"],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": ["Engine.connect", "Connection"],
        "expected_subsystem": "engine",
        "expected_traversal_depth": 0,
        "ambiguity_expected": False,
        "ambiguity_note": (
            "The qualified query target Engine.connect is unambiguous, but "
            "the bare identifier 'connect' has 23 separate def connect( "
            "definitions repo-wide (dialects, pool, DBAPI stubs) -- noted "
            "for context, not expected to affect this qualified query."
        ),
        "negative": False,
    },
    {
        "id": "sqla_task2_declarative_metaclass",
        "repo": "sqlalchemy",
        "query": (
            "How does SQLAlchemy's declarative base class use a metaclass to "
            "intercept class creation and configure ORM mappings when a user "
            "defines a model class?"
        ),
        "category": "I",
        # Confirmed: lib/sqlalchemy/orm/decl_api.py:175 `class DeclarativeMeta
        # (DeclarativeAttributeIntercept)` overrides __init__ and calls
        # `_ORMClassConfigurator._as_declarative(reg, cls, dict_)`.
        # _ORMClassConfigurator / _MapperConfig are defined in
        # lib/sqlalchemy/orm/decl_base.py:254/315 -- the real collaborator
        # that does the actual mapping configuration work the metaclass
        # delegates to.
        "ground_truth_files": [
            "lib/sqlalchemy/orm/decl_api.py",
            "lib/sqlalchemy/orm/decl_base.py",
        ],
        "ground_truth_structural": ["lib/sqlalchemy/orm/decl_api.py"],
        "ground_truth_behavioral": ["lib/sqlalchemy/orm/decl_base.py"],
        "ground_truth_symbols": [
            "DeclarativeMeta",
            "_ORMClassConfigurator._as_declarative",
        ],
        "expected_subsystem": "orm.declarative",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "sqla_task3_instrumented_attribute_descriptor",
        "repo": "sqlalchemy",
        "query": (
            "How does SQLAlchemy implement attribute get/set interception "
            "for mapped columns using Python's descriptor protocol?"
        ),
        "category": "I",
        # Confirmed: lib/sqlalchemy/orm/attributes.py:515 `class
        # InstrumentedAttribute(QueryableAttribute[_T_co])` implements
        # __get__ (561), __set__ (545), __delete__ (550) -- the descriptor
        # protocol methods Python calls to intercept `instance.attr` /
        # `instance.attr = value`. QueryableAttribute (base class, line 136)
        # is in the same file.
        "ground_truth_files": ["lib/sqlalchemy/orm/attributes.py"],
        "ground_truth_structural": ["lib/sqlalchemy/orm/attributes.py"],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": [
            "InstrumentedAttribute",
            "InstrumentedAttribute.__get__",
            "InstrumentedAttribute.__set__",
            "QueryableAttribute",
        ],
        "expected_subsystem": "orm.attributes",
        "expected_traversal_depth": 0,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "sqla_task4_table_new_dynamic_dispatch",
        "repo": "sqlalchemy",
        "query": (
            "How does SQLAlchemy's Table class use __new__ to redirect "
            "construction so that repeated Table() calls with the same "
            "name and metadata don't always create a new object?"
        ),
        "category": "I",
        # Confirmed: lib/sqlalchemy/sql/schema.py:328 `class Table(...)`;
        # __new__ at line 482 delegates to the classmethod `_new` (line
        # 486), which inspects (name, metadata, ...) args and consults the
        # MetaData registry before deciding whether to construct a new
        # instance -- a real, non-synthetic dynamic-dispatch-via-__new__
        # mechanism, distinct from tasks 2/3's metaclass and descriptor
        # mechanisms.
        "ground_truth_files": ["lib/sqlalchemy/sql/schema.py"],
        "ground_truth_structural": ["lib/sqlalchemy/sql/schema.py"],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": ["Table.__new__", "Table._new"],
        "expected_subsystem": "sql.schema",
        "expected_traversal_depth": 0,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "sqla_task5_dialect_plugin_loading",
        "repo": "sqlalchemy",
        "query": (
            "How does SQLAlchemy pick which dialect implementation class to "
            "use based on the driver name in a database connection URL "
            "string, e.g. 'postgresql+psycopg2://...'?"
        ),
        "category": "H",
        # Confirmed: lib/sqlalchemy/engine/url.py:761
        # `URL._get_entrypoint` calls `registry.load(name)` where `name` is
        # derived from `self.drivername` (a config value parsed out of the
        # connection URL string, not visible in the call graph alone).
        # `registry` is a `PluginLoader` instance (lib/sqlalchemy/util/
        # langhelpers.py:361) whose `load()` method (line 372) resolves the
        # string to a class via either a registered impl or a real
        # importlib.metadata entry-point group lookup.
        "ground_truth_files": [
            "lib/sqlalchemy/engine/url.py",
            "lib/sqlalchemy/util/langhelpers.py",
        ],
        "ground_truth_structural": ["lib/sqlalchemy/engine/url.py"],
        "ground_truth_behavioral": ["lib/sqlalchemy/util/langhelpers.py"],
        "ground_truth_symbols": [
            "URL.get_dialect",
            "URL._get_entrypoint",
            "PluginLoader.load",
        ],
        "expected_subsystem": "engine.url",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": (
            "Config-driven dispatch: the actual dialect class loaded "
            "depends entirely on the URL string's drivername value at "
            "runtime, not on anything visible in a static call graph -- "
            "this is the mechanism category H is meant to test."
        ),
        "negative": False,
    },
    {
        "id": "sqla_task6_unit_of_work_subsystem",
        "repo": "sqlalchemy",
        "query": "How does the ORM Unit of Work subsystem coordinate the order in which pending inserts, updates, and deletes are flushed?",
        "category": "D",
        # Confirmed: lib/sqlalchemy/orm/unitofwork.py:156 `class
        # UOWTransaction` is the real coordinator (topological sort of
        # per-mapper "dependency" processing via _SaveUpdateAll/_DeleteAll/
        # _ProcessState etc., lines 555-789). Entry point is
        # lib/sqlalchemy/orm/session.py:4538 `Session._flush`, which
        # constructs `flush_context = UOWTransaction(self)` at line 4544.
        "ground_truth_files": [
            "lib/sqlalchemy/orm/unitofwork.py",
            "lib/sqlalchemy/orm/session.py",
        ],
        "ground_truth_structural": ["lib/sqlalchemy/orm/unitofwork.py"],
        "ground_truth_behavioral": ["lib/sqlalchemy/orm/session.py"],
        "ground_truth_symbols": ["UOWTransaction", "Session._flush"],
        "expected_subsystem": "orm.unitofwork",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "sqla_task7_session_commit_call_chain",
        "repo": "sqlalchemy",
        "query": "What does Session.commit() call internally, step by step, to actually persist pending changes to the database?",
        "category": "F",
        # Confirmed real call chain, directly grepped:
        # session.py:2040 Session.commit -> (via flush path) session.py:4538
        # Session._flush -> constructs UOWTransaction (unitofwork.py:156) at
        # session.py:4544 -> unitofwork.py calls persistence._save_obj
        # (line 760) / persistence._delete_obj (line 789) /
        # persistence._post_update (line 630), i.e. orm/persistence.py is a
        # real two-hop-deep collaborator, not a same-file/same-directory
        # adjacency guess.
        "ground_truth_files": [
            "lib/sqlalchemy/orm/session.py",
            "lib/sqlalchemy/orm/unitofwork.py",
            "lib/sqlalchemy/orm/persistence.py",
        ],
        "ground_truth_structural": ["lib/sqlalchemy/orm/session.py"],
        "ground_truth_behavioral": [
            "lib/sqlalchemy/orm/unitofwork.py",
            "lib/sqlalchemy/orm/persistence.py",
        ],
        "ground_truth_symbols": [
            "Session.commit",
            "Session._flush",
            "UOWTransaction",
            "persistence._save_obj",
        ],
        "expected_subsystem": "orm.session",
        "expected_traversal_depth": 2,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "sqla_task8_ambiguous_process",
        "repo": "sqlalchemy",
        "query": "What does the process function do in SQLAlchemy?",
        "category": "B",
        # Confirmed: `def process(` occurs 108 times repo-wide (grep
        # count), heavily concentrated in lib/sqlalchemy/sql/sqltypes.py
        # (type bind/result processors, e.g. lines 299/423/525/843/848/
        # 1018/...) and lib/sqlalchemy/engine/processors.py (row-level
        # DBAPI value processors). Deliberately unqualified/bare name
        # query -- the known-boundary ambiguous-symbol case (Sec 0 of the
        # plan), analogous to Consul's New/Register/Notify.
        "ground_truth_files": [
            "lib/sqlalchemy/sql/sqltypes.py",
            "lib/sqlalchemy/engine/processors.py",
        ],
        "ground_truth_structural": [],
        "ground_truth_behavioral": [
            "lib/sqlalchemy/sql/sqltypes.py",
            "lib/sqlalchemy/engine/processors.py",
        ],
        "ground_truth_symbols": ["process"],
        "expected_subsystem": None,
        "expected_traversal_depth": 0,
        "ambiguity_expected": True,
        "ambiguity_note": "process has 108 separate def process( definitions repo-wide (grep-confirmed) -- a bare-name ambiguity case in the same shape as the closed Consul recall-gap boundary (New/Register/Notify), expected to reproduce it here rather than surface a new mechanism.",
        "negative": False,
    },
    {
        "id": "sqla_task9_mapped_column_wraps_column",
        "repo": "sqlalchemy",
        "query": "How does the ORM's mapped_column / MappedColumn construct relate to the Core Column type used to define a table's schema?",
        "category": "E",
        # Confirmed: lib/sqlalchemy/orm/properties.py:516 `class
        # MappedColumn(...)` declares `column: Column[_T]` (a real typed
        # attribute wrapping the Core Column type) and its own docstring
        # states it "Maps a single :class:`_schema.Column` on a class."
        # Column itself is defined in lib/sqlalchemy/sql/schema.py:1770
        # `class Column(DialectKWArgs, SchemaItem, ColumnClause[_T],
        # Named[_T])` -- a genuine cross-file type-definition/usage
        # relationship (ORM layer wrapping a Core layer type), not same-
        # file adjacency.
        "ground_truth_files": [
            "lib/sqlalchemy/orm/properties.py",
            "lib/sqlalchemy/sql/schema.py",
        ],
        "ground_truth_structural": ["lib/sqlalchemy/orm/properties.py"],
        "ground_truth_behavioral": ["lib/sqlalchemy/sql/schema.py"],
        "ground_truth_symbols": ["MappedColumn", "Column"],
        "expected_subsystem": "orm.properties",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "sqla_task10_negative_graphql",
        "repo": "sqlalchemy",
        "query": "How does SQLAlchemy implement GraphQL query resolution and schema stitching?",
        "category": "L",
        # Confirmed absent: grep -rl "GraphQLResolver|WebSocketPool|
        # KafkaProducer" lib/sqlalchemy/ -> 0 matches. SQLAlchemy is a SQL
        # toolkit/ORM; it has no GraphQL layer at all. Tests false-positive
        # behavior per the plan's negative-query methodology.
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
