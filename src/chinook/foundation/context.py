from dataclasses import dataclass


@dataclass
class CustomerContext:
    customer_id: int | None = None
