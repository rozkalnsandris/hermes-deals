#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any

PRIMARY = Path('/home/andris/hermes-deals')
HOST_RAW_ROOT = PRIMARY / 'data' / 'raw'
CONTAINER_RAW_ROOT = PurePosixPath('/data/raw')
OWNER = 'andris'
OWNER_HOME = '/home/andris'
RUNNER_USER = 'github-runner'
REQUIRED_FIX_COMMITS = (
    '0eb83f47658560ff733199399475771dc966008f',
    '52a3127c940dc36177846812932a08f49d913692',
)
POLICY_PATH = 'backend/tests/fixtures/netto/n25_title_package_review_policy_v1.json'
W4_DAILY_UI_SOURCE_PATH = 'backend/frontend/src/features/daily-specials.js'
DAILY_CONTRACT = 'explicit_immutable_retailer_evidence_only'
WEEKLY_CONTRACT = 'single_week_query_short_periods_plus_explicit_immutable_daily_evidence'
WEEKLY_UI_CONTRACT = 'normalized_unique_deals_by_id_v1'
W4_BUNDLE_MARKER = 'w3-behavior-preserving-bootstrap-v1'
NETTO_MANIFEST_CONTENT_TYPE = 'application/vnd.hermes-deals.netto-store-prospect+json'
INLINE_PRODUCTION_SCRIPT = 'inline:production-app.js'
PRODUCTION_BUNDLE_SCRIPT_ATTR = 'data-hermes-production-bundle'
PRODUCTION_BUNDLE_SCRIPT_VALUE = 'app.js'
PRODUCTION_BUNDLE_META_NAME = 'hermes-production-bundle'
PRODUCTION_BUNDLE_META_VALUE = 'inline-v1'
SHA40_RE = re.compile(r'[0-9a-f]{40}')
SHA256_RE = re.compile(r'[0-9a-f]{64}')
HASHED_UI_JS_PATH_RE = re.compile(
    r'/ui/assets/[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{8,}\.js'
)
DAILY_SOURCE_CONTRACT_DIRECT_RE = re.compile(
    rf'\bsource_contract\s*!==\s*["\']{re.escape(DAILY_CONTRACT)}["\']'
)
DAILY_SOURCE_CONTRACT_CONST_RE = re.compile(
    rf'\bDAILY_SPECIAL_SOURCE_CONTRACT\s*=\s*["\']{re.escape(DAILY_CONTRACT)}["\']'
)
DAILY_SOURCE_CONTRACT_USE_RE = re.compile(
    r'\bsource_contract\s*!==\s*DAILY_SPECIAL_SOURCE_CONTRACT\b'
)
DAILY_HIGH_CONFIDENCE_RE = re.compile(
    r'\bspecial_confidence\s*===\s*["\']high["\']'
)
DAILY_COUNT_RE = re.compile(
    r'\bcountEl\.textContent\s*=\s*String\(\s*rows\.length\s*\)'
)


class VerifyError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerifyError(message)


class _ScriptSrcParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []
        self.inline_production_scripts: list[str] = []
        self.production_bundle_meta_count = 0
        self.errors: list[str] = []
        self._capture_inline_production = False
        self._inline_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == 'meta':
            names = [value for name, value in attrs if name == 'name']
            contents = [value for name, value in attrs if name == 'content']
            if names == [PRODUCTION_BUNDLE_META_NAME] and contents == [PRODUCTION_BUNDLE_META_VALUE]:
                self.production_bundle_meta_count += 1
            return
        if tag != 'script':
            return

        src_values = [value.strip() for name, value in attrs if name == 'src' and value is not None]
        marker_values = [value for name, value in attrs if name == PRODUCTION_BUNDLE_SCRIPT_ATTR]
        if len(src_values) > 1:
            self.errors.append('daily UI script has duplicate src attributes')
        if len(marker_values) > 1:
            self.errors.append('daily UI production script marker is duplicated')
        self.sources.extend(src_values)

        if not marker_values:
            return
        if marker_values != [PRODUCTION_BUNDLE_SCRIPT_VALUE]:
            self.errors.append('daily UI production script marker value is invalid')
            return
        if src_values:
            self.errors.append('daily UI production inline script must not use src')
            return
        if self._capture_inline_production:
            self.errors.append('daily UI production inline script nesting is invalid')
            return
        self._capture_inline_production = True
        self._inline_parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_inline_production:
            self._inline_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != 'script' or not self._capture_inline_production:
            return
        self.inline_production_scripts.append(''.join(self._inline_parts))
        self._capture_inline_production = False
        self._inline_parts = []


