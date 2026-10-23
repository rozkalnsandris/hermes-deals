# Audit-only regression layer; never deploy in production.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY backend/locks/ci-py313.txt /app/locks/ci-py313.txt
RUN python -m pip install --disable-pip-version-check \
    --require-hashes --only-binary=:all: -r /app/locks/ci-py313.txt \
    && python -m pip check
