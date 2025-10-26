"""Submit recent Cowrie downloads to VirusTotal and add a comment.

This script scans the configured downloads folder for files modified in the
last ~6 minutes, submits each file to VirusTotal, and posts an identifying
comment referencing the DShield honeypot.
"""

import argparse
import hashlib
import json
import os
import time

import requests
from secrets_resolver import is_reference, resolve_secret

parser = argparse.ArgumentParser(description='Virus Total file submission options')
parser.add_argument('--filepath', dest='filepath', type=str, help='Path of a specific file to submit')
parser.add_argument(
    '--folderpath',
    dest='folderpath',
    type=str,
    help='Folder ocation of files to process for submission',
    default='/srv/cowrie/var/lib/cowrie/downloads/',
)
parser.add_argument('--vtapi', dest='vtapi', type=str, help='VirusTotal API key (required for VT data lookup)')

args = parser.parse_args()

filepath = args.filepath
folderpath = args.folderpath
vtapi = args.vtapi or os.getenv('VT_API_KEY')
try:
    if is_reference(vtapi):
        vtapi = resolve_secret(vtapi)
except Exception:
    pass


def vt_filescan(filename: str) -> None:
    """Submit a file to VirusTotal and record responses.

    Args:
        filename: File name (not full path) located under ``folderpath``.

    Returns:
        None. Side effects: creates files in ``vtsubmissions/`` with
        submission and comment responses.
    """
    headers = {'X-Apikey': vtapi}
    url = "https://www.virustotal.com/api/v3/files"
    with open(folderpath + filename, 'rb') as file:
        files = {'file': (folderpath + filename, file)}
        response = requests.post(url, headers=headers, files=files)
    _ = json.loads(response.text)
    if not os.path.exists("vtsubmissions"):
        os.mkdir("vtsubmissions")
    with open("vtsubmissions/files_" + filename, 'w', encoding='utf-8') as out:
        out.write(response.text)

    filehash = sha256sum(folderpath + filename)
    headers = {'Content-type': 'application/json', 'X-Apikey': vtapi}
    url = "https://www.virustotal.com/api/v3/files/" + filehash + "/comments"
    commentdata = {
        'data': {
            'type': 'comment',
            'attributes': {'text': 'File submitted from a DShield Honeypot - https://github.com/DShield-ISC/dshield'},
        }
    }
    response = requests.post(url, headers=headers, data=json.dumps(commentdata))
    _ = json.loads(response.text)
    with open("vtsubmissions/files_comment_" + filename, 'w', encoding='utf-8') as out:
        out.write(response.text)


def sha256sum(filename: str) -> str:
    """Compute the SHA-256 checksum of a file.

    Args:
        filename: Full path to the file.

    Returns:
        Hex-encoded SHA-256 digest string.
    """
    h = hashlib.sha256()
    b = bytearray(128 * 1024)
    mv = memoryview(b)
    with open(filename, 'rb', buffering=0) as f:
        while n := f.readinto(mv):
            h.update(mv[:n])
    return h.hexdigest()


past = time.time() - ((60 * 60) / 11)  # 1/11 of an hour - just under 6 minutes
result = []
for p, ds, fs in os.walk(folderpath):
    for fn in fs:
        filepath = os.path.join(p, fn)
        if os.path.getmtime(filepath) >= past:
            result.append(fn)

for each_file in result:
    print(each_file)
    vt_filescan(each_file)

# vt_filescan("58458d88aeb274ebd87a2cc4dad0b64f3c38c8951a287b3b31c1f99c8240d38e")
