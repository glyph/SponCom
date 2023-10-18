from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from pathlib import Path
from sys import argv
from textwrap import dedent, wrap
from time import time
from typing import (AsyncIterable, Callable, Concatenate, Coroutine, Literal,
                    ParamSpec, Protocol)
from uuid import uuid4

from click import ClickException, argument, echo, group
from dbxs import accessor, many, maybe, one, query, statement
from dbxs.dbapi_async import adaptSynchronousDriver, transaction
from twisted.internet.defer import Deferred
from twisted.internet.task import react

schema = """

CREATE TABLE IF NOT EXISTS sponsor (
    id uuid PRIMARY KEY NOT NULL,
    name text NOT NULL,
    level integer NOT NULL,
    current integer NOT NULL
);

CREATE TABLE IF NOT EXISTS gratitude (
    id UUID NOT NULL,
    sponsor_id UUID NOT NULL,
    timestamp REAL NOT NULL,
    description TEXT NOT NULL,

    FOREIGN KEY (sponsor_id) REFERENCES sponsor(id)
);

CREATE TABLE IF NOT EXISTS precommit (
    gratitude_id UUID NOT NULL,
    commit_message TEXT NOT NULL,
    working_directory TEXT NOT NULL,
    pre_message_path TEXT,
    commit_source TEXT,
    commit_object TEXT,

    FOREIGN KEY (gratitude_id) REFERENCES gratitude(id)
);

"""


@dataclass
class Gratitude:
    storage: SponsorStorage = field(repr=False)
    id: str
    sponsor_id: str
    timestamp: float
    description: str


@dataclass
class Sponsor:
    storage: SponsorStorage = field(repr=False)
    name: str
    level: int
    current: int = None  # type:ignore[assignment]
    id: str = field(default_factory=lambda: str(uuid4()))

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


@dataclass
class CommitRecord:
    storage: SponsorStorage
    gratitudeID: str
    commitMessage: str
    workingDirectory: str
    preMessagePath: str
    commitSource: str | None
    commitObject: str | None

class SponsorStorage(Protocol):
    """
    Storage for sponsors.
    """

    @query(
        sql="""
        select name, level, current from sponsor;
        """,
        load=many(Sponsor),
    )
    def sponsors(self) -> AsyncIterable[Sponsor]:
        ...

    @statement(
        sql="""
        INSERT INTO sponsor(id, name, level, current)
        VALUES({id}, {name}, {level}, {current})
        ON CONFLICT(sponsor.id)
        DO UPDATE SET
        (name, level, current) =
        (EXCLUDED.name, EXCLUDED.level, EXCLUDED.current)
        """
    )
    async def saveSponsor(
        self,
        id: str,
        name: str,
        level: int,
        current: int,
    ) -> None:
        ...

    @query(
        sql="""
        SELECT name, level, current FROM sponsor WHERE id = {id};
        """,
        load=one(Sponsor),
    )
    async def sponsorByID(self, id: str) -> Sponsor:
        ...

    @query(
        sql="""
        SELECT name, level, current, id FROM sponsor
        WHERE current > 0
        ORDER BY random()
        LIMIT {limit};
        """,
        load=many(Sponsor),
    )
    def draw(self, limit: int) -> AsyncIterable[Sponsor]:
        ...

    @query(
        sql="""
        SELECT id, sponsor_id, timestamp, description
        FROM gratitude
        ORDER BY timestamp ASC
        """,
        load=many(Gratitude),
    )
    def listGratitude(self) -> AsyncIterable[Gratitude]:
        ...

    @statement(
        sql="""
        INSERT INTO gratitude(id, sponsor_id, timestamp, description)
        VALUES ({id}, {sponsor_id}, {timestamp}, {description})
        """
    )
    async def addGratitude(
        self, id: str, sponsor_id: str, timestamp: float, description: str
    ) -> None:
        ...

    @statement(
        sql="""
        INSERT INTO precommit (gratitude_id, commit_message, working_directory,
                               pre_message_path, commit_source, commit_object)
        VALUES ({gratitude_id}, {userMessage}, {workingDirectory},
                {preMessagePath}, {commitSource}, {commitObject})
        """
    )
    async def addCommit(
        self,
        gratitude_id: str,
        userMessage: str,
        workingDirectory: str,
        preMessagePath: str,
        commitSource: str | None,
        commitObject: str | None,
    ) -> None:
        ...

    @statement(
        sql="""
        update sponsor set current = level;
        """,
    )
    async def fullReset(self) -> None:
        ...

    @query(
        sql="""
        SELECT gratitude_id, commit_message, working_directory, pre_message_path, commit_source, commit_object
        FROM precommit
        WHERE gratitude_id = {gratitude_id}
        """,
        load=maybe(CommitRecord),
    )
    async def commitForGratitude(self, gratitude_id: str) -> CommitRecord | None:
        ...


