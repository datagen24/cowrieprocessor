"""
Cowrie Processing Pipeline

Features:
- Raw event storage with JSON + BLAKE3 checksums
- Audit trails
- DLQ for malformed events
- Bulk & delta ingestion
- Telemetry for ingestion, parsing failures, DLQ inserts
- Summary derivation (sessions, commands)

CLI Commands:
- python cowrie_pipeline.py init
- python cowrie_pipeline.py bulk /path/to/logs --force-hash
- python cowrie_pipeline.py delta /path/to/logs
- python cowrie_pipeline.py report 2025-09-23

"""

import sqlite3
import json
import os
import hashlib
import time
from datetime import datetime, timedelta
import click
import blake3  # pip install blake3

DB_PATH = "data/cowrie.db"
BATCH_SIZE = 1000
DEFAULT_USER = "system"

# -----------------
# Utilities
# -----------------

def now_iso():
    return datetime.utcnow().isoformat() + "Z"

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def compute_blake3(path):
    h = blake3.blake3()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

# -----------------
# DB helpers
# -----------------

def get_conn(path=DB_PATH):
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    # Useful pragmas
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-64000;")
    return conn

def record_telemetry(conn, phase, phase_step, details=None):
    conn.execute(
        "INSERT INTO telemetry(phase, phase_step, details, created_at) VALUES (?, ?, ?, ?)",
        (phase, phase_step, json.dumps(details) if details else None, now_iso())
    )
    conn.commit()

