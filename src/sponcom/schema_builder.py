
from dataclasses import dataclass, field
from typing import Callable, TypeVar

T = TypeVar("T")
@dataclass
class SchemaBuilder:
    schema: str = ""
    pendingColumns: list[str] = field(default_factory=lambda: [])
    constraintsYet: bool = False

    def table(self, tableName: str) -> Callable[[T], T]:

        def buildSchema(c: T) -> T:
            pendingColumns, self.pendingColumns = self.pendingColumns, []
            sep = ",\n    "
            partialSchema = f"""
            CREATE TABLE IF NOT EXISTS {tableName} (
                {sep.join(pendingColumns)}
            );
            """
            self.schema += partialSchema
            c.__schema__ = partialSchema  # type:ignore
            return c

        return buildSchema

    def column(self, columnText: str) -> None:
        self.constraintsYet = False
        self.pendingColumns.append(columnText)

    def constraint(self, constraintText: str) -> None:
        if not self.constraintsYet:
            constraintText = f"\n    {constraintText}"
        self.constraintsYet = True
        self.pendingColumns.append(constraintText)


