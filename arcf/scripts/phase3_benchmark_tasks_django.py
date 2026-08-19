"""phase3_benchmark_tasks_django.py -- Phase 3 retrieval benchmark ground
truth for Django (docs/ARCF_RETRIEVAL_BENCHMARK_PLAN_2026-08-17.md Sec 3
schema).

Repository: https://github.com/django/django, shallow-cloned 2026-08-17
into arcf/.benchmark_repos/django. Commit at clone time:
a3e6e7d3aa6e2aa793ba1d122a76cb007727197c (2026-08-14).

Every ground_truth_files entry below was confirmed by directly reading
the real cloned source (Read/Grep on arcf/.benchmark_repos/django), per
the plan's Sec 3 non-negotiable rule -- none were derived from ARCF's
own retrieval output, none guessed from a filename or README.

Django's ORM/forms/admin layers are the plan's designated stress case
for query category J (inheritance-heavy). Tasks 1 and 2 below each
target a real, independently-confirmed deep/wide class hierarchy
(auth's User->AbstractUser->AbstractBaseUser+PermissionsMixin->Model,
and forms' ModelForm->BaseModelForm / ModelFormMetaclass->
DeclarativeFieldsMetaclass->MediaDefiningClass) rather than the same
hierarchy queried twice.
"""