def run(args: list[str], *, input_text: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        input=input_text,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=timeout,
        env={
            'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            'LANG': 'C.UTF-8',
        },
    )
    if result.returncode != 0:
        raise VerifyError(f'command failed: {Path(args[0]).name}')
    return result


def owner_git(*args: str) -> str:
    result = run([
        '/usr/sbin/runuser', '-u', OWNER, '--',
        '/usr/bin/env', '-i',
        f'HOME={OWNER_HOME}', f'USER={OWNER}', f'LOGNAME={OWNER}',
        'PATH=/usr/local/bin:/usr/bin:/bin',
        'GIT_OPTIONAL_LOCKS=0',
        '/usr/bin/git', '-C', str(PRIMARY), *args,
    ])
    require(not result.stderr, f'Git command emitted stderr: {args[0]}')
    return result.stdout.strip()


def compose_prefix() -> list[str]:
    return [
        '/usr/bin/docker', 'compose',
        '--project-directory', str(PRIMARY),
        '--env-file', str(PRIMARY / '.env'),
        '-f', str(PRIMARY / 'docker-compose.yml'),
        '-f', str(PRIMARY / 'docker-compose.production.yml'),
    ]


def compose(*args: str, timeout: int = 30) -> str:
    return run([*compose_prefix(), *args], timeout=timeout).stdout.strip()


def docker_inspect(container_id: str) -> dict[str, Any]:
    payload = json.loads(run(['/usr/bin/docker', 'inspect', container_id]).stdout)
    require(isinstance(payload, list) and len(payload) == 1, 'Docker inspect result invalid')
    require(isinstance(payload[0], dict), 'Docker inspect row invalid')
    return payload[0]


def db_identity(db_container: str) -> tuple[str, str]:
    row = docker_inspect(db_container)
    env: dict[str, str] = {}
    for item in row.get('Config', {}).get('Env', []):
        key, sep, value = str(item).partition('=')
        if sep:
            env[key] = value
    user = env.get('POSTGRES_USER', '')
    name = env.get('POSTGRES_DB', '')
    require(bool(user and name), 'database identity unavailable')
    return user, name


def psql(db_container: str, sql: str) -> str:
    user, name = db_identity(db_container)
    return compose(
        'exec', '-T',
        '-e', 'PGOPTIONS=-c default_transaction_read_only=on',
        'db', 'psql',
        '-X', '-v', 'ON_ERROR_STOP=1',
        '-U', user, '-d', name,
        '-Atqc', sql,
        timeout=60,
    )


def table_digest(db_container: str, table: str, where: str = 'TRUE') -> tuple[int, str]:
    require(
        table in {
            'source_snapshots',
            'offer_candidates',
            'offer_review_items',
            'offer_review_revisions',
        },
        'unsafe table',
    )
    count = int(psql(db_container, f'SELECT count(*) FROM {table} WHERE {where};'))
    sql = (
        'COPY (SELECT row_to_json(t)::text FROM '
        f'(SELECT * FROM {table} WHERE {where} ORDER BY id) t) TO STDOUT;'
    )
    raw = psql(db_container, sql)
    return count, hashlib.sha256(raw.encode('utf-8')).hexdigest()


def http_text(path: str) -> str:
    return run([
        '/usr/bin/curl', '--fail', '--silent', '--show-error', '--max-time', '20',
        f'http://127.0.0.1:9128{path}',
    ], timeout=25).stdout


def http_json(path: str) -> dict[str, Any]:
    try:
        payload = json.loads(http_text(path))
    except json.JSONDecodeError as exc:
        raise VerifyError(f'HTTP JSON invalid for {path}') from exc
    require(isinstance(payload, dict), f'HTTP JSON root invalid for {path}')
    return payload