def init_db(path=DB_PATH):
    conn = get_conn(path)
    cur = conn.cursor()
    cur.executescript(r"""
    CREATE TABLE IF NOT EXISTS raw_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_file TEXT NOT NULL,
        file_offset INTEGER DEFAULT 0,
        ingest_ts TEXT DEFAULT (datetime('now')),
        event_ts TEXT,
        session_id TEXT,
        event_type TEXT,
        raw_json TEXT NOT NULL,
        raw_hash TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_raw_events_session ON raw_events(session_id);
    CREATE INDEX IF NOT EXISTS idx_raw_events_event_ts ON raw_events(event_ts);
    CREATE INDEX IF NOT EXISTS idx_raw_events_sourcefile ON raw_events(source_file);

    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        src_ip TEXT,
        src_port INTEGER,
        username TEXT,
        auth_success INTEGER DEFAULT 0,
        start_ts TEXT,
        end_ts TEXT,
        duration_seconds INTEGER,
        commands_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        last_updated TEXT DEFAULT (datetime('now')),
        created_by TEXT DEFAULT 'system',
        modified_by TEXT,
        modified_at TEXT
    );

    CREATE TABLE IF NOT EXISTS command_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        command TEXT,
        command_ts TEXT,
        exit_code INTEGER,
        output_snippet TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        created_by TEXT DEFAULT 'system',
        modified_by TEXT,
        modified_at TEXT
    );

    CREATE TABLE IF NOT EXISTS ingest_manifest (
        source_file TEXT PRIMARY KEY,
        last_modified_ts TEXT,
        file_size INTEGER,
        file_hash TEXT,
        last_line_read INTEGER DEFAULT 0,
        last_ingest_ts TEXT
    );

    CREATE TABLE IF NOT EXISTS telemetry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phase TEXT NOT NULL,
        phase_step TEXT NOT NULL,
        details TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS dlq (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_json TEXT,
        error TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    conn.close()
    print(f"Initialized DB at {path}")

# -----------------
# Parsing helpers
# -----------------

def parse_cowrie_line(line):
    try:
        obj = json.loads(line)
        # Minimal JSON validation
        if 'session' in obj or 'session_id' in obj and 'timestamp' in obj:
            return obj
        return None
    except Exception:
        return None

# -----------------
# Loader helpers
# -----------------

def insert_raw_batch(conn, rows):
    sql = """INSERT INTO raw_events(source_file, file_offset, event_ts, session_id, event_type, raw_json, raw_hash, ingest_ts)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
    conn.executemany(sql, rows)

def process_one_file(conn, file_path, force_hash=False):
    st = os.stat(file_path)
    mtime = datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z"
    fsize = st.st_size
    file_hash = compute_blake3(file_path) if force_hash else None

    cur = conn.cursor()
    cur.execute("SELECT last_modified_ts, file_size, file_hash, last_line_read FROM ingest_manifest WHERE source_file=?", (file_path,))
    row = cur.fetchone()
    if row and row["last_modified_ts"]==mtime and row["file_size"]==fsize and (not force_hash or row["file_hash"]==file_hash):
        return 0

    rows=[]
    inserted=0
    record_telemetry(conn, "bulk-ingest","start-file",{"file":file_path})
    with open(file_path,"r",encoding="utf8",errors="replace") as fh:
        for offset,line in enumerate(fh,start=1):
            obj=parse_cowrie_line(line)
            if not obj:
                conn.execute("INSERT INTO dlq(raw_json,error) VALUES (?,?)",(line,"parse_error"))
                record_telemetry(conn,"bulk-ingest","dlq-insert",{"line":offset})
                continue
            evt=obj.get('event') or obj.get('eventid')
            session=obj.get('session') or obj.get('sessionid') or obj.get('session_id')
            ts=obj.get('timestamp') or obj.get('time') or obj.get('event_time')
            raw_json=json.dumps(obj,ensure_ascii=False)
            raw_hash=blake3.blake3(raw_json.encode()).hexdigest()
            rows.append((file_path, offset, ts, session, evt, raw_json, raw_hash, now_iso()))
            if len(rows)>=BATCH_SIZE:
                conn.execute("BEGIN")
                insert_raw_batch(conn,rows)
                conn.commit()
                inserted+=len(rows)
                rows=[]
    if rows:
        conn.execute("BEGIN")
        insert_raw_batch(conn,rows)
        conn.commit()
        inserted+=len(rows)

    cur.execute("""INSERT INTO ingest_manifest(source_file,last_modified_ts,file_size,file_hash,last_line_read,last_ingest_ts)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(source_file) DO UPDATE SET
                   last_modified_ts=excluded.last_modified_ts,
                   file_size=excluded.file_size,
                   file_hash=excluded.file_hash,
                   last_line_read=excluded.last_line_read,
                   last_ingest_ts=excluded.last_ingest_ts""",
                   (file_path,mtime,fsize,file_hash,offset,now_iso()))
    conn.commit()
    record_telemetry(conn,"bulk-ingest","done-file",{"file":file_path,"rows":inserted})
    return inserted

def bulk_load(logs_dir, force_hash=False):
    conn=get_conn()
    record_telemetry(conn,"bulk-ingest","start",{"dir":logs_dir})
    files=[os.path.join(logs_dir,f) for f in os.listdir(logs_dir) if f.endswith((".log",".json",".txt"))]
    total=0
    for f in sorted(files):
        try:
            total+=process_one_file(conn,f,force_hash)
        except Exception as e:
            record_telemetry(conn,"bulk-ingest","error",{"file":f,"error":str(e)})
    derive_summaries(conn)
    record_telemetry(conn,"bulk-ingest","done",{"dir":logs_dir,"rows":total})
    conn.close()
    print(f"Bulk load finished: {total} rows inserted")

def delta_load(logs_dir):
    conn=get_conn()
    record_telemetry(conn,"delta-ingest","start",{"dir":logs_dir})
    files=[os.path.join(logs_dir,f) for f in os.listdir(logs_dir) if f.endswith((".log",".json",".txt"))]
    total=0
    cur=conn.cursor()
    for f in sorted(files):
        st=os.stat(f)
        fsize=st.st_size
        mtime=datetime.utcfromtimestamp(st.st_mtime).isoformat()+"Z"
        cur.execute("SELECT last_modified_ts,file_size,last_line_read FROM ingest_manifest WHERE source_file=?",(f,))
        row=cur.fetchone()
        last_line=row["last_line_read"] if row else 0
        if row and row["file_size"]==fsize and row["last_modified_ts"]==mtime:
            continue
        inserted=0
        record_telemetry(conn,"delta-ingest","start-file",{"file":f,"from_line":last_line+1})
        with open(f,"r",encoding="utf8",errors="replace") as fh:
            for offset,line in enumerate(fh,start=1):
                if offset<=last_line:
                    continue
                obj=parse_cowrie_line(line)
                if not obj:
                    conn.execute("INSERT INTO dlq(raw_json,error) VALUES (?,?)",(line,"parse_error"))
                    record_telemetry(conn,"delta-ingest","dlq-insert",{"line":offset})
                    continue
                evt=obj.get('event') or obj.get('eventid')
                session=obj.get('session') or obj.get('sessionid') or obj.get('session_id')
                ts=obj.get('timestamp') or obj.get('time') or obj.get('event_time')
                raw_json=json.dumps(obj,ensure_ascii=False)
                raw_hash=blake3.blake3(raw_json.encode()).hexdigest()
                conn.execute("INSERT INTO raw_events(source_file,file_offset,event_ts,session_id,event_type,raw_json,raw_hash,ingest_ts) VALUES (?,?,?,?,?,?,?,?)",
                             (f,offset,ts,session,evt,raw_json,raw_hash,now_iso()))
                inserted+=1
                if inserted%BATCH_SIZE==0:
                    conn.commit()
        conn.execute("""INSERT INTO ingest_manifest(source_file,last_modified_ts,file_size,last_line_read,last_ingest_ts)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(source_file) DO UPDATE SET
                       last_modified_ts=excluded.last_modified_ts,
                       file_size=excluded.file_size,
                       last_line_read=excluded.last_line_read,
                       last_ingest_ts=excluded.last_ingest_ts""",(f,mtime,fsize,offset,now_iso()))
        conn.commit()
        record_telemetry(conn,"delta-ingest","done-file",{"file":f,"rows":inserted})
        total+=inserted
    derive_summaries(conn)
    record_telemetry(conn,"delta-ingest","done",{"dir":logs_dir,"rows":total})
    conn.close()
    print(f"Delta load finished: {total} rows inserted")

# -----------------
# Summary Derivation
# -----------------

def derive_summaries(conn=None):
    close_conn=False
    if conn is None:
        conn=get_conn()
        close_conn=True
    record_telemetry(conn,"derive","start")
    cur=conn.cursor()
    cur.execute("SELECT id,raw_json FROM raw_events ORDER BY id")
    rows=cur.fetchall()
    processed=0
    for batch_start in range(0,len(rows),BATCH_SIZE):
        batch=rows[batch_start:batch_start+BATCH_SIZE]
        with conn:
            for rid in batch:
                try:
                    obj=json.loads(rid["raw_json"])
                    evt=obj.get('event') or obj.get('eventid')
                    session=obj.get('session') or obj.get('sessionid') or obj.get('session_id')
                    ts=obj.get('timestamp') or obj.get('time')
                    if evt in ('session.connect','session.start','session.connect.succeeded'):
                        src_ip=obj.get('src_ip') or obj.get('src_ip_addr')
                        conn.execute("""INSERT INTO sessions(session_id,src_ip,username,start_ts,last_updated,created_by)
                                        VALUES(?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET src_ip=COALESCE(excluded.src_ip,sessions.src_ip),
                                        start_ts=COALESCE(sessions.start_ts,excluded.start_ts),
                                        last_updated=?""",(session,src_ip,obj.get('username'),ts,now_iso(),DEFAULT_USER,now_iso()))
                    if evt in ('cmd_input','command.input','input'):
                        command=obj.get('input') or obj.get('message') or obj.get('command')
                        snippet=(command or '')[:400]
                        conn.execute("""INSERT INTO command_stats(session_id,command,command_ts,output_snippet,created_by)
                                        VALUES(?,?,?,?,?)""",(session,snippet,ts,snippet,DEFAULT_USER))
                        conn.execute("UPDATE sessions SET commands_count=COALESCE(commands_count,0)+1,last_updated=? WHERE session_id=?",(now_iso(),session))
                    if evt in ('session.closed','session.closed.failed','session.end'):
                        cur_s=conn.execute("SELECT start_ts FROM sessions WHERE session_id=?",(session,)).fetchone()
                        start_ts=cur_s[0] if cur_s else None
                        duration=None
                        if start_ts and ts:
                            try:
                                sd=datetime.fromisoformat(start_ts.replace('Z',''))
                                ed=datetime.fromisoformat(ts.replace('Z',''))
                                duration=int((ed-sd).total_seconds())
                            except:
                                duration=None
                        conn.execute("UPDATE sessions SET end_ts=?,duration_seconds=COALESCE(?,duration_seconds),last_updated=? WHERE session_id=?",(ts,duration,now_iso(),session))
                    processed+=1
                except Exception as e:
                    conn.execute("INSERT INTO dlq(raw_json,error) VALUES (?,?)",(rid["raw_json"],str(e)))
    record_telemetry(conn,"derive","done",{"rows":processed})
    if close_conn:
        conn.close()
    print(f"Derived summaries: processed {processed} raw_events")

# -----------------
# Reporting
# -----------------

def report_daily(conn,date_str):
    start=date_str+"T00:00:00"
    end=(datetime.fromisoformat(date_str)+timedelta(days=1)).isoformat()
    cur=conn.cursor()
    cur.execute("SELECT COUNT(*) as sessions, AVG(duration_seconds) as avg_duration FROM sessions WHERE start_ts>=? AND start_ts<?",(start,end))
    sessions,avg_duration=cur.fetchone()
    print(f"Daily report {date_str}: sessions={sessions}, avg_duration={avg_duration}")
    cur.execute("SELECT command,COUNT(*) as cnt FROM command_stats WHERE command_ts>=? AND command_ts<? GROUP BY command ORDER BY cnt DESC LIMIT 50",(start,end))
    for r in cur.fetchall():
        print(f"{r[0]:40.40} {r[1]}")

# -----------------
# CLI
# -----------------

@click.group()
def cli():
    pass

@cli.command()
def init():
    init_db()

@cli.command()
@click.argument("logs_dir")
@click.option("--force-hash",is_flag=True,help="Force hash comparison")
def bulk(logs_dir,force_hash):
    bulk_load(logs_dir,force_hash)

@cli.command()
@click.argument("logs_dir")
def delta(logs_dir):
    delta_load(logs_dir)

@cli.command()
@click.argument("date")
def report(date):
    conn=get_conn()
    report_daily(conn,date)
    conn.close()

if __name__=="__main__":
    cli()
