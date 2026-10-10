# Built with app/ as its context, not proxy/, because the image needs both the nginx
# config and the front end and those are siblings. `dockerfile:` in compose names this
# file; `.dockerignore` at app/ keeps the wider context from carrying anything else.
#
# **Two stages since D104 (2026-08-18).** The surface was a vendored Vue global build with no
# build step; it is now Vite + React 19 + Tailwind 4, so something has to run `npm`. It runs
# here rather than on a developer's machine for the reason the old single stage existed: the
# image must be self-contained on a machine that has never seen this repository, which is the
# scenario §6 grades. Nothing about the front end is bind-mounted, and a change under `web/`
# is invisible to the running stack until this image is rebuilt (H28).

# ---- the build stage -------------------------------------------------------------------
#
# **`node:22-alpine`, the major pinned and nothing narrower.** Vite 7+ needs Node 20.19+ or
# 22.12+, so 22 is the lowest current LTS that clears it and is in maintenance until 2027-04.
# **Rejected: pinning by digest** — reproducible, and it makes a security patch a manual edit
# in this file, while the thing that actually needs pinning is the dependency tree, which
# `npm ci` against the committed `package-lock.json` already does exactly. **Rejected:
# `node:24`** — newer with no benefit any dependency here asks for. Agreed with the frontend
# session, which runs its own npm commands through this same image so the lockfile it commits
# was resolved by the toolchain this stage uses; "works locally, fails in the image" is not a
# category that can arise from a version skew.
FROM node:22-alpine AS build
WORKDIR /build

# **The manifests first, then `npm ci`, then the source.** Two layers on purpose: a
# source-only change re-runs the build and reuses the resolved tree, and only a change to
# `package.json` or the lockfile pays for resolution again.
#
# `npm ci` rather than `npm install`: it installs exactly the lockfile and fails if the two
# disagree, which is the difference between a pinned tree and a tree that was pinned once.
COPY web/package.json web/package-lock.json ./
RUN npm ci

# `web/node_modules` is excluded in `.dockerignore`, so this cannot bury the tree `npm ci`
# just installed — and without that exclusion the build context carries several hundred
# megabytes for nothing. The two lines belong together and neither is safe alone.
COPY web/ ./

# `npm run build` is `tsc -b && vite build`, and the type check is deliberately part of it:
# a surface that does not compile must not reach an image. Output lands in `dist/` at Vite's
# default, which is why this file does not name `build.outDir` — a Dockerfile should not
# depend on a value that could drift in `vite.config.ts`.
RUN npm run build

# ---- the served image ------------------------------------------------------------------
#
# **`nginxinc/nginx-unprivileged` since A11 ⑤ (owner-ruled 2026-08-19), not `nginx`.** The stock
# image starts its master process as root and only drops its workers to uid 101; this one runs the
# master as 101 too, so nothing in the container is root at any point. Same nginx, same version,
# same modules — it is the same source built with a different default user, pid path and listen
# port.
#
# **The consequence is a port, and it is not optional:** a non-root process cannot bind below 1024,
# so `proxy/upto.conf` listens on **8080** and `compose.yaml` maps `${UPTO_HTTP_PORT:-8080}:8080`.
# `FROM` unprivileged with `listen 80` does not fail to serve — it fails to *start*, before the log
# can name the port as the cause. The two lines are one change and neither is safe alone.
#
# **What is inherited and must stay writable:** the unprivileged image's own `nginx.conf` puts the
# pid at `/tmp/nginx.pid` and every temp path under `/tmp`. Only `conf.d/default.conf` is replaced
# here, so that arrangement is inherited untouched — which is the thing a later read-only-rootfs
# idea has to account for. Noted by the frontend session, 2026-08-19.
FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY proxy/upto.conf /etc/nginx/conf.d/default.conf
COPY proxy/security-headers.conf /etc/nginx/upto-security-headers.conf

# **`dist/` rather than `web/`.** `dist/fonts/` arrives verbatim from `web/public/fonts/`
# because Vite copies `publicDir` without hashing or rewriting, so the served URLs stay
# `/fonts/*.woff2` exactly as they were before a build step existed — which is what keeps
# `font_subset_check --shipped` checking a fixed filename rather than a hash it would have to
# look up in Vite's manifest.
COPY --from=build /build/dist /usr/share/nginx/html