def http_status(path: str) -> int:
    result = run([
        '/usr/bin/curl', '--silent', '--show-error', '--output', '/dev/null',
        '--write-out', '%{http_code}', '--max-time', '20',
        f'http://127.0.0.1:9128{path}',
    ], timeout=25)
    require(result.stdout.isdigit(), f'HTTP status invalid for {path}')
    return int(result.stdout)


def host_snapshot_path(stored_path: str) -> Path:
    raw = PurePosixPath(stored_path)
    require(raw.is_absolute(), 'Netto manifest path is not absolute')
    host_root = HOST_RAW_ROOT.resolve(strict=True)
    host_prefix = PurePosixPath(str(host_root))
    try:
        if raw == CONTAINER_RAW_ROOT or CONTAINER_RAW_ROOT in raw.parents:
            relative = raw.relative_to(CONTAINER_RAW_ROOT)
        elif raw == host_prefix or host_prefix in raw.parents:
            relative = raw.relative_to(host_prefix)
        else:
            raise ValueError
    except ValueError as exc:
        raise VerifyError('Netto manifest path outside approved raw roots') from exc
    require(bool(relative.parts), 'Netto manifest path points at raw root')
    require('..' not in relative.parts, 'Netto manifest path contains traversal')
    candidate = host_root.joinpath(*relative.parts)
    require(candidate.is_file() and not candidate.is_symlink(), 'Netto manifest path unavailable')
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(host_root)
    except ValueError as exc:
        raise VerifyError('Netto manifest path escapes host raw root') from exc
    return resolved


@dataclass(frozen=True)
class Snapshot:
    id: str
    sha256: str
    collected_at: datetime
    valid_from: date
    valid_until: date


def parse_snapshot_rows(db_container: str) -> list[Snapshot]:
    raw = psql(
        db_container,
        """
        SELECT json_build_object(
          'id', id::text,
          'snapshot_path', snapshot_path,
          'sha256', sha256,
          'collected_at', collected_at
        )::text
        FROM source_snapshots
        WHERE source_chain='netto'
          AND scope='family_primary_netto'
          AND success IS TRUE
          AND content_type='application/vnd.hermes-deals.netto-store-prospect+json'
        ORDER BY collected_at DESC, id DESC;
        """,
    )
    snapshots: list[Snapshot] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        path = host_snapshot_path(str(row['snapshot_path']))
        expected = str(row['sha256'])
        require(SHA256_RE.fullmatch(expected) is not None, 'Netto manifest SHA invalid')
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == expected, 'Netto manifest SHA mismatch')
        manifest = json.loads(data)
        require(isinstance(manifest, dict), 'Netto manifest root invalid')
        require(str(manifest.get('store_external_id')) == '5659', 'Netto store binding mismatch')
        require(manifest.get('scope') == 'family_primary_netto', 'Netto scope binding mismatch')
        start = date.fromisoformat(str(manifest.get('valid_from')))
        end = date.fromisoformat(str(manifest.get('valid_until')))
        require(start <= end, 'Netto campaign window reversed')
        snapshots.append(Snapshot(
            id=str(row['id']),
            sha256=expected,
            collected_at=datetime.fromisoformat(str(row['collected_at'])),
            valid_from=start,
            valid_until=end,
        ))
    require(bool(snapshots), 'no immutable Netto snapshots available')
    return snapshots


def select_snapshot(snapshots: list[Snapshot], day: date) -> Snapshot | None:
    matches = [s for s in snapshots if s.valid_from <= day <= s.valid_until]
    if not matches:
        return None
    return max(matches, key=lambda s: (s.collected_at, s.id))


def validate_daily_payload(payload: dict[str, Any], *, day: date, selected: Snapshot | None) -> list[dict[str, Any]]:
    require(payload.get('as_of') == day.isoformat(), 'daily as_of mismatch')
    require(payload.get('timezone') == 'Europe/Berlin', 'daily timezone mismatch')
    require(payload.get('source_contract') == DAILY_CONTRACT, 'daily source contract mismatch')
    deals = payload.get('deals')
    require(isinstance(deals, list), 'daily deals invalid')
    netto = [row for row in deals if isinstance(row, dict) and row.get('source_chain') == 'netto']
    retailer_counts = payload.get('retailer_counts') or {}
    require(isinstance(retailer_counts, dict), 'daily retailer counts invalid')
    require(int(retailer_counts.get('netto', 0)) == len(netto), 'daily Netto count mismatch')
    if selected is None:
        require(not netto, 'out-of-window request returned Netto rows')
        return []
    for row in netto:
        require(row.get('source_store_external_id') == '5659', 'daily store binding mismatch')
        require(row.get('source_snapshot_id') == selected.id, 'daily snapshot identity mismatch')
        require(row.get('source_snapshot_sha256') == selected.sha256, 'daily snapshot SHA mismatch')
        require(row.get('special_valid_on') == day.isoformat(), 'daily validity mismatch')
        require(row.get('is_daily_special') is True, 'daily special marker missing')
        require(row.get('shadow_only') is True, 'daily shadow-only marker missing')
    return netto