SponsorAccessor = accessor(SponsorStorage)


def schemaed() -> sqlite3.Connection:
    connection = sqlite3.connect(str(Path("~/.sponcom-v1.sqlite").expanduser()))
    connection.executescript(schema)
    return connection


driver = adaptSynchronousDriver(
    schemaed,
    sqlite3.paramstyle,
)


@group()
def main() -> None:
    """
    Sponsored Commit message generator.
    """


P = ParamSpec("P")


def reactive(
    thunk: Callable[Concatenate[object, P], Coroutine[Deferred[object], object, object]]
) -> Callable[P, None]:
    @wraps(thunk)
    def cmd(*args, **kw) -> None:
        react(lambda reactor: thunk(reactor, *args, **kw))

    return cmd


@main.command()
@reactive
async def list(reactor: object) -> None:
    async with transaction(driver) as t:
        db = SponsorAccessor(t)
        async for sponsor in db.sponsors():
            echo(f"{sponsor.current=} {sponsor.name=} {sponsor.level=} {sponsor.id=}")


@main.command()
@reactive
async def history(reactor: object) -> None:
    async with transaction(driver) as t:
        db = SponsorAccessor(t)
        async for gratitude in db.listGratitude():
            sponsor = await db.sponsorByID(gratitude.sponsor_id)
            isotime = (
                datetime.fromtimestamp(gratitude.timestamp).astimezone().isoformat()
            )
            echo(f"{isotime} {sponsor.name!r} {gratitude.description!r}")
            commit = await db.commitForGratitude(gratitude.id)
            if commit is not None:
                echo(f"    commit in {commit.workingDirectory}")


@main.command()
@argument("name")
@argument("level", type=int)
@reactive
async def add(reactor: object, name: str, level: int) -> None:
    async with transaction(driver) as t:
        # print(f"adding sponsor <{name}> at <{level}>")
        await Sponsor(SponsorAccessor(t), name, level).save()
        echo("saved!")


# This is the git prepare-commit-message hook.

# It takes one to three parameters.


@main.command(hidden=True)

# The first is the name of the file that contains the commit log message.


@argument("premessagepath")

# The second is the source of the commit message, and can be:


@argument("commitsource", default=None, required=False)

# - message (if a -m or -F option was given);

# - template (if a -t option was given or the configuration option
#   commit.template is set);

# - merge (if the commit is a merge or a .git/MERGE_MSG file exists);

# - squash (if a .git/SQUASH_MSG file exists); or

# - commit, followed by a commit object name (if a -c, -C or --amend option was
#   given).


@argument("commitobject", default=None, required=False)
@reactive
async def prepare(
    reactor: object,
    premessagepath: str,
    commitsource: Literal["message", "template", "merge", "squash", "commit"] | None,
    commitobject: str | None = None,
) -> None:
    """
    Git prepare-commit-message hook.
    """
    import os
    from pprint import pformat

    echo(pformat(dict(os.environ)))
    with Path(premessagepath).open("r+") as f:
        userMessage = f.read()
        # f.write(
        #     f"\n\n# Debug: {premessagepath!r}, {commitsource!r}, {commitobject!r}\n"
        # )
        c = await contributors(
            3,
            CommitDescriber(
                userMessage,
                premessagepath,
                str(Path.cwd().absolute()),
                commitsource,
                commitobject,
            ),
        )
        msg = wrap(
            dedent(
                f"""\
                This commit was sponsored by {c}, and my other patrons.
                If you want to join them, you can support my work at
                https://patreon.com/creatorglyph.
                """
            )
        )
        f.write("\n".join(msg))


@main.command()
def install() -> None:
    gitdir = Path(".git")
    if not gitdir.is_dir():
        raise ClickException("Not in a git repository root.")
    hooksdir = gitdir / "hooks"
    hooksdir.mkdir(mode=0o755, parents=False, exist_ok=True)
    hookpath = hooksdir / "prepare-commit-msg"
    with hookpath.open("w") as f:
        f.write(
            dedent(
                f"""\
                #!/bin/sh
                exec '{argv[0]}' prepare "$@";
                """
            )
        )
    hookpath.chmod(0o755)
    echo(f"installed {hookpath}")


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


@dataclass
class CommitDescriber:
    userMessage: str
    preMessagePath: str
    workingDirectory: str
    commitSource: str | None
    commitObject: str | None

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

async def contributors(howMany: int, describer: GratitudeDescriber) -> str:
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

    assert False, "this should be unreachable"


@main.command()
@argument("description")
@argument("number", type=int, default=3)
@reactive
async def thank(reactor: object, description: str, number: int) -> None:
    echo(await contributors(number, StringDescriber(description)))
