# Airflow carries the ingest code in the image rather than bind-mounting it.
#
# A bind mount would be faster to iterate on and would need an SELinux :z label on the
# development machine to be readable at all. The deciding reason is the other one: §6 grades
# `docker compose up` on a machine that has never seen this repository, and an image that
# already contains what it runs is the version of that which cannot half-work.
# **3.0.6 since 2026-10-07 (owner, the combined deploy; H102).** 3.0.2 leaked one file descriptor
# per task run in the LocalExecutor worker (fixed in 3.0.3, #51654) and could not run a task failure
# callback in the DAG processor at all (`NotImplementedError`, gone from 3.0.4) — between them they
# stopped every scheduled job on dev and wedged four DAGs on the box. One metadata migration between
# the two (`0069_3_0_3_delete_import_errors`); `airflow-init` runs it.
FROM apache/airflow:3.0.6

# The ingest runs in its own interpreter, and this is a dependency conflict rather than a
# preference. Airflow 3 pins SQLAlchemy below 2.0; the ingest uses 2.0's async session, which
# exists because H1 forbids a synchronous driver anywhere near this project. Installing 2.0
# into Airflow's own environment would break Airflow. A venv keeps both true, and it is the
# arrangement Airflow documents for exactly this case.
#
# **`pyarrow` joins them for the dataset export (2026-09-12).** pyarrow 25.0.1, **Apache-2.0**,
# requires Python >= 3.10 — PyPI, read 2026-09-12. It lives **here and not in the api image**: the
# wheel is 50.1 MB compressed and the serving image is 287 MB, so it would grow the thing the box
# pulls and serves from by roughly half, for a library the server never imports. This image is
# 2.57 GB, where the same library is under 6%.
COPY --chown=airflow:root api/requirements.txt /opt/upto/requirements.txt
RUN python -m venv /opt/upto/venv \
    && /opt/upto/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/upto/venv/bin/pip install --no-cache-dir \
         "sqlalchemy[asyncio]==2.0.43" "asyncpg==0.30.0" "pyarrow==25.0.1"

ENV UPTO_PYTHON=/opt/upto/venv/bin/python \
    UPTO_SRC=/opt/upto/src \
    PYTHONDONTWRITEBYTECODE=1

# The mount point for the airflow-auth volume, created here rather than left to Docker. A
# named volume mounted on a path the image does not have is created root-owned, and every
# Airflow process runs as `airflow` — the failure is a PermissionError on the password file
# at api-server start. Made by the image, the empty volume inherits this ownership instead.
RUN mkdir -p /opt/airflow/auth

COPY --chown=airflow:root api/src /opt/upto/src
COPY --chown=airflow:root airflow/dags /opt/airflow/dags

# **A11 ⑤ — `USER airflow` stated, though it was already true. Owner-ruled 2026-08-19.**
#
# `apache/airflow:3.0.2` (and 3.0.6, re-checked at the bump) already ends on `USER airflow` (uid 50000), and nothing above switches to
# root, so every `RUN` here and every process in the three airflow containers already ran unprivileged
# — verified with `docker top`, not assumed. This line therefore changes no behaviour today. It is
# here because the property is load-bearing and currently held by a *base image's* last directive: a
# future `USER root` for one `apt-get`, or a base-image bump that reorders its own tail, would drop it
# silently and nothing would say so. Stating it makes the guarantee this file's own.
USER airflow