def daily_ui_high_confidence_ids(day: date, daily_netto: list[dict[str, Any]]) -> set[str]:
    return {
        str(row.get('offer_candidate_id'))
        for row in daily_netto
        if row.get('special_valid_on') == day.isoformat()
        and row.get('is_daily_special') is True
        and row.get('special_confidence') == 'high'
    }


def _parse_daily_ui_scripts(html: str) -> _ScriptSrcParser:
    parser = _ScriptSrcParser()
    try:
        parser.feed(html)
        parser.close()
    except VerifyError:
        raise
    except Exception as exc:
        raise VerifyError('daily UI HTML parsing failed') from exc
    require(not parser.errors, parser.errors[0] if parser.errors else 'daily UI HTML parsing failed')
    require(not parser._capture_inline_production, 'daily UI production inline script is unterminated')
    return parser


def _daily_ui_script_selection(html: str) -> tuple[str, str | None]:
    parser = _parse_daily_ui_scripts(html)
    hashed = [src for src in parser.sources if HASHED_UI_JS_PATH_RE.fullmatch(src)]
    legacy = [src for src in parser.sources if src == '/ui/app.js']
    inline = parser.inline_production_scripts
    mode_count = int(bool(hashed)) + int(bool(legacy)) + int(bool(inline))
    require(mode_count == 1, 'daily UI active script reference missing or ambiguous')

    if inline:
        require(len(inline) == 1, 'daily UI production inline script is ambiguous')
        require(
            parser.production_bundle_meta_count == 1,
            'daily UI production inline meta marker missing or ambiguous',
        )
        return INLINE_PRODUCTION_SCRIPT, inline[0]

    require(
        parser.production_bundle_meta_count == 0,
        'daily UI production inline meta marker has no matching inline script',
    )
    if hashed:
        require(len(hashed) == 1, 'daily UI hashed script reference is ambiguous')
        return hashed[0], None
    require(len(legacy) == 1, 'daily UI active script reference missing or ambiguous')
    return legacy[0], None


def daily_ui_script_path(html: str) -> str:
    script_ref, _ = _daily_ui_script_selection(html)
    return script_ref


def validate_daily_ui_script_semantics(script: str) -> None:
    direct_contract = DAILY_SOURCE_CONTRACT_DIRECT_RE.search(script) is not None
    constant_contract = (
        DAILY_SOURCE_CONTRACT_CONST_RE.search(script) is not None
        and DAILY_SOURCE_CONTRACT_USE_RE.search(script) is not None
    )
    require(direct_contract or constant_contract, 'daily UI source-contract semantic check missing')
    require(DAILY_HIGH_CONFIDENCE_RE.search(script) is not None, 'daily UI high-confidence filter semantic check missing')
    require(DAILY_COUNT_RE.search(script) is not None, 'daily UI count semantic check missing')


def validate_daily_ui_contract(production_revision: str) -> str:
    html = http_text('/ui')
    script_ref, inline_script = _daily_ui_script_selection(html)
    if script_ref == INLINE_PRODUCTION_SCRIPT:
        require(inline_script is not None, 'daily UI production inline script missing')
        require(W4_BUNDLE_MARKER in inline_script, 'daily UI production inline behavior marker missing')
        require(DAILY_CONTRACT in inline_script, 'daily UI production inline source-contract literal missing')
        validate_daily_ui_script_semantics(inline_script)
        return 'inline-production'

    script = http_text(script_ref)
    if script_ref == '/ui/app.js':
        validate_daily_ui_script_semantics(script)
        return 'legacy-w3'

    require(HASHED_UI_JS_PATH_RE.fullmatch(script_ref) is not None, 'daily UI hashed script path invalid')
    require(W4_BUNDLE_MARKER in script, 'daily UI hashed bundle behavior marker missing')
    require(DAILY_CONTRACT in script, 'daily UI hashed bundle source-contract literal missing')
    source = owner_git('show', f'{production_revision}:{W4_DAILY_UI_SOURCE_PATH}')
    validate_daily_ui_script_semantics(source)
    return 'hashed-w4'


