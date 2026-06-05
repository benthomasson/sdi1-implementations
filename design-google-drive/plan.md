# Plan (Iteration 1)

Task: DESIGN GOOGLE DRIVE
System Design Interview Vol 1 - Chapter 15

OVERVIEW
--------
Implement a cloud file storage system simulation as a single-process Python
application. The system supports file upload/download, versioning, chunked
upload for large files, file and folder metadata management, sharing with
permissions, and sync conflict detection. All file content is stored in-memory
as strings or bytes, simulating a cloud storage service like Google Drive or
Dropbox.

REQUIREMENTS
------------
1.  Implement a FileMetadata data model: file_id, name, path (folder hierarchy),
    size_bytes, mime_type, owner_id, created_at, modified_at, checksum (SHA-256
    of content), is_folder, parent_folder_id.
2.  Implement a FileStore for storing file content and metadata:
    - upload_file(name, content, owner_id, parent_folder_id, current_time) -> FileMetadata
    - download_file(file_id, user_id) -> tuple[bytes, FileMetadata]
    - delete_file(file_id, user_id) -> bool (soft delete)
    - move_file(file_id, new_parent_id, user_id) -> FileMetadata
    - rename_file(file_id, new_name, user_id) -> FileMetadata
3.  Implement folder hierarchy:
    - create_folder(name, owner_id, parent_folder_id) -> FileMetadata
    - list_folder(folder_id, user_id) -> list[FileMetadata]
    - Root folder per user (created automatically).
    - Support nested folders with full path resolution.
    - get_path(file_id) -> str (e.g., "/documents/work/report.pdf")
4.  Implement file versioning:
    - Each file maintains a version history (list of FileVersion objects).
    - upload_file to an existing path creates a new version.
    - update_file(file_id, new_content, user_id, current_time) -> FileVersion
    - get_versions(file_id) -> list[FileVersion]
    - restore_version(file_id, version_number, user_id) -> FileMetadata
    - Maximum versions per file (configurable, default 100). Oldest versions
      are pruned when limit exceeded.
5.  Implement chunked upload for large files:
    - init_chunked_upload(name, total_size, chunk_size, owner_id) -> upload_id
    - upload_chunk(upload_id, chunk_index, chunk_data) -> bool
    - complete_chunked_upload(upload_id, user_id) -> FileMetadata
    - abort_chunked_upload(upload_id) -> bool
    - Track which chunks have been uploaded; allow resume by re-uploading
      missing chunks.
    - Validate all chunks received before completing.
    - Each chunk has its own checksum for integrity verification.
6.  Implement sharing and permissions:
    - share(file_id, owner_id, target_user_id, permission: "read"|"write"|"admin")
    - revoke(file_id, owner_id, target_user_id)
    - get_shared_with(file_id) -> dict[user_id, permission]
    - Permission inheritance: a shared folder grants access to all children.
    - Check permission before any file operation (download, update, delete).
    - Admin can reshare, write can edit, read can only download.
7.  Implement sync conflict detection:
    - Each file has a version_vector (dict of {device_id: version_number}).
    - When two devices edit the same file, detect the conflict.
    - detect_conflict(file_id, device_id, base_version) -> bool
    - resolve_conflict(file_id, strategy: "latest_wins"|"keep_both") -> FileMetadata
    - "keep_both" creates a copy with " (conflict)" appended to name.
8.  Implement storage quota per user:
    - Configurable max storage per user (default 1GB simulated).
    - Track used storage per user.
    - Reject uploads that would exceed quota.
    - get_usage(user_id) -> tuple[used_bytes, total_bytes]
9.  Implement file search: search by name (substring match) and by file type
    (mime_type filter).
10. Implement a trash/recycle bin: deleted files go to trash, can be restored
    or permanently deleted. Trash auto-empties after configurable days (simulated
    via timestamps).

DATA MODELS
-----------
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import hashlib