BENCHMARK_TASKS_DJANGO = [
    {
        "id": "django_task1_modelbase_metaclass_inheritance",
        "repo": "django",
        "query": (
            "How does Django's User model get its fields and permission "
            "behavior through the AbstractUser/AbstractBaseUser/"
            "PermissionsMixin class hierarchy, and what metaclass drives "
            "Model class construction?"
        ),
        "category": "J",
        # Confirmed: django/db/models/base.py:102 `class ModelBase(type)`
        # is the metaclass every django.db.models.Model subclass uses
        # (base.py:508 `class Model(AltersData, metaclass=ModelBase)`).
        # django/contrib/auth/base_user.py:43 `class AbstractBaseUser
        # (models.Model)`; django/contrib/auth/models.py:322 `class
        # PermissionsMixin(models.Model)`; models.py:451 `class AbstractUser
        # (AbstractBaseUser, PermissionsMixin)`; models.py:522 `class User
        # (AbstractUser)` -- a real, confirmed 4-level hierarchy plus a
        # mixin, all funneling through the same ModelBase metaclass.
        "ground_truth_files": [
            "django/db/models/base.py",
            "django/contrib/auth/base_user.py",
            "django/contrib/auth/models.py",
        ],
        "ground_truth_structural": ["django/db/models/base.py"],
        "ground_truth_behavioral": [
            "django/contrib/auth/base_user.py",
            "django/contrib/auth/models.py",
        ],
        "ground_truth_symbols": [
            "ModelBase",
            "Model",
            "AbstractBaseUser",
            "PermissionsMixin",
            "AbstractUser",
            "User",
        ],
        "expected_subsystem": "db.models",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "django_task2_modelform_metaclass_hierarchy",
        "repo": "django",
        "query": (
            "How does Django's ModelForm class combine Form field "
            "declaration with model-derived fields, and what metaclass "
            "chain makes that work?"
        ),
        "category": "J",
        # Confirmed: django/forms/widgets.py:306 `class MediaDefiningClass
        # (type)`; django/forms/forms.py:21 `class
        # DeclarativeFieldsMetaclass(MediaDefiningClass)`; forms.py:432
        # `class Form(BaseForm, metaclass=DeclarativeFieldsMetaclass)`.
        # django/forms/models.py:274 `class ModelFormMetaclass
        # (DeclarativeFieldsMetaclass)`; models.py:347 `class BaseModelForm
        # (BaseForm, AltersData)`; models.py:585 `class ModelForm
        # (BaseModelForm, metaclass=ModelFormMetaclass)` -- a real
        # 3-level metaclass chain (MediaDefiningClass ->
        # DeclarativeFieldsMetaclass -> ModelFormMetaclass) distinct from
        # task 1's ModelBase/Model hierarchy, deliberately picked so
        # Django's two J tasks don't probe the same mechanism twice.
        "ground_truth_files": [
            "django/forms/widgets.py",
            "django/forms/forms.py",
            "django/forms/models.py",
        ],
        "ground_truth_structural": ["django/forms/forms.py"],
        "ground_truth_behavioral": [
            "django/forms/widgets.py",
            "django/forms/models.py",
        ],
        "ground_truth_symbols": [
            "MediaDefiningClass",
            "DeclarativeFieldsMetaclass",
            "Form",
            "ModelFormMetaclass",
            "BaseModelForm",
            "ModelForm",
        ],
        "expected_subsystem": "forms",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "django_task3_manager_from_queryset_dynamic_class",
        "repo": "django",
        "query": (
            "How does Django dynamically build a Manager class from a "
            "custom QuerySet class using Manager.from_queryset?"
        ),
        "category": "I",
        # Confirmed: django/db/models/manager.py:108 `def from_queryset(cls,
        # queryset_class, class_name=None)` literally calls
        # `type(class_name, (cls,), {...})` (line 111) to construct a new
        # class object at runtime -- genuine dynamic class construction,
        # not just static inheritance. django/db/models/manager.py:176
        # `class Manager(BaseManager.from_queryset(QuerySet))` is the real,
        # already-in-production caller of this mechanism.
        "ground_truth_files": ["django/db/models/manager.py"],
        "ground_truth_structural": ["django/db/models/manager.py"],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": ["BaseManager.from_queryset", "Manager"],
        "expected_subsystem": "db.models.manager",
        "expected_traversal_depth": 0,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "django_task4_model_save_exact",
        "repo": "django",
        "query": "What does Model.save do in Django's ORM?",
        "category": "A",
        # Confirmed: django/db/models/base.py:848 `def save(self, ...)`.
        "ground_truth_files": ["django/db/models/base.py"],
        "ground_truth_structural": ["django/db/models/base.py"],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": ["Model.save"],
        "expected_subsystem": "db.models",
        "expected_traversal_depth": 0,
        "ambiguity_expected": False,
        "ambiguity_note": (
            "The qualified query Model.save is unambiguous, but the bare "
            "identifier 'save' has 18 separate def save( definitions "
            "repo-wide (grep-confirmed) -- noted for context."
        ),
        "negative": False,
    },
    {
        "id": "django_task5_ambiguous_save",
        "repo": "django",
        "query": "What does the save method do?",
        "category": "B",
        # Same 18 def save( definitions repo-wide as task 4's note, but
        # here queried WITHOUT a qualifying class name -- the deliberate
        # bare-name ambiguity case (Sec 0 of the plan), same shape as
        # Consul's New/Register/Notify boundary.
        "ground_truth_files": ["django/db/models/base.py"],
        "ground_truth_structural": ["django/db/models/base.py"],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": ["save"],
        "expected_subsystem": None,
        "expected_traversal_depth": 0,
        "ambiguity_expected": True,
        "ambiguity_note": "save has 18 separate def save( definitions repo-wide (grep-confirmed: Model.save, ModelForm.save, formset save_new/save_existing, session backends' save, etc.) -- expected to reproduce the closed recall-gap boundary rather than surface a new mechanism.",
        "negative": False,
    },
    {
        "id": "django_task6_signal_dispatch_subsystem",
        "repo": "django",
        "query": "How does Django's signal dispatch subsystem deliver a sent signal to all connected receivers?",
        "category": "D",
        # Confirmed: django/dispatch/dispatcher.py:68 `class Signal`;
        # `connect` (line 102) registers `(lookup_key, receiver, sender_ref,
        # is_async)` tuples into `self.receivers` (initialized line 91);
        # `send` (line 219) calls `self._live_receivers(sender)` (line 216)
        # to get sync/async receiver lists and dispatches to each.
        "ground_truth_files": ["django/dispatch/dispatcher.py"],
        "ground_truth_structural": ["django/dispatch/dispatcher.py"],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": ["Signal", "Signal.connect", "Signal.send"],
        "expected_subsystem": "dispatch",
        "expected_traversal_depth": 0,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "django_task7_request_response_call_chain",
        "repo": "django",
        "query": "What calls happen between BaseHandler.get_response receiving a request and a view actually being resolved and invoked?",
        "category": "F",
        # Confirmed real call chain, directly grepped:
        # django/core/handlers/base.py:138 `get_response` calls
        # `self._middleware_chain(request)` -> eventually reaches
        # `_get_response` (line 176) -> `self.resolve_request(request)`
        # (line 183, resolve_request defined line 302) -> line 315
        # `resolver.resolve(request.path_info)` where resolver comes from
        # `get_resolver()` (django/urls/resolvers.py). URLResolver.resolve
        # is a real method in django/urls/resolvers.py (class URLResolver
        # at line 503; resolve() methods at lines 471/670 for
        # URLPattern/URLResolver respectively) -- a genuine cross-file
        # execution-path collaborator, not adjacency.
        "ground_truth_files": [
            "django/core/handlers/base.py",
            "django/urls/resolvers.py",
        ],
        "ground_truth_structural": ["django/core/handlers/base.py"],
        "ground_truth_behavioral": ["django/urls/resolvers.py"],
        "ground_truth_symbols": [
            "BaseHandler.get_response",
            "BaseHandler._get_response",
            "BaseHandler.resolve_request",
            "URLResolver.resolve",
        ],
        "expected_subsystem": "core.handlers",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "django_task8_middleware_config_driven",
        "repo": "django",
        "query": "How does Django decide which middleware classes run on every request, and where does that list come from?",
        "category": "H",
        # Confirmed: django/core/handlers/base.py:27 `load_middleware`
        # docstring: "Populate middleware lists from settings.MIDDLEWARE."
        # Line 41: `for middleware_path in reversed(settings.MIDDLEWARE):`
        # -- the middleware chain composition is entirely driven by a
        # user-configured settings value (a plain list of import-path
        # strings), not visible in a static call graph without reading
        # settings.
        "ground_truth_files": ["django/core/handlers/base.py"],
        "ground_truth_structural": ["django/core/handlers/base.py"],
        "ground_truth_behavioral": [],
        "ground_truth_symbols": ["BaseHandler.load_middleware"],
        "expected_subsystem": "core.handlers",
        "expected_traversal_depth": 0,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "django_task9_admin_uses_forms_metaclass",
        "repo": "django",
        "query": "How does Django's admin ModelAdmin/BaseModelAdmin class relate to the forms framework's media-handling metaclass?",
        "category": "E",
        # Confirmed: django/contrib/admin/options.py:177 `class
        # BaseModelAdmin(metaclass=forms.MediaDefiningClass)` -- a real
        # cross-file relationship: admin/options.py's class directly uses
        # a metaclass defined in forms/widgets.py (line 306), not
        # same-directory adjacency (admin/ vs forms/ are sibling
        # django/contrib and django/ top-level packages).
        "ground_truth_files": [
            "django/contrib/admin/options.py",
            "django/forms/widgets.py",
        ],
        "ground_truth_structural": ["django/contrib/admin/options.py"],
        "ground_truth_behavioral": ["django/forms/widgets.py"],
        "ground_truth_symbols": ["BaseModelAdmin", "MediaDefiningClass"],
        "expected_subsystem": "contrib.admin",
        "expected_traversal_depth": 1,
        "ambiguity_expected": False,
        "ambiguity_note": None,
        "negative": False,
    },
    {
        "id": "django_task10_negative_graphql_websocket",
        "repo": "django",
        "query": "How does Django implement native GraphQL schema resolution and a built-in WebSocket consumer subsystem?",
        "category": "L",
        # Confirmed absent: grep -rl "GraphQLSchema|KafkaConsumer|
        # WebSocketConsumer" django/ -> 0 matches. Django ships no native
        # GraphQL or WebSocket support (those are separate third-party
        # packages, e.g. graphene-django/channels, not in this repo).
        # Tests false-positive behavior per the plan's negative-query
        # methodology.
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