def validate_review_only_policy(production_revision: str) -> None:
    policy = json.loads(owner_git('show', f'{production_revision}:{POLICY_PATH}'))
    require(policy['title_policy']['automatic_selection_enabled'] is False, 'title auto-selection enabled')
    require(policy['title_policy']['route'] == 'review_required', 'title review route drift')
    require(policy['package_policy']['automatic_selection_enabled'] is False, 'package auto-selection enabled')
    require(policy['package_policy']['route'] == 'review_required', 'package review route drift')
    promotion = policy['promotion_policy']
    require(promotion['automatic_approval_enabled'] is False, 'automatic approval enabled')
    require(promotion['automatic_publish_enabled'] is False, 'automatic publish enabled')
    require(promotion['production_integration_allowed'] is False, 'N25/N26 production integration enabled')


def find_covered_probes(snapshots: list[Snapshot], *, max_windows: int = 4) -> list[tuple[date, Snapshot, list[dict[str, Any]]]]:
    probes: list[tuple[date, Snapshot, list[dict[str, Any]]]] = []
    seen_windows: set[tuple[date, date]] = set()
    for snapshot in snapshots:
        window = (snapshot.valid_from, snapshot.valid_until)
        if window in seen_windows:
            continue
        seen_windows.add(window)
        if len(seen_windows) > max_windows:
            break
        day = snapshot.valid_from
        while day <= snapshot.valid_until:
            selected = select_snapshot(snapshots, day)
            if selected is not None:
                payload = http_json(f'/api/v1/deals/daily-specials?as_of={day.isoformat()}')
                netto = validate_daily_payload(payload, day=day, selected=selected)
                if daily_ui_high_confidence_ids(day, netto):
                    probes.append((day, selected, netto))
                    break
            day += timedelta(days=1)
        if len(probes) >= 2:
            break
    require(len(probes) >= 2, 'current and historical covered Netto probes are both required')
    return probes


