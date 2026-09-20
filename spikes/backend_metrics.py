# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Provider-neutral run usage and privileged OpenAI account reports."""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import http.client
import json
import os
from pathlib import Path
import sqlite3
import ssl
import stat
from urllib.parse import urlencode

from spikes.metadata import require, timestamp
from spikes.openai_backend import OpenAICredentials


MAX_REPORT_RESPONSE = 4 * 1024 * 1024
MAX_PAGES = 100


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _metric(name, value, unit, *, currency=None):
    require(isinstance(name, str) and name and isinstance(unit, str) and unit,
            'Invalid backend metric')
    require(type(value) in {int, float} and value >= 0, 'Invalid backend metric value')
    result = {'name': name, 'value': value, 'unit': unit, 'value_kind': 'actual'}
    if currency is not None:
        require(isinstance(currency, str) and len(currency) == 3
                and currency.isascii() and currency.islower(), 'Invalid billing currency')
        result['currency'] = currency
    return result


def run_usage(adapter_id, binding_id, run_id, response, fetched_at=None):
    """Normalize only provider-reported metrics from a completed run."""
    require(isinstance(response, dict), 'Backend response is required')
    metrics = []
    if adapter_id == 'ollama':
        fields = (('prompt_eval_count', 'input_tokens', 'tokens'),
                  ('eval_count', 'output_tokens', 'tokens'),
                  ('total_duration', 'total_duration', 'nanoseconds'),
                  ('load_duration', 'load_duration', 'nanoseconds'),
                  ('prompt_eval_duration', 'input_duration', 'nanoseconds'),
                  ('eval_duration', 'output_duration', 'nanoseconds'))
        for source, name, unit in fields:
            value = response.get(source)
            if type(value) is int and value >= 0:
                metrics.append(_metric(name, value, unit))
    elif adapter_id == 'openai-responses':
        usage = response.get('usage')
        if isinstance(usage, dict):
            for source, name in (('input_tokens', 'input_tokens'),
                                 ('output_tokens', 'output_tokens'),
                                 ('total_tokens', 'total_tokens')):
                value = usage.get(source)
                if type(value) is int and value >= 0:
                    metrics.append(_metric(name, value, 'tokens'))
    else:
        raise ValueError('Unsupported backend usage adapter')
    observed = fetched_at or _now(); timestamp(observed)
    return {'schema_version': 1, 'kind': 'usage',
            'status': 'available' if metrics else 'unsupported', 'scope': 'run',
            'adapter_id': adapter_id, 'binding_id': binding_id, 'run_id': run_id,
            'period_start': None, 'period_end': None, 'fetched_at': observed,
            'metrics': metrics}


class MetricTransportError(RuntimeError):
    def __init__(self, message, *, forbidden=False):
        super().__init__(message); self.forbidden = forbidden


class MetricCache:
    def __init__(self, root):
        self.root = Path(root); self.path = self.root / 'backend-metrics.sqlite'

    def connect(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe backend metric cache')
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS reports ('
                   'cache_key TEXT PRIMARY KEY, report TEXT NOT NULL, fetched_at TEXT NOT NULL)')
        db.commit(); return closing(db)

    def load(self, key):
        with self.connect() as db:
            row = db.execute('SELECT report FROM reports WHERE cache_key=?', (key,)).fetchone()
        return None if row is None else json.loads(row[0])

    def save(self, key, report):
        raw = json.dumps(report, sort_keys=True, separators=(',', ':'))
        require(len(raw.encode()) <= MAX_REPORT_RESPONSE, 'Backend metric report is too large')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO reports VALUES (?,?,?) ON CONFLICT(cache_key) DO UPDATE '
                       'SET report=excluded.report,fetched_at=excluded.fetched_at',
                       (key, raw, report['fetched_at']))
            db.commit()


