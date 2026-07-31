from domain.artifact import Artifact
from domain.enums import ArtifactKind


def test_artifact_generates_id_and_timestamp_by_default() -> None:
    a = Artifact(kind=ArtifactKind.CODE_CHANGE, content="diff --git a/x b/x")
    b = Artifact(kind=ArtifactKind.CODE_CHANGE, content="diff --git a/y b/y")
    assert a.id != b.id
    assert a.created_at is not None


def test_artifact_optional_fields_default() -> None:
    a = Artifact(kind=ArtifactKind.EXPLANATION, content="Renamed foo to bar.")
    assert a.path is None
    assert a.metadata == {}
