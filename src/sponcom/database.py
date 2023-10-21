

from typing import AsyncIterable, Protocol

from dbxs import many, maybe, one, query, statement

from .models import CommitRecord, Gratitude, Sponsor


class SponsorStorage(Protocol):
    """
    Storage for sponsors.
    """

    @query(
        sql="""
        SELECT
            name, level, current
        FROM sponsor;
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
        SELECT
            name, level, current
        FROM sponsor
        WHERE id = {id};
        """,
        load=one(Sponsor),
    )
    async def sponsorByID(self, id: str) -> Sponsor:
        ...

    @query(
        sql="""
        SELECT
            name, level, current, id
        FROM sponsor
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
        SELECT
            id, sponsor_id, timestamp, description
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
                               pre_message_path, commit_source, commit_object,
                               parent_commit)
        VALUES ({gratitudeID}, {userMessage}, {workingDirectory},
                {preMessagePath}, {commitSource}, {commitObject}, {parentCommit})
        """
    )
    async def addCommit(
        self,
        gratitudeID: str,
        userMessage: str,
        workingDirectory: str,
        preMessagePath: str,
        commitSource: str | None,
        commitObject: str | None,
        parentCommit: str,
    ) -> None:
        ...

    @statement(
        sql="""
        UPDATE sponsor
        SET current = level;
        """,
    )
    async def fullReset(self) -> None:
        ...

    @query(
        sql="""
        SELECT
            gratitude_id, commit_message, working_directory,
            pre_message_path, commit_source, commit_object,
            parent_commit
        FROM precommit
        WHERE gratitude_id = {gratitude_id}
        """,
        load=maybe(CommitRecord),
    )
    async def commitForGratitude(self, gratitude_id: str) -> CommitRecord | None:
        ...


