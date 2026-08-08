FROM node:24.18.0-bookworm-slim@sha256:6f7b4768c55fccf07e8c851e940864a576822b0fa9318b2e901386eb446438ed AS ui-build

ENV npm_config_update_notifier=false \
    npm_config_fund=false

WORKDIR /ui

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts \
    && npm audit --audit-level=high

COPY frontend/vite.config.js ./
COPY frontend/scripts ./scripts
COPY frontend/src ./src
COPY frontend/tests ./tests
RUN npm test \
    && npm run build:check

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

# The Node builder never enters the runtime image. It contributes only the
# deterministic W3 bundle, which replaces the reviewed legacy source app.js
# immediately before the existing fail-closed inline production bundling step.
COPY --from=ui-build /ui/dist/app.js /app/app/ui/app.js

# W3 keeps the immutable production contract as one self-contained /ui HTML
# document. W4 will later introduce independently cached hashed assets.
RUN python -m app.ui_bundle --ui-dir /app/app/ui

# Local build contexts preserve source permission metadata. Normalize the final
# runtime tree to exact modes after generated UI files exist so non-root
# collectors can read/traverse it and the image is independent of source umask.
RUN find /app/app /app/alembic -type d -exec chmod 0755 {} + \
    && find /app/app /app/alembic -type f -exec chmod 0644 {} + \
    && chmod 0644 /app/alembic.ini

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
