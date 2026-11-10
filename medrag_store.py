"""MedRAG corpus import and SQLite FTS5 BM25. Not the upstream MedCPT engine."""
import argparse
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from agents import ServiceFailure

DATASET = 'https://huggingface.co/datasets/MedRAG/textbooks'


def build_index(files, output, revision='main'):
    output = Path(output)
    if output.exists():
        raise ValueError('Index already exists; choose a new versioned path')
    output.parent.mkdir(parents=True, exist_ok=True)
    imported = datetime.now(timezone.utc).isoformat()
    manifest = {'dataset': DATASET, 'revision': revision, 'imported_at': imported,
                'reviewed': False, 'engine': 'sqlite_fts5_bm25', 'files': []}
    try:
        with closing(sqlite3.connect(output)) as db:
            db.execute('CREATE TABLE documents (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED, title, content, tokenize="porter unicode61")')
            count = 0
            for file in files:
                file = Path(file)
                manifest['files'].append({'name': file.name, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
                with file.open(encoding='utf-8-sig') as stream:
                    for line in stream:
                        if not line.strip():
                            continue
                        raw = json.loads(line)
                        if any(not isinstance(raw.get(k), str) or not raw[k].strip() for k in ('id', 'title', 'content')):
                            raise ValueError('Invalid MedRAG record')
                        if len(raw['content']) > 12000 or len(raw['id']) > 110:
                            raise ValueError('Oversized MedRAG record')
                        doc = {'id': 'medrag:' + raw['id'], 'title': raw['title'], 'content': raw['content'],
                            'source': DATASET + '/blob/' + revision + '/chunk/' + file.name,
                            'updated_at': 'unknown (corpus import: ' + imported + ')',
                            'population': 'Not specified by source; applicability requires review',
                            'reviewed': False, 'demo': False, 'dataset': 'MedRAG/textbooks',
                            'corpus_revision': revision, 'imported_at': imported,
                            'content_hash': hashlib.sha256(raw['content'].encode()).hexdigest()}
                        db.execute('INSERT INTO documents VALUES (?,?)', (doc['id'], json.dumps(doc, ensure_ascii=False)))
                        db.execute('INSERT INTO search VALUES (?,?,?)', (doc['id'], doc['title'], doc['content']))
                        count += 1
            if not count:
                raise ValueError('Empty corpus')
            manifest['documents'] = count
            db.execute('CREATE TABLE metadata (payload TEXT NOT NULL)')
            db.execute('INSERT INTO metadata VALUES (?)', (json.dumps(manifest),))
            db.commit()
    except Exception:
        output.unlink(missing_ok=True)
        raise
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def search_index(path, query, top_k=4, timeout=10):
    tokens = list(dict.fromkeys(re.findall(r'[a-zA-Z][a-zA-Z0-9-]*', query)))[:32]
    if not tokens:
        return []
    expression = ' OR '.join('"' + t + '"' for t in tokens)
    try:
        uri = Path(path).resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, timeout=timeout)) as db:
            import time
            deadline = time.monotonic() + timeout
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            rows = db.execute('SELECT documents.payload, bm25(search,0,2,1) AS score '
                'FROM search JOIN documents ON documents.id=search.id '
                'WHERE search MATCH ? ORDER BY score, documents.id LIMIT ?',
                (expression, min(top_k, 10))).fetchall()
        return [json.loads(payload) | {'score': -score} for payload, score in rows]
    except (sqlite3.Error, OSError, ValueError):
        raise ServiceFailure('medrag_index_unavailable') from None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', nargs='+', help='Official chunk/*.jsonl files already downloaded')
    parser.add_argument('--download', choices=['First_Aid_Step1', 'First_Aid_Step2'])
    parser.add_argument('--revision', default='main')
    parser.add_argument('--output', default='data/medrag.sqlite')
    args = parser.parse_args()
    files = args.input or []
    if args.download:
        target = Path('work/medrag-downloads') / (args.download + '.jsonl')
        target.parent.mkdir(parents=True, exist_ok=True)
        url = DATASET + '/resolve/' + args.revision + '/chunk/' + target.name
        with urlopen(url, timeout=90) as response:
            data = response.read(10_000_001)
        if len(data) > 10_000_000:
            raise SystemExit('Unexpected corpus download size')
        target.write_bytes(data)
        files.append(str(target))
    if not files:
        parser.error('Specify --input or --download')
    print(json.dumps(build_index(files, args.output, args.revision), indent=2))