class Permission(Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"

@dataclass
class FileVersion:
    version_number: int
    content_hash: str
    size_bytes: int
    modified_at: float
    modified_by: str
    content: bytes = b""

@dataclass
class FileMetadata:
    file_id: str
    name: str
    size_bytes: int
    mime_type: str
    owner_id: str
    created_at: float
    modified_at: float
    checksum: str
    is_folder: bool = False
    parent_folder_id: Optional[str] = None
    is_deleted: bool = False
    deleted_at: Optional[float] = None
    current_version: int = 1
    shared_with: dict[str, Permission] = field(default_factory=dict)
    version_vector: dict[str, int] = field(default_factory=dict)

@dataclass
class ChunkedUpload:
    upload_id: str
    file_name: str
    total_size: int
    chunk_size: int
    total_chunks: int
    owner_id: str
    chunks: dict[int, bytes] = field(default_factory=dict)  # {chunk_index: data}
    chunk_checksums: dict[int, str] = field(default_factory=dict)
    started_at: float = 0.0
    completed: bool = False

class FileStore:
    def __init__(self, max_versions: int = 100,
                 default_quota_bytes: int = 1_073_741_824): ...

    # File operations
    def upload_file(self, name: str, content: bytes, owner_id: str,
                    parent_folder_id: Optional[str] = None,
                    current_time: float = None) -> FileMetadata: ...
    def download_file(self, file_id: str, user_id: str) -> tuple[bytes, FileMetadata]: ...
    def update_file(self, file_id: str, new_content: bytes, user_id: str,
                    device_id: str = "default",
                    current_time: float = None) -> FileVersion: ...
    def delete_file(self, file_id: str, user_id: str,
                    current_time: float = None) -> bool: ...
    def move_file(self, file_id: str, new_parent_id: str,
                  user_id: str) -> FileMetadata: ...
    def rename_file(self, file_id: str, new_name: str,
                    user_id: str) -> FileMetadata: ...

    # Folder operations
    def create_folder(self, name: str, owner_id: str,
                      parent_folder_id: Optional[str] = None,
                      current_time: float = None) -> FileMetadata: ...
    def list_folder(self, folder_id: str, user_id: str) -> list[FileMetadata]: ...
    def get_path(self, file_id: str) -> str: ...

    # Versioning
    def get_versions(self, file_id: str) -> list[FileVersion]: ...
    def restore_version(self, file_id: str, version_number: int,
                        user_id: str, current_time: float = None) -> FileMetadata: ...

    # Chunked upload
    def init_chunked_upload(self, name: str, total_size: int, chunk_size: int,
                            owner_id: str, current_time: float = None) -> str: ...
    def upload_chunk(self, upload_id: str, chunk_index: int,
                     chunk_data: bytes) -> bool: ...
    def complete_chunked_upload(self, upload_id: str,
                                parent_folder_id: Optional[str] = None,
                                current_time: float = None) -> FileMetadata: ...
    def abort_chunked_upload(self, upload_id: str) -> bool: ...

    # Sharing
    def share(self, file_id: str, owner_id: str, target_user_id: str,
              permission: Permission): ...
    def revoke(self, file_id: str, owner_id: str, target_user_id: str): ...
    def get_shared_with(self, file_id: str) -> dict[str, Permission]: ...

    # Conflict detection
    def detect_conflict(self, file_id: str, device_id: str,
                        base_version: int) -> bool: ...
    def resolve_conflict(self, file_id: str, strategy: str = "latest_wins",
                         user_id: str = None,
                         current_time: float = None) -> FileMetadata: ...

    # Quota
    def get_usage(self, user_id: str) -> tuple[int, int]: ...

    # Search
    def search(self, user_id: str, query: str = None,
               mime_type: str = None) -> list[FileMetadata]: ...

    # Trash
    def restore_from_trash(self, file_id: str, user_id: str) -> FileMetadata: ...
    def empty_trash(self, user_id: str, current_time: float = None,
                    auto_days: float = 30.0): ...
    def list_trash(self, user_id: str) -> list[FileMetadata]: ...

API SPECIFICATION
-----------------
store = FileStore(default_quota_bytes=1_000_000)  # 1MB quota for testing

# Create folder structure
docs = store.create_folder("documents", "alice", current_time=1000.0)
work = store.create_folder("work", "alice", parent_folder_id=docs.file_id, current_time=1000.0)

# Upload file
report = store.upload_file(
    "report.pdf", b"PDF content here...", "alice",
    parent_folder_id=work.file_id, current_time=1001.0
)
assert report.name == "report.pdf"
assert store.get_path(report.file_id) == "/documents/work/report.pdf"

# Download
content, meta = store.download_file(report.file_id, "alice")
assert content == b"PDF content here..."

# Update (creates new version)
v2 = store.update_file(report.file_id, b"Updated PDF content", "alice", current_time=1002.0)
assert v2.version_number == 2

# Version history
versions = store.get_versions(report.file_id)
assert len(versions) == 2

# Restore old version
store.restore_version(report.file_id, version_number=1, user_id="alice", current_time=1003.0)
content, _ = store.download_file(report.file_id, "alice")
assert content == b"PDF content here..."

# Share with another user
store.share(report.file_id, "alice", "bob", Permission.READ)
content, _ = store.download_file(report.file_id, "bob")  # bob can read
try:
    store.update_file(report.file_id, b"Hacked!", "bob")  # bob can't write
    assert False
except PermissionError:
    pass

# Chunked upload
upload_id = store.init_chunked_upload("big_file.zip", total_size=3000, chunk_size=1000,
                                       owner_id="alice", current_time=2000.0)
store.upload_chunk(upload_id, 0, b"x" * 1000)
store.upload_chunk(upload_id, 1, b"y" * 1000)
store.upload_chunk(upload_id, 2, b"z" * 1000)
big_file = store.complete_chunked_upload(upload_id, current_time=2001.0)
assert big_file.size_bytes == 3000

# Quota
used, total = store.get_usage("alice")
assert used > 0

# Conflict detection
store.update_file(report.file_id, b"Device A edit", "alice", device_id="phone", current_time=3000.0)
has_conflict = store.detect_conflict(report.file_id, device_id="laptop", base_version=1)
assert has_conflict == True

# Search
results = store.search("alice", query="report")
assert len(results) >= 1

# Delete to trash
store.delete_file(report.file_id, "alice", current_time=4000.0)
trash = store.list_trash("alice")
assert any(f.file_id == report.file_id for f in trash)

# Restore from trash
store.restore_from_trash(report.file_id, "alice")

EXAMPLE USAGE WITH ASSERTIONS
------------------------------
store = FileStore()

# Basic upload and download
f = store.upload_file("test.txt", b"Hello World", "user1", current_time=100.0)
assert f.name == "test.txt"
assert f.size_bytes == 11
assert f.checksum == hashlib.sha256(b"Hello World").hexdigest()

content, meta = store.download_file(f.file_id, "user1")
assert content == b"Hello World"

# Folder hierarchy
root = store.create_folder("root", "user1")
sub = store.create_folder("sub", "user1", parent_folder_id=root.file_id)
f2 = store.upload_file("nested.txt", b"data", "user1", parent_folder_id=sub.file_id)
assert store.get_path(f2.file_id) == "/root/sub/nested.txt"

# List folder
items = store.list_folder(root.file_id, "user1")
assert any(i.name == "sub" for i in items)

# Versioning
store.update_file(f.file_id, b"Updated", "user1", current_time=200.0)
store.update_file(f.file_id, b"Updated Again", "user1", current_time=300.0)
versions = store.get_versions(f.file_id)
assert len(versions) == 3

# Sharing and permission check
store.share(f.file_id, "user1", "user2", Permission.READ)
content, _ = store.download_file(f.file_id, "user2")  # works
try:
    store.update_file(f.file_id, b"Unauthorized", "user2")
    assert False
except PermissionError:
    pass

store.share(f.file_id, "user1", "user2", Permission.WRITE)
store.update_file(f.file_id, b"Authorized", "user2", current_time=400.0)  # now works

# Chunked upload resume
uid = store.init_chunked_upload("large.bin", 2000, 1000, "user1")
store.upload_chunk(uid, 0, b"A" * 1000)
# Simulate interruption — chunk 1 missing
try:
    store.complete_chunked_upload(uid)
    assert False  # should fail
except ValueError:
    pass
store.upload_chunk(uid, 1, b"B" * 1000)
result = store.complete_chunked_upload(uid)
assert result.size_bytes == 2000

# Quota enforcement
small_store = FileStore(default_quota_bytes=100)
small_store.upload_file("small.txt", b"x" * 50, "user1")
try:
    small_store.upload_file("big.txt", b"x" * 60, "user1")
    assert False  # exceeds quota
except Exception:
    pass

# Conflict resolution: keep_both
store2 = FileStore()
f = store2.upload_file("doc.txt", b"original", "u1", current_time=100.0)
store2.update_file(f.file_id, b"edit from phone", "u1", device_id="phone", current_time=200.0)
if store2.detect_conflict(f.file_id, "laptop", base_version=1):
    result = store2.resolve_conflict(f.file_id, strategy="keep_both", user_id="u1", current_time=201.0)
    # A conflict copy should exist

CONSTRAINTS
-----------
- All file content stored in-memory as bytes
- File IDs: UUID4 strings
- Checksums: SHA-256
- Maximum file size: 100MB simulated (100_000_000 bytes)
- Maximum versions per file: configurable (default 100)
- Chunked upload: chunks must be sequential indices starting from 0
- Permission hierarchy: ADMIN > WRITE > READ
- No external dependencies beyond Python standard library
- Target: 350-500 lines of code

TESTING REQUIREMENTS
--------------------
Write tests in test_design_google_drive.py using pytest. Include these test cases:

1.  Upload and download returns original content
2.  File checksum matches SHA-256 of content
3.  Folder creation and listing works correctly
4.  Nested folder path resolution returns correct path
5.  File versioning creates new versions on update
6.  Restore version reverts file content to old version
7.  Maximum version limit prunes oldest versions
8.  Chunked upload assembles all chunks correctly
9.  Chunked upload fails if chunks are missing
10. Share with READ permission allows download but not update
11. Share with WRITE permission allows update
12. Unshared user cannot access file (raises PermissionError)
13. Conflict detection identifies concurrent edits from different devices
14. Conflict resolution with keep_both creates a copy
15. Storage quota blocks uploads that exceed limit

IMPORTANT - EFFORT LEVEL: MINIMAL
Keep plan VERY brief (2-3 paragraphs max). Focus only on algorithm choice. Skip architectural discussions and detailed analysis.

Plan written to `PLAN.md`. 

**Summary:** Single-class `FileStore` with in-memory dicts, implementing all 10 requirements in order: data models → folders → file CRUD → versioning → chunked upload → sharing with inheritance → conflict detection → quota → search → trash. ~400 lines, no external deps. The spec is detailed enough that this is a straightforward faithful implementation — confidence is **HIGH**.

[Committed changes to planner branch]