from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from os import umask
from pathlib import Path
from sys import argv
from textwrap import dedent, wrap
from time import time
from typing import (AsyncIterable, Callable, Concatenate, Coroutine, Literal,
                    ParamSpec, Protocol)
from uuid import uuid4

from click import ClickException, argument, echo, group
from dbxs import accessor, many, one, query, statement
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

    async def thank(self, id: str, description: str, timestamp: float) -> None:
        await self.storage.addGratitude(
            id=id,
            sponsor_id=self.id,
            timestamp=timestamp,
            description=description,
        )
        self.current -= 1


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
        insert into sponsor(id, name, level, current)
        values({id}, {name}, {level}, {current})
        ON CONFLICT(sponsor.id)
        DO UPDATE SET
        (name, level, current) =
        (excluded.name, excluded.level, excluded.current)
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
        select name, level, current from sponsor where id = {id};
        """,
        load=one(Sponsor),
    )
    async def sponsorByID(self, id: str) -> Sponsor:
        ...

    @query(
        sql="""
        select name, level, current, id from sponsor
        where current > 0
        order by random()
        limit {limit};
        """,
        load=many(Sponsor),
    )
    def draw(self, limit: int) -> AsyncIterable[Sponsor]:
        ...

    @query(
        sql="""
        select id, sponsor_id, timestamp, description
        from gratitude
        order by timestamp asc
        """,
        load=many(Gratitude),
    )
    def listGratitude(self) -> AsyncIterable[Gratitude]:
        ...

    @statement(
        sql="""
        insert into gratitude(id, sponsor_id, timestamp, description)
        values ({id}, {sponsor_id}, {timestamp}, {description})
        """
    )
    async def addGratitude(
        self, id: str, sponsor_id: str, timestamp: float, description: str
    ) -> None:
        ...

    @statement(
        sql="""
        update sponsor set current = level;
        """,
    )
    async def fullReset(self) -> None:
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
            isotime = datetime.fromtimestamp(gratitude.timestamp).astimezone().isoformat()
            echo(f"{isotime} {sponsor.name!r} {gratitude.description!r}")

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


@main.command()

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
    with Path(premessagepath).open("a+") as f:
        # f.write(
        #     f"\n\n# Debug: {premessagepath!r}, {commitsource!r}, {commitobject!r}\n"
        # )
        c = await contributors(3, description=f"commit {commitsource} {commitobject}")
        msg = wrap(dedent(f"""\
        This commit was sponsored by my patrons {c}.  If you want to join them,
        you can support my work at https://patreon.com/creatorglyph.
        """))
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


async def contributors(howMany: int, description: str) -> str:
    for repeat in range(2):
        async with transaction(driver) as t:
            names = []
            gratitudeID = str(uuid4())
            timestamp = time()
            acc = SponsorAccessor(t)
            async for sponsor in acc.draw(howMany):
                await sponsor.thank(gratitudeID, description, timestamp)
                await sponsor.save()
                names.append(sponsor.name)
            if names:
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
    echo(contributors(number, description))
