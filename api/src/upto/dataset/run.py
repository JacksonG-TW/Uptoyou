"""Write the dataset into a directory and print what was written.

    python -m upto.dataset.run <directory>

**Its whole output contract is three `dataset:` lines**, because the caller is a shell-out from a
DAG and parsing a log is how a job learns what happened. The DAG reads `publication` and `rows`;
the third line is for a person.

**The row count is asserted here, not by the caller.** `place`'s own count of reference rows is read
in the same session and compared with the rows written. A partial write produces a smaller file that
looks exactly like a working export — the one failure a dataset job has that nobody notices — so the
mismatch raises before anything is uploaded, and the two numbers are both printed either way.

Run by hand against the development database:

    docker compose run --rm tests python -m upto.dataset.run /tmp/ds
"""

from __future__ import annotations

import asyncio
import os
import sys

from . import export


async def main(directory: str) -> int:
    from ..db import session_factory  # noqa: PLC0415

    async with session_factory()() as session:
        rows = await export.rows_for(session)
        expected = await export.expected_count(session)
        provenance = await export.publications_in_force(session)

    publication = provenance["place_publication_id"]
    os.makedirs(directory, exist_ok=True)
    parquet = os.path.join(directory, "places.parquet")
    written = export.write_parquet(rows, parquet)

    print("dataset: publication={}".format(publication))
    print("dataset: rows={}".format(written))
    print("dataset: expected={}".format(expected))

    if written != expected:
        # **Loud, and before the upload.** A dataset that is quietly short is believed.
        print(
            "dataset: ROW COUNT MISMATCH — wrote {} rows and `place` holds {} reference rows. "
            "Nothing should be uploaded from this run.".format(written, expected),
            file=sys.stderr,
        )
        return 2

    with open(os.path.join(directory, "dictionary.md"), "w", encoding="utf-8") as handle:
        handle.write(export.dictionary_markdown(publication, written))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        raise SystemExit(64)
    raise SystemExit(asyncio.run(main(sys.argv[1])))