def validate_weekly_probe(day: date, daily_netto: list[dict[str, Any]]) -> tuple[int, int]:
    monday = day - timedelta(days=day.isoweekday() - 1)
    payload = http_json(f'/api/v1/deals/weekly-specials?week_start={monday.isoformat()}')
    require(payload.get('week_start') == monday.isoformat(), 'weekly start mismatch')
    require(payload.get('timezone') == 'Europe/Berlin', 'weekly timezone mismatch')
    require(payload.get('source_contract') == WEEKLY_CONTRACT, 'weekly source contract mismatch')
    days = payload.get('days')
    require(isinstance(days, list), 'weekly days invalid')
    row = next((item for item in days if isinstance(item, dict) and item.get('date') == day.isoformat()), None)
    require(isinstance(row, dict), 'weekly probe day missing')
    deals = row.get('deals')
    require(isinstance(deals, list), 'weekly probe deals invalid')
    weekly_netto_ids = {
        str(item.get('offer_candidate_id'))
        for item in deals
        if isinstance(item, dict)
        and item.get('source_chain') == 'netto'
        and item.get('is_daily_special') is True
    }
    daily_high_ids = daily_ui_high_confidence_ids(day, daily_netto)
    require(weekly_netto_ids == daily_high_ids, 'daily/weekly high-confidence Netto set mismatch')

    ui = http_json(f'/api/v1/deals/weekly-specials/ui?week_start={monday.isoformat()}')
    require(ui.get('week_start') == monday.isoformat(), 'weekly UI start mismatch')
    require(ui.get('timezone') == 'Europe/Berlin', 'weekly UI timezone mismatch')
    require(ui.get('source_contract') == WEEKLY_CONTRACT, 'weekly UI source contract mismatch')
    require(ui.get('ui_contract') == WEEKLY_UI_CONTRACT, 'weekly UI contract mismatch')
    ui_days = ui.get('days')
    ui_deals = ui.get('deals')
    require(isinstance(ui_days, list) and isinstance(ui_deals, list), 'weekly UI payload invalid')
    require(int(ui.get('count', -1)) == sum(len(item.get('deal_ids') or []) for item in ui_days if isinstance(item, dict)), 'weekly UI total count mismatch')
    ui_day = next((item for item in ui_days if isinstance(item, dict) and item.get('date') == day.isoformat()), None)
    require(isinstance(ui_day, dict), 'weekly UI probe day missing')
    by_id = {
        str(item.get('offer_candidate_id')): item
        for item in ui_deals
        if isinstance(item, dict)
    }
    ui_netto_ids = {
        str(offer_id)
        for offer_id in ui_day.get('deal_ids') or []
        if isinstance(by_id.get(str(offer_id)), dict)
        and by_id[str(offer_id)].get('source_chain') == 'netto'
        and by_id[str(offer_id)].get('is_daily_special') is True
    }
    require(ui_netto_ids == daily_high_ids, 'weekly UI Netto count/set mismatch')
    return len(weekly_netto_ids), len(ui_netto_ids)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--registered-sha', required=True)
    parser.add_argument('--evidence-dir', required=True)
    args = parser.parse_args()

    require(os.geteuid() == 0, 'verifier must run as root')
    require(SHA40_RE.fullmatch(args.registered_sha) is not None, 'registered SHA invalid')
    evidence_dir = Path(args.evidence_dir).resolve()
    require(evidence_dir.is_dir() and not evidence_dir.is_symlink(), 'evidence directory unsafe')
    require(str(evidence_dir).startswith('/home/github-runner/_work/_temp/hermes-netto-19-production-verify-'), 'evidence directory outside allowlist')
    require(PRIMARY.is_dir() and not PRIMARY.is_symlink(), 'production root missing')
    require((PRIMARY / '.env').is_file(), 'production env missing')

    production_git_head = owner_git('rev-parse', 'HEAD')
    production_git_status = owner_git('status', '--porcelain=v1', '--untracked-files=all')

    api = compose('ps', '-q', 'api')
    db = compose('ps', '-q', 'db')
    web = compose('ps', '-q', 'web')
    require(bool(api and db and web), 'production containers are not all running')

    api_row = docker_inspect(api)
    image_ref = str(api_row.get('Config', {}).get('Image') or '')
    image_id = str(api_row.get('Image') or '')
    labels = api_row.get('Config', {}).get('Labels') or {}
    production_revision = str(labels.get('org.opencontainers.image.revision') or '')
    require(image_ref.startswith('hermes-deals-api:'), 'unexpected production image reference')
    require(image_id.startswith('sha256:'), 'unexpected production image id')
    require(SHA40_RE.fullmatch(production_revision) is not None, 'production revision missing')
    owner_git('cat-file', '-e', f'{production_revision}^{{commit}}')
    for required in REQUIRED_FIX_COMMITS:
        owner_git('merge-base', '--is-ancestor', required, production_revision)

    validate_review_only_policy(production_revision)
    require(psql(db, 'SHOW default_transaction_read_only;') == 'on', 'database read-only session enforcement missing')

    alembic_before = psql(db, 'SELECT version_num FROM alembic_version;')
    require(bool(alembic_before), 'Alembic revision unavailable')
    db_before = {
        'source_snapshots': table_digest(db, 'source_snapshots', "source_chain='netto'"),
        'offer_candidates': table_digest(db, 'offer_candidates', "source_chain='netto'"),
        'offer_review_items': table_digest(db, 'offer_review_items'),
        'offer_review_revisions': table_digest(db, 'offer_review_revisions'),
    }

    health = http_json('/api/health')
    require(health.get('status') == 'ok', 'health status not ok')
    require(health.get('service') == 'hermes-deals-api', 'health service mismatch')
    require(http_status('/ui') == 200, 'UI status not 200')
    require(http_status('/ui/review') in {200, 302}, 'Review UI status unexpected')
    daily_ui_asset_mode = validate_daily_ui_contract(production_revision)

    snapshots = parse_snapshot_rows(db)
    probes = find_covered_probes(snapshots)
    weekly_counts: list[int] = []
    weekly_ui_counts: list[int] = []
    for day, _, netto in probes:
        weekly_count, weekly_ui_count = validate_weekly_probe(day, netto)
        weekly_counts.append(weekly_count)
        weekly_ui_counts.append(weekly_ui_count)
    latest_day, latest_snapshot, latest_netto = probes[0]

    outside_day = max(snapshot.valid_until for snapshot in snapshots) + timedelta(days=7)
    outside_payload = http_json(f'/api/v1/deals/daily-specials?as_of={outside_day.isoformat()}')
    validate_daily_payload(outside_payload, day=outside_day, selected=None)

    alembic_after = psql(db, 'SELECT version_num FROM alembic_version;')
    db_after = {
        'source_snapshots': table_digest(db, 'source_snapshots', "source_chain='netto'"),
        'offer_candidates': table_digest(db, 'offer_candidates', "source_chain='netto'"),
        'offer_review_items': table_digest(db, 'offer_review_items'),
        'offer_review_revisions': table_digest(db, 'offer_review_revisions'),
    }
    require(alembic_after == alembic_before, 'Alembic revision changed during verifier')
    require(db_after == db_before, 'database payload changed during verifier')
    require(owner_git('rev-parse', 'HEAD') == production_git_head, 'production Git HEAD changed')
    require(owner_git('status', '--porcelain=v1', '--untracked-files=all') == production_git_status, 'production Git status changed')

    receipt = {
        'schema_version': 1,
        'result': 'PASS',
        'registered_sha': args.registered_sha,
        'production_revision': production_revision,
        'production_image_ref': image_ref,
        'production_image_id': image_id,
        'runtime_version': health.get('version'),
        'runtime_phase': health.get('phase'),
        'alembic_revision': alembic_after,
        'required_fix_commits_present': True,
        'daily_contract': 'PASS',
        'weekly_contract': 'PASS',
        'daily_ui_count_contract': 'PASS',
        'daily_ui_asset_mode': daily_ui_asset_mode,
        'weekly_ui_count_contract': 'PASS',
        'review_only_policy': 'PASS',
        'covered_probe_count': len(probes),
        'latest_covered_probe_date': latest_day.isoformat(),
        'latest_covered_snapshot_id': latest_snapshot.id,
        'latest_covered_snapshot_sha256': latest_snapshot.sha256,
        'latest_covered_netto_count': len(latest_netto),
        'latest_daily_ui_netto_count': len(daily_ui_high_confidence_ids(latest_day, latest_netto)),
        'historical_covered_probe_present': True,
        'covered_probes': [
            {
                'date': day.isoformat(),
                'snapshot_id': snapshot.id,
                'snapshot_sha256': snapshot.sha256,
                'daily_netto_count': len(netto),
                'daily_ui_high_confidence_netto_count': len(daily_ui_high_confidence_ids(day, netto)),
                'weekly_high_confidence_netto_count': weekly_count,
                'weekly_ui_netto_count': weekly_ui_count,
            }
            for (day, snapshot, netto), weekly_count, weekly_ui_count in zip(
                probes, weekly_counts, weekly_ui_counts, strict=True
            )
        ],
        'outside_window_probe_date': outside_day.isoformat(),
        'outside_window_netto_count': 0,
        'database_payload_unchanged': True,
        'production_git_unchanged': True,
        'rollback_target': {
            'kind': 'current_running_image',
            'image_ref': image_ref,
            'image_id': image_id,
            'revision': production_revision,
            'command_required': False,
            'reason': 'read-only verifier performs no deployment',
        },
        'production_mutated': False,
        'database_write_performed': False,
        'review_write_performed': False,
        'publication_performed': False,
        'deployment_performed': False,
        'scheduler_change_performed': False,
        'host_root_change_performed': False,
    }
    target = evidence_dir / 'receipt.json'
    target.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    os.chown(target, 0, 0)
    os.chmod(target, 0o644)
    run(['/usr/bin/chown', f'{RUNNER_USER}:{RUNNER_USER}', str(target)])
    run(['/usr/bin/chmod', '0600', str(target)])
    print(json.dumps(receipt, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except VerifyError as exc:
        print(f'NETTO_19_READONLY_VERIFY=FAIL reason={exc}', file=sys.stderr)
        raise SystemExit(1)
