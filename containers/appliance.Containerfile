# The appliance: systemd as PID 1, supervising PostgreSQL and the MCP server.
#
# Fedora rather than ubi9-init because UBI ships only the PostgreSQL *client*
# (13.x), not postgresql-server -- verified 2026-09-13.
#
# postgresql16-server, not the default (18.x): existing pgdata volumes hold a
# PG 16 cluster, and postgresql.service refuses to start on an older major
# version. Moving to a newer major needs a pg_upgrade (or `make clean`).
FROM quay.io/fedora/fedora:44

RUN dnf -y install --setopt=install_weak_deps=False \
        systemd postgresql16-server postgresql16 python3 python3-pip procps-ng iproute \
    && dnf clean all \
    && rm -rf /var/cache/dnf

# A container has no consoles, no login prompts and no hardware to probe.
# Stripping these shaves several seconds off boot and a lot of noise off logs.
RUN systemctl mask \
        systemd-logind.service \
        systemd-machine-id-commit.service \
        getty.target console-getty.service \
        dev-hugepages.mount sys-fs-fuse-connections.mount \
    && rm -f /lib/systemd/system/multi-user.target.wants/* \
             /etc/systemd/system/*.wants/* \
             /lib/systemd/system/sockets.target.wants/*udev*

WORKDIR /app
COPY requirements.lock /app/requirements.lock
RUN python3 -m pip install --no-cache-dir -r /app/requirements.lock

COPY src      /app/src
COPY db       /app/db
COPY scripts  /app/scripts
COPY fixtures /app/fixtures
COPY scripts/pg-bootstrap.sh /usr/local/bin/pg-bootstrap.sh
# Vendor location, not /etc: `systemctl mask` needs /etc free for its symlink.
COPY systemd/ /usr/lib/systemd/system/
RUN chmod +x /usr/local/bin/pg-bootstrap.sh

# Ordering is declared in the units themselves; these are the roots.
RUN systemctl enable \
        container-env.service \
        pg-init.service \
        postgresql.service \
        pg-bootstrap.service \
        migrate.service \
        mcp-solar.service \
    && systemctl mask warm-cache.timer

ENV PYTHONPATH=/app/src \
    MIGRATIONS_DIR=/app/db/migrations \
    PYTHONUNBUFFERED=1

EXPOSE 8000
STOPSIGNAL SIGRTMIN+3
# Podman auto-enables systemd mode when the entrypoint is /sbin/init. Compose
# has no way to pass --systemd=always, so this line is what makes it work.
ENTRYPOINT ["/sbin/init"]
