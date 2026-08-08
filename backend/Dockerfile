FROM node:24.18.0-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d AS ui-build

ENV npm_config_update_notifier=false \
    npm_config_fund=false

WORKDIR /ui

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts \
    && npm audit --audit-level=high

COPY frontend/vite.config.js frontend/vite.w4.config.js ./
COPY frontend/scripts ./scripts
COPY frontend/src ./src
COPY frontend/tests ./tests
COPY app/ui/styles.css ./legacy-styles.css
RUN npm test \
    && npm run build:check \
    && npm run build:w4:check

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

# Preserve the current W3 serving contract exactly: the deterministic IIFE
# replaces reviewed source app.js and is then inlined into the immutable /ui
# document by app.ui_bundle.
COPY --from=ui-build /ui/dist/app.js /app/app/ui/app.js

# W4A packages a second, non-serving shadow build in the same exact release
# image. It contains only manifest-selected content-hashed JS/CSS plus generated
# shadow HTML/evidence. W4B will separately authorize any serving cutover.
COPY --from=ui-build /ui/dist-w4 /app/app/ui_w4_shadow
RUN python -m app.ui_w4_shadow \
        --source-ui-dir /app/app/ui \
        --build-dir /app/app/ui_w4_shadow

# W4A deliberately leaves production routing on the existing one-document W3
# bundle. No /ui/assets route or cache-policy change is introduced here.
RUN python -m app.ui_bundle --ui-dir /app/app/ui

# Local build contexts preserve source permission metadata. Normalize the final
# runtime tree to exact modes after generated UI files exist so non-root
# collectors can read/traverse it and the image is independent of source umask.
RUN find /app/app /app/alembic -type d -exec chmod 0755 {} + \
    && find /app/app /app/alembic -type f -exec chmod 0644 {} + \
    && chmod 0644 /app/alembic.ini

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