class OpenAIAccountMetrics:
    SETTINGS = 'openai-account-metrics.json'

    def __init__(self, root, transport=None):
        self.root = Path(root); self.credentials = OpenAICredentials(
            root, filename='openai-admin-credentials.sqlite')
        self.path = self.root / self.SETTINGS
        self.cache = MetricCache(root); self.transport = transport or self._http

    def configure(self, secret):
        reference = 'credential:openai-admin'
        credential = self.credentials.put(reference, secret)
        value = {'schema_version': 1, 'credential_ref': reference,
                 'credential_revision': credential['revision']}
        raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
        temporary = self.root / ('.' + self.SETTINGS + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, raw); os.fsync(fd); os.close(fd); fd = -1
            os.replace(temporary, self.path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if fd >= 0: os.close(fd)
            if temporary.exists(): temporary.unlink()
        return self.status()

    def settings(self):
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077,
                    'Unsafe OpenAI account metric settings')
            raw = os.read(fd, 64 * 1024 + 1)
        finally:
            os.close(fd)
        require(len(raw) <= 64 * 1024, 'OpenAI account metric settings are too large')
        value = json.loads(raw)
        require(set(value) == {'schema_version', 'credential_ref', 'credential_revision'}
                and value['schema_version'] == 1, 'Invalid OpenAI account metric settings')
        return value

    def status(self):
        try:
            value = self.settings()
        except FileNotFoundError:
            return {'capabilities': {'usage': True, 'billing': True},
                    'credential': None, 'report': None}
        report = self.cache.load('openai-account')
        return {'capabilities': {'usage': True, 'billing': True},
                'credential': self.credentials.status(value['credential_ref']),
                'report': report}

    def refresh(self, start_time, end_time):
        require(type(start_time) is int and type(end_time) is int
                and 0 <= start_time < end_time and end_time - start_time <= 90 * 86400,
                'Invalid account metric period')
        value = self.settings(); secret, revision = self.credentials.resolve(
            value['credential_ref'])
        require(revision == value['credential_revision'], 'Admin credential revision changed')
        try:
            usage = self._pages('/v1/organization/usage/completions', start_time,
                                end_time, secret)
            costs = self._pages('/v1/organization/costs', start_time, end_time, secret)
            report = self._normalize(usage, costs, start_time, end_time)
            self.cache.save('openai-account', report)
            return report
        except MetricTransportError as exc:
            cached = self.cache.load('openai-account')
            if cached is not None:
                return dict(cached, status='forbidden' if exc.forbidden else 'stale')
            return {'schema_version': 1,
                    'status': 'forbidden' if exc.forbidden else 'unavailable',
                    'scope': 'account', 'adapter_id': 'openai-responses',
                    'period_start': start_time, 'period_end': end_time,
                    'fetched_at': _now(), 'reports': []}

    def _pages(self, path, start, end, secret):
        page = None; rows = []
        for _ in range(MAX_PAGES):
            query = {'start_time': start, 'end_time': end, 'limit': 31}
            if page: query['page'] = page
            value = self.transport(path + '?' + urlencode(query), secret)
            require(isinstance(value, dict) and isinstance(value.get('data'), list),
                    'Invalid OpenAI account metric response')
            rows.extend(value['data'])
            require(len(json.dumps(rows).encode()) <= MAX_REPORT_RESPONSE,
                    'OpenAI account metric response is too large')
            page = value.get('next_page') if value.get('has_more') is True else None
            if not page: return rows
        raise ValueError('OpenAI account metric pagination exceeds limit')

    @staticmethod
    def _normalize(usage, costs, start, end):
        totals = {'input_tokens': 0, 'output_tokens': 0, 'model_requests': 0}
        for bucket in usage:
            require(isinstance(bucket, dict) and isinstance(bucket.get('results'), list),
                    'Invalid OpenAI usage bucket')
            for item in bucket['results']:
                for source, target in (('input_tokens', 'input_tokens'),
                                       ('output_tokens', 'output_tokens'),
                                       ('num_model_requests', 'model_requests')):
                    value = item.get(source, 0)
                    require(type(value) is int and value >= 0, 'Invalid OpenAI usage value')
                    totals[target] += value
        money = {}
        for bucket in costs:
            require(isinstance(bucket, dict) and isinstance(bucket.get('results'), list),
                    'Invalid OpenAI cost bucket')
            for item in bucket['results']:
                amount = item.get('amount', {})
                currency = amount.get('currency'); value = amount.get('value')
                require(isinstance(currency, str) and isinstance(value, (int, float, str)),
                        'Invalid OpenAI cost value')
                try: money[currency] = money.get(currency, Decimal(0)) + Decimal(str(value))
                except InvalidOperation as exc: raise ValueError('Invalid OpenAI cost value') from exc
        fetched = _now()
        usage_metrics = [_metric(name, value,
                         'tokens' if name.endswith('tokens') else 'requests')
                         for name, value in totals.items()]
        billing_metrics = [_metric('cost', float(value), 'currency', currency=currency)
                           for currency, value in sorted(money.items())]
        common = {'schema_version': 1, 'status': 'available', 'scope': 'account',
                  'adapter_id': 'openai-responses', 'period_start': start,
                  'period_end': end, 'fetched_at': fetched}
        return dict(common, reports=[dict(common, kind='usage', metrics=usage_metrics),
                                     dict(common, kind='billing', metrics=billing_metrics)])

    @staticmethod
    def _http(path, secret):
        connection = http.client.HTTPSConnection('api.openai.com', 443, timeout=30,
                                                 context=ssl.create_default_context())
        try:
            connection.request('GET', path, headers={'Authorization': 'Bearer ' + secret,
                                                      'Accept': 'application/json'})
            response = connection.getresponse()
            if response.status in {401, 403}:
                raise MetricTransportError('OpenAI account metrics forbidden', forbidden=True)
            if response.status < 200 or response.status >= 300:
                raise MetricTransportError('OpenAI account metrics unavailable')
            raw = response.read(MAX_REPORT_RESPONSE + 1)
            if len(raw) > MAX_REPORT_RESPONSE:
                raise MetricTransportError('OpenAI account metric response is too large')
            return json.loads(raw)
        except MetricTransportError:
            raise
        except (OSError, ValueError) as exc:
            raise MetricTransportError('OpenAI account metrics unavailable') from exc
        finally:
            connection.close()
