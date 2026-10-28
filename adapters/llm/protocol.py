"""Provider-neutral structured-action port and explicitly offline protocol test double.

A real service implementation must be installed by trusted code after service/data/credential
authorization. No live vendor adapter is installed or represented as tested in E7.
"""

from dataclasses import dataclass
from typing import Callable, Protocol

from packages.transport.security import canonical


@dataclass(frozen=True)
class ModelReply:
    output: str
    input_tokens: int
    output_tokens: int
    usage_source: str


class ModelAdapter(Protocol):
    model_id: str
    test_kind: str

    def complete(self, request: dict, *, output_limit: int, check: Callable[[], None]) -> ModelReply:
        """Must honor output_limit and call check during waits; never execute tools itself."""
        ...


class ProtocolTestAdapter:
    """Exercises the actual guard and persistence, never claims to be an external model."""

    model_id = "protocol-test/actions-v1"
    test_kind = "protocol_test_double"

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.requests = []

    def complete(self, request, *, output_limit, check):
        check()
        self.requests.append(request)
        value = next(self.outputs)
        output = value if isinstance(value, str) else canonical(value)
        check()
        return ModelReply(
            output=output,
            input_tokens=len(canonical(request).encode()),
            output_tokens=len(output.encode()),
            usage_source="protocol_test_utf8_units_not_vendor_tokens",
        )
