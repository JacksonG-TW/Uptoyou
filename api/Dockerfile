# The host runs Python 3.9, which is end of life. The container carries a current one —
# that split is deliberate and is why nothing here depends on the host interpreter.
#
# **Two stages since 2026-09-12, and the split is a measured one.** The dataset export writes
# Parquet and needs `pyarrow`, whose wheel is **50.1 MB compressed** and considerably more
# installed. This image is **287 MB** and the box pulls it and runs `api` and `migrate` from it, so
# adding pyarrow here would grow the serving image by roughly half for a library the server never
# imports. The airflow image, where the export actually runs, is 2.57 GB — the same library is
# under 6% there. So: `api` stays as it was, and only `tests` gets pyarrow, because the test has to
# write a real file and read it back rather than assert against a mock.
FROM python:3.13-slim AS base

# Fail fast and log immediately: a buffered stdout hides the startup error that matters.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/srv/src

WORKDIR /srv

# Requirements first, so a source edit does not reinstall the world.
COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt

COPY src /srv/src
COPY alembic.ini /srv/alembic.ini
COPY migrations /srv/migrations
COPY entrypoint.sh /srv/entrypoint.sh
# Tests travel with the image: the container is the canonical environment, so the place
# they must be runnable is inside it rather than only on a host that happens to work.
COPY tests /srv/tests

# Not root inside the container. The daemon itself is rootful (D10) because the success
# criterion is literally `docker compose up`, but that is no reason for the application
# process to be root as well.
RUN useradd --system --uid 10001 --no-create-home upto
USER 10001

EXPOSE 8000

ENTRYPOINT ["/srv/entrypoint.sh"]
CMD ["uvicorn", "upto.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]


# --- the serving image: `api`, `migrate`. Nothing added. -------------------------------------
FROM base AS api


# --- the test image: everything above, plus what a test needs and a server does not -----------
FROM base AS tests

USER root
# pyarrow 25.0.1, **Apache-2.0**, requires Python >= 3.10 (PyPI, read 2026-09-12). Pinned like
# every other dependency here: «it worked on my machine last week» is what `requirements.txt`
# prevents, and a format library that changes its defaults between minor versions would change
# what the shipped dataset IS.
RUN pip install --no-cache-dir "pyarrow==25.0.1"
USER 10001
