from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from click import echo
from dbxs.dbapi_async import AsyncConnectable


from .cli import transaction
from .schema_builder import SchemaBuilder

if TYPE_CHECKING:
    # SponsorStorage is a protocol, therefore only used at type-check time.
    from .database import SponsorStorage

builder = SchemaBuilder()

class GratitudeDescriber(Protocol):
    async def describeGratitude(
        self,
        storage: SponsorStorage,
        timestamp: float,
        gratitudeID: str,
    ) -> None:
        ...

    def descriptionString(self) -> str:
        ...

@builder.table("sponsor")
@dataclass
class Sponsor:
    storage: SponsorStorage = field(repr=False)

    name: str
    builder.column("name TEXT NOT NULL")

    level: int
    builder.column("level INTEGER NOT NULL")

    current: int = None  # type:ignore[assignment]
    # `current` is only None in the window between instantiation and
    # __post_init__.  It defaults to being the same value as `level`.
    builder.column("current INTEGER NOT NULL")

    id: str = field(default_factory=lambda: str(uuid4()))
    builder.column("id uuid PRIMARY KEY NOT NULL")

    def __post_init__(self) -> None:
        if self.current is None:
            self.current = self.level

    async def save(self) -> None:
        await self.storage.saveSponsor(
            id=self.id, name=self.name, level=self.level, current=self.current
        )

    async def thank(self, timestamp: float, describer: GratitudeDescriber) -> None:
        gratitudeID = str(uuid4())
        await self.storage.addGratitude(
            id=gratitudeID,
            sponsor_id=self.id,
            timestamp=timestamp,
            description=describer.descriptionString(),
        )
        await describer.describeGratitude(self.storage, timestamp, gratitudeID)
        self.current -= 1
        await self.save()


@builder.table("gratitude")
@dataclass
class Gratitude:
    storage: SponsorStorage = field(repr=False)
    id: str
    builder.column("id UUID NOT NULL")

    sponsor_id: str
    builder.column("sponsor_id UUID NOT NULL")

    timestamp: float
    builder.column("timestamp REAL NOT NULL")

    description: str
    builder.column("description TEXT NOT NULL")

    builder.constraint("FOREIGN KEY (sponsor_id) REFERENCES sponsor(id)")


@builder.table("precommit")
@dataclass
class CommitRecord:
    storage: SponsorStorage

    gratitudeID: str
    builder.column("gratitude_id UUID NOT NULL")

    commitMessage: str
    builder.column("commit_message TEXT NOT NULL")

    workingDirectory: str
    builder.column("working_directory TEXT NOT NULL")

    preMessagePath: str
    builder.column("pre_message_path TEXT")

    commitSource: str | None
    builder.column("commit_source TEXT")

    commitObject: str | None
    builder.column("commit_object TEXT")

    parentCommit: str
    builder.column("parent_commit TEXT NOT NULL")

    builder.constraint("FOREIGN KEY (gratitude_id) REFERENCES gratitude(id)")


@dataclass
class CommitDescriber:
    userMessage: str
    preMessagePath: str
    workingDirectory: str
    commitSource: str | None
    commitObject: str | None
    parentCommit: str

    def descriptionString(self) -> str:
        return f"commit from {self.workingDirectory}"

    async def describeGratitude(
        self,
        storage: SponsorStorage,
        timestamp: float,
        gratitudeID: str,
    ) -> None:
        await storage.addCommit(
            gratitudeID,
            self.userMessage,
            self.workingDirectory,
            self.preMessagePath,
            self.commitSource,
            self.commitObject,
            self.parentCommit,
        )


@dataclass
class StringDescriber:
    string: str

    def descriptionString(self) -> str:
        return self.string

    async def describeGratitude(
        self,
        storage: SponsorStorage,
        timestamp: float,
        gratitudeID: str,
    ) -> None:
        ...


async def patrons(driver: AsyncConnectable, howMany: int, describer: GratitudeDescriber) -> str:
    from sponcom.cli import SponsorAccessor

    for repeat in range(2):
        async with transaction(driver) as t:
            names = []
            timestamp = time()
            acc = SponsorAccessor(t)
            async for sponsor in acc.draw(howMany):
                await sponsor.thank(timestamp, describer)
                names.append(sponsor.name)
            if names:
                if len(names) > 1:
                    names[-1] = "and " + names[-1]
                return (", " if len(names) > 2 else " ").join(names)
            else:
                await acc.fullReset()
                echo("* resetting")

    return "just me"


