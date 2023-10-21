from __future__ import annotations

import sqlite3
from datetime import datetime
from functools import wraps
from os import popen
from pathlib import Path
from sys import argv
from textwrap import dedent, wrap
from typing import Callable, Concatenate, Coroutine, Literal, ParamSpec, TypeVar

from click import ClickException, argument, echo, group
from dbxs import accessor
from dbxs.dbapi_async import adaptSynchronousDriver, transaction
from twisted.internet.defer import Deferred
from twisted.internet.task import react

from sponcom.database import SponsorStorage
from sponcom.models import CommitDescriber, Sponsor, StringDescriber, builder, patrons
from sponcom.schema_builder import SchemaBuilder

# This should probably go in a configuration file.  Maybe a template?
creatorURL = "https://patreon.com/creatorglyph"
T = TypeVar("T")


SponsorAccessor = accessor(SponsorStorage)


def sqliteWithSchema(builder: SchemaBuilder) -> Callable[[], sqlite3.Connection]:
    def _() -> sqlite3.Connection:
        connection = sqlite3.connect(str(Path("~/.sponcom-v1.sqlite").expanduser()))
        connection.executescript(builder.schema)
        return connection

    return _


driver = adaptSynchronousDriver(
    sqliteWithSchema(builder),
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
                echo(f"    commit in {commit.workingDirectory} ({commit.parentCommit})")


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
@main.command(hidden=True)

# It takes one to three parameters.

@argument("premessagepath")
# The first is the name of the file that contains the commit log message.

@argument("commitsource", default=None, required=False)
# The second is the source of the commit message, and can be:

# - message (if a -m or -F option was given);

# - template (if a -t option was given or the configuration option
#   commit.template is set);

# - merge (if the commit is a merge or a .git/MERGE_MSG file exists);

# - squash (if a .git/SQUASH_MSG file exists); or

# - commit, followed by a commit object name (if a -c, -C or --amend option was
#   given).

@argument("commitobject", default=None, required=False)
# If the second argument is 'commit', then the third will be a commit object
# name (if a -c, -C or --amend option was given).

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

        with popen("git rev-parse HEAD") as gitProcess:
            parentCommit = gitProcess.read().strip()

        patronText = await patrons(
            driver,
            3,
            CommitDescriber(
                userMessage,
                premessagepath,
                str(Path.cwd().absolute()),
                commitsource,
                commitobject,
                parentCommit,
            ),
        )
        msg = wrap(
            dedent(
                f"""\
                This commit was sponsored by {patronText}, and my other
                patrons.  If you want to join them, you can support my work at
                {creatorURL}.
                """
            )
        )

        if userMessage[-1:] != "\n":
            f.write("\n\n")
        elif userMessage[-2:] != "\n\n":
            f.write("\n")

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


@main.command()
@argument("description")
@argument("number", type=int, default=3)
@reactive
async def thank(reactor: object, description: str, number: int) -> None:
    echo(await patrons(driver, number, StringDescriber(description)))
