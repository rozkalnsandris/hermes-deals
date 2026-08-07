FROM python:3.13.14-slim-bookworm@sha256:9d7f287598e1a5a978c015ee176d8216435aaf335ed69ac3c38dd1bbb10e8d64

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Source stays split for review and tests. Only the immutable release image
# receives a self-contained HTML document so nginx needs to proxy only /ui.
RUN python -m app.ui_bundle --ui-dir /app/app/ui

# Release-control worktrees are intentionally private (0700/0600). Docker COPY
# preserves local build-context modes, so normalize runtime source readability
# after all generated UI files exist. This keeps non-root collector execution
# independent of the staging umask without making source files executable.
RUN chmod -R a+rX /app/app /app/alembic \
    && chmod a+r /app/alembic.ini

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
