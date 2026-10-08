# Stage 1: fetch the model and verify every file against its SHA-256
# (standard library only, see model.py).
# Base: Debian 13 "trixie", pinned by digest so every build starts from the
# same bits. Dependabot proposes updates (.github/dependabot.yml).
FROM python:3.13-slim-trixie@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c AS model
COPY wyoming_sittich/model.py /tmp/model.py
# Fixed permissions and timestamps, so the files are bit-identical in every
# build and the layer below keeps its digest across releases.
RUN python /tmp/model.py /model \
    && chmod 0755 /model && chmod 0644 /model/* \
    && touch -d @0 /model/* /model

# Stage 2: the server.
FROM python:3.13-slim-trixie@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c

# The model comes first and is linked as an independent layer: updates of
# Python, packages or code do not change it, so Home Assistant downloads the
# ~640 MB only once.
COPY --link --from=model /model /app/model

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
# Every package and every dependency is pinned with its hash; anything
# else, or a file that does not match, aborts the build.
RUN pip install --require-hashes --only-binary=:all: -r requirements.txt

COPY wyoming_sittich ./wyoming_sittich

ARG BUILD_VERSION=dev
ARG BUILD_ARCH=amd64
LABEL io.hass.name="Sittich" \
      io.hass.type="addon" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.arch="${BUILD_ARCH}"

EXPOSE 10300

HEALTHCHECK --interval=30s --timeout=5s --start-period=2m \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 10300), 3).close()"

ENTRYPOINT ["python", "-m", "wyoming_sittich"]
