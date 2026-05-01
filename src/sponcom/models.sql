CREATE TABLE IF NOT EXISTS sponsor (
  name TEXT NOT NULL,
  level INTEGER NOT NULL,
  current INTEGER NOT NULL,
  id uuid PRIMARY KEY NOT NULL
);

-- sponsors(...)
SELECT name, level, current, id FROM sponsor;

-- saveSponsor(...)
INSERT INTO sponsor(id, name, level, current)
VALUES({id}, {name}, {level}, {current})
       ON CONFLICT(sponsor.id)
       DO UPDATE SET
       (name, level, current) =
       (EXCLUDED.name, EXCLUDED.level, EXCLUDED.current);


-- setSponsorLevel(...)
UPDATE sponsor SET level = {newLevel} WHERE id = {sponsorID}
