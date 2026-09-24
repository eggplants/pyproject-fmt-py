FROM python:3.14-slim AS builder

ARG VERSION
ENV VERSION=${VERSION:-master}

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
RUN /opt/venv/bin/pip install --no-cache-dir \
    "git+https://github.com/eggplants/pyproject-fmt-py@${VERSION}"

FROM al3xos/python-distroless:3.14-debian13@sha256:5b2586853c9e20e18d91619528a80ea27f89347217d772efe0391eb06afa3b5e
COPY --from=builder /opt/venv /opt/venv
# Nothing in here launches a venv, so the interpreter is called directly and told
# where the packages landed.
ENV PYTHONPATH="/opt/venv/lib/python3.14/site-packages"

ENTRYPOINT ["python", "/opt/venv/bin/pyproject-fmt"]
