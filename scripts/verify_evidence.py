"""Read-only integrity check of the public historical subset; no experiments."""
import hashlib
import json
from goalflow_world.store import ROOT


def main():
    folder = ROOT/'evidence'
    manifest = json.loads((folder/'manifest.json').read_text())
    originals = json.loads((folder/'original-checksum-subset.json').read_text())
    for entry in manifest['files']:
        path = (folder/entry['path']).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file():
            raise ValueError('Invalid evidence path')
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry['sha256']:
            raise ValueError('Evidence checksum mismatch: '+entry['path'])
        if entry['path'] in originals and actual != originals[entry['path']]['sha256']:
            raise ValueError('Original checksum mismatch')
    results = json.loads((folder/'lifecycle/results.json').read_text())
    if len(results) != 112 or not all(row['passed'] for row in results):
        raise ValueError('Historical results differ')
    # Check exact upstream Git blobs, independently of the project license.
    vendor = ROOT/'experiments/work-lifecycle/backends/paperclip'
    for entry in json.loads((vendor/'provenance.json').read_text()):
        raw = (vendor/entry['local_path']).read_bytes()
        blob = b'blob '+str(len(raw)).encode()+b'\0'+raw
        if hashlib.sha1(blob).hexdigest() != entry['git_blob_sha']:
            raise ValueError('Upstream Git blob mismatch')
    print(f"{len(manifest['files'])} historical records verified; 112/112 saved cells; Paperclip Git blobs verified. No historical experiment rerun.")

if __name__ == '__main__':
    main()
