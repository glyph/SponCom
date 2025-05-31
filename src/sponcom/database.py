from typing import AsyncIterable, Protocol

from dbxs import many, maybe, one, query, statement

from sponcom.models import ThanksScore

from .models import CommitRecord, Gratitude, Sponsor


class SponsorStorage(Protocol):
    """
    Storage for sponsors.
    """

    @query(
        sql="""
        SELECT name, level, current, id
        FROM sponsor;
        """,
        load=many(Sponsor),
    )
    def sponsors(self) -> AsyncIterable[Sponsor]: ...

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
    ) -> None: ...

    @statement(
        sql="UPDATE sponsor SET level = {newLevel} WHERE id = {sponsorID}",
    )
    async def setSponsorLevel(self, sponsorID: str, newLevel: int) -> None: ...

    @statement(
        sql="""
            INSERT INTO relevel
            (sponsor_id, timestamp, description, previous_level, new_level)
            VALUES
            ({sponsorID}, {when}, {why}, {old}, {new})
            """,
    )
    async def recordLevelChange(
        self, sponsorID: str, when: float, old: int, new: int, why: str
    ) -> None: ...

    @query(
        sql="""
        SELECT name, level, current, id
        FROM sponsor
        WHERE id = {id};
        """,
        load=one(Sponsor),
    )
    async def sponsorByID(self, id: str) -> Sponsor: ...

    @query(
        sql="""
        SELECT name, level, current, id
        FROM sponsor
        WHERE current > 0
            AND id not in (
                SELECT sponsor.id FROM gratitude
                JOIN sponsor ON
                    (gratitude.sponsor_id = sponsor.id)
                WHERE timestamp = (select max(timestamp) from gratitude)
            )
        ORDER BY random()
        LIMIT {limit};
        """,
        load=many(Sponsor),
    )
    def draw(self, limit: int) -> AsyncIterable[Sponsor]: ...

    @query(
        sql="""
        SELECT name, level, current, id
        FROM sponsor
        WHERE name = {name}
        """,
        load=one(Sponsor),
    )
    async def sponsorByName(self, name: str) -> Sponsor: ...

    @query(
        sql="""
        SELECT id, sponsor_id, timestamp, description
        FROM gratitude
        ORDER BY timestamp ASC
        """,
        load=many(Gratitude),
    )
    def listGratitude(self) -> AsyncIterable[Gratitude]: ...

    @statement(
        sql="""
        INSERT INTO gratitude(id, sponsor_id, timestamp, description)
        VALUES ({id}, {sponsor_id}, {timestamp}, {description})
        """
    )
    async def addGratitude(
        self, id: str, sponsor_id: str, timestamp: float, description: str
    ) -> None: ...

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
    ) -> None: ...

    @statement(sql="UPDATE sponsor SET current = current + level")
    async def fullReset(self) -> None: ...

    @statement(
        sql="""
        INSERT INTO imported_gratitude
        (gratitude_id, timestamp, processed)
        VALUES
        ({gratitudeID}, {timestamp}, false)
        """
    )
    async def markGratitudeImport(self, gratitudeID: str, timestamp: float) -> None: ...

    @query(
        sql="""
        SELECT sponsor.name, count(gratitude.id)
        FROM sponsor
        JOIN gratitude ON sponsor.id=sponsor_id
        GROUP BY sponsor.id
        ORDER BY count(gratitude.id) DESC
        LIMIT {n}
        """,
        load=many(ThanksScore),
    )
    def topSponsors(self, n: int) -> AsyncIterable[ThanksScore]: ...

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
    async def commitForGratitude(self, gratitude_id: str) -> CommitRecord | None: ...
