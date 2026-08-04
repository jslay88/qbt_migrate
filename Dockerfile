ARG PYTHON_VERSION="3.14"

FROM python:${PYTHON_VERSION}-alpine AS build
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY pyproject.toml README.md LICENSE.md ./
COPY qbt_migrate ./qbt_migrate
# Plain PEP 517 install into a prefix we can copy out, so pip, flit, and the
# sources stay out of the runtime image.
RUN pip install --prefix=/install .

FROM python:${PYTHON_VERSION}-alpine
LABEL org.opencontainers.image.title="qbt_migrate" \
      org.opencontainers.image.description="Migrate qBittorrent downloads" \
      org.opencontainers.image.source="https://github.com/jslay88/qbt_migrate" \
      org.opencontainers.image.licenses="MIT"
ENV BT_BACKUP_PATH=/tmp/BT_backup \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY --from=build /install /usr/local
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# The mounted BT_backup has to be writable by whoever runs the container, and
# that is the host's uid. Left as root by default for that reason, override
# with `docker run --user` when the mount permits it.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
