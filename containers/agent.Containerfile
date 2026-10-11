FROM quay.io/fedora/fedora:44

RUN dnf -y install --setopt=install_weak_deps=False python3 python3-pip \
    && dnf clean all && rm -rf /var/cache/dnf

WORKDIR /app
COPY requirements.lock /app/requirements.lock
RUN python3 -m pip install --no-cache-dir -r /app/requirements.lock
COPY src     /app/src
COPY scripts /app/scripts

ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "-m", "agent.main"]
