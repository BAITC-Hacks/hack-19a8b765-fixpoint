"""Local JSON archives for inspection, never for replaying business actions."""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

logger = logging.getLogger(__name__)
OMIT_FIELDS = {'audio_base64', 'openai_api_key', 'api_key', 'authorization'}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def archive_value(value):
    if isinstance(value, dict):
        return {key: archive_value(item) for key, item in value.items() if key.lower() not in OMIT_FIELDS}
    if isinstance(value, (list, tuple)):
        return [archive_value(item) for item in value]
    return value


class SessionArchive:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, session_id):
        # Only generated canonical UUIDs can select a file; no user paths.
        if str(UUID(session_id)) != session_id:
            raise ValueError('Invalid session ID')
        return self.directory / f'{session_id}.json'

    def save(self, document):
        path = self.path(document['session_id'])
        document['updated_at'] = timestamp()
        payload = json.dumps(archive_value(document), ensure_ascii=False, indent=2, allow_nan=False)
        temporary = None
        try:
            with NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.directory,
                                    prefix=f'.{document["session_id"]}-', suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

    def read(self, session_id):
        path = self.path(session_id)
        if not path.exists():
            return None
        document = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(document, dict) or document.get('session_id') != session_id or document.get('schema_version') != 1:
            raise ValueError('Invalid session archive')
        if document.get('status') not in ('active', 'closed', 'interrupted') or not isinstance(document.get('turns'), list):
            raise ValueError('Invalid session archive contents')
        if any(not isinstance(turn, dict) or not isinstance(turn.get('trace'), dict) for turn in document['turns']):
            raise ValueError('Invalid archived turn')
        return document

    def documents(self):
        for path in self.directory.glob('*.json'):
            try:
                document = self.read(path.stem)
                if document is not None:
                    yield document
            except (OSError, ValueError):
                logger.warning('Unreadable session archive: %s', path.name)

    def interrupt_open_sessions(self):
        # A new process cannot continue an old confirmation or replay a request.
        for document in self.documents():
            if document['status'] == 'active':
                document.update(status='interrupted', closed_at=timestamp(), close_reason='server_restart')
                self.save(document)

    def listing(self, limit=50, offset=0):
        rows = []
        for document in self.documents():
            turns = document['turns']
            rows.append({key: document.get(key) for key in
                         ('session_id', 'created_at', 'updated_at', 'closed_at', 'status', 'close_reason')}
                        | {'turn_count': len(turns), 'pending_request': document.get('in_progress') is not None,
                           'preview': next((turn['trace'].get('transcript', '')[:100] for turn in turns if turn['trace'].get('transcript')), ''),
                           'last_status': turns[-1]['trace'].get('status') if turns else None})
        rows.sort(key=lambda row: row['updated_at'], reverse=True)
        return {'sessions': rows[offset:offset + limit], 'total': len(rows)}


def archive_snapshot(document):
    return {**document, 'traces': [turn['trace'] for turn in document['turns']]}
