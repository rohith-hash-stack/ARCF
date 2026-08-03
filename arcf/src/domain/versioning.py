"""Living Contract — versioned envelope around a Contract snapshot.

Maps to the diagram's "Living Contract (Versioned)" box and the Phase 3
deliverable "Versioned Execution Contract". Each evolution produces a new
immutable LivingContract: version increments, lineage records the prior
contract snapshot's id, and updated_at advances while created_at is
preserved from the first version. This is what later becomes a LangGraph
checkpoint (Phase 10) and an Execution Ledger entry (Phase 9).

contract_id identifies the whole version lineage and is preserved by
evolve() — it is the stable handle a caller persists/looks up by (e.g.
GET /api/v1/contracts/{contract_id}). This is distinct from
contract.id, which identifies one immutable snapshot's content and
changes on every version — Phase 3's persistence layer needs the
former; lineage tracking needs the latter.
"""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from domain.contract import Contract
from domain.enums import ContractStatus
from shared import utc_now


class LivingContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract_id: UUID = Field(default_factory=uuid4)
    contract: Contract
    version: int = Field(default=1, ge=1)
    status: ContractStatus = ContractStatus.DRAFT
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    lineage: list[UUID] = Field(default_factory=list)

    def evolve(
        self, contract: Contract, status: ContractStatus | None = None
    ) -> "LivingContract":
        return LivingContract(
            contract_id=self.contract_id,
            contract=contract,
            version=self.version + 1,
            status=status if status is not None else self.status,
            created_at=self.created_at,
            updated_at=utc_now(),
            lineage=[*self.lineage, self.contract.id],
        )
