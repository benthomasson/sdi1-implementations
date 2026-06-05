"""Tests for Google Drive file storage simulation."""

import hashlib
import pytest
from design_google_drive import FileStore, Permission


def test_upload_and_download():
    store = FileStore()
    f = store.upload_file("test.txt", b"Hello World", "user1", current_time=100.0)
    content, meta = store.download_file(f.file_id, "user1")
    assert content == b"Hello World"
    assert meta.name == "test.txt"
    assert meta.size_bytes == 11


def test_file_checksum():
    store = FileStore()
    data = b"Hello World"
    f = store.upload_file("test.txt", data, "user1")
    assert f.checksum == hashlib.sha256(data).hexdigest()


def test_folder_creation_and_listing():
    store = FileStore()
    folder = store.create_folder("docs", "user1", current_time=100.0)
    f = store.upload_file("a.txt", b"data", "user1", parent_folder_id=folder.file_id)
    items = store.list_folder(folder.file_id, "user1")
    assert len(items) == 1
    assert items[0].name == "a.txt"


def test_nested_folder_path():
    store = FileStore()
    root = store.create_folder("root", "user1")
    sub = store.create_folder("sub", "user1", parent_folder_id=root.file_id)
    f = store.upload_file("nested.txt", b"data", "user1", parent_folder_id=sub.file_id)
    assert store.get_path(f.file_id) == "/root/sub/nested.txt"


def test_versioning_on_update():
    store = FileStore()
    f = store.upload_file("test.txt", b"v1", "user1", current_time=100.0)
    store.update_file(f.file_id, b"v2", "user1", current_time=200.0)
    store.update_file(f.file_id, b"v3", "user1", current_time=300.0)
    versions = store.get_versions(f.file_id)
    assert len(versions) == 3
    assert versions[0].version_number == 1
    assert versions[2].version_number == 3


def test_restore_version():
    store = FileStore()
    f = store.upload_file("test.txt", b"original", "user1", current_time=100.0)
    store.update_file(f.file_id, b"updated", "user1", current_time=200.0)
    store.restore_version(f.file_id, version_number=1, user_id="user1", current_time=300.0)
    content, _ = store.download_file(f.file_id, "user1")
    assert content == b"original"


def test_max_version_limit():
    store = FileStore(max_versions=3)
    f = store.upload_file("test.txt", b"v1", "user1", current_time=100.0)
    for i in range(2, 6):
        store.update_file(f.file_id, f"v{i}".encode(), "user1", current_time=100.0 + i)
    versions = store.get_versions(f.file_id)
    assert len(versions) == 3
    assert versions[0].version_number == 3  # oldest kept


def test_chunked_upload():
    store = FileStore()
    uid = store.init_chunked_upload("big.bin", 3000, 1000, "user1", current_time=100.0)
    store.upload_chunk(uid, 0, b"A" * 1000)
    store.upload_chunk(uid, 1, b"B" * 1000)
    store.upload_chunk(uid, 2, b"C" * 1000)
    result = store.complete_chunked_upload(uid, current_time=101.0)
    assert result.size_bytes == 3000
    content, _ = store.download_file(result.file_id, "user1")
    assert content == b"A" * 1000 + b"B" * 1000 + b"C" * 1000


def test_chunked_upload_missing_chunk():
    store = FileStore()
    uid = store.init_chunked_upload("big.bin", 2000, 1000, "user1")
    store.upload_chunk(uid, 0, b"A" * 1000)
    with pytest.raises(ValueError):
        store.complete_chunked_upload(uid)


def test_share_read_allows_download_not_update():
    store = FileStore()
    f = store.upload_file("test.txt", b"data", "user1")
    store.share(f.file_id, "user1", "user2", Permission.READ)
    content, _ = store.download_file(f.file_id, "user2")
    assert content == b"data"
    with pytest.raises(PermissionError):
        store.update_file(f.file_id, b"hacked", "user2")


def test_share_write_allows_update():
    store = FileStore()
    f = store.upload_file("test.txt", b"data", "user1")
    store.share(f.file_id, "user1", "user2", Permission.WRITE)
    v = store.update_file(f.file_id, b"updated by user2", "user2", current_time=200.0)
    assert v.version_number == 2


def test_unshared_user_cannot_access():
    store = FileStore()
    f = store.upload_file("test.txt", b"secret", "user1")
    with pytest.raises(PermissionError):
        store.download_file(f.file_id, "user2")


def test_conflict_detection():
    store = FileStore()
    f = store.upload_file("doc.txt", b"original", "u1", current_time=100.0)
    store.update_file(f.file_id, b"phone edit", "u1", device_id="phone", current_time=200.0)
    assert store.detect_conflict(f.file_id, "laptop", base_version=1) is True
    assert store.detect_conflict(f.file_id, "phone", base_version=2) is False


def test_conflict_keep_both():
    store = FileStore()
    f = store.upload_file("doc.txt", b"original", "u1", current_time=100.0)
    store.update_file(f.file_id, b"phone edit", "u1", device_id="phone", current_time=200.0)
    laptop_content = b"laptop edit"
    copy = store.resolve_conflict(f.file_id, strategy="keep_both", user_id="u1",
                                  current_time=201.0, conflicting_content=laptop_content)
    assert "(conflict)" in copy.name
    assert copy.file_id != f.file_id
    content, _ = store.download_file(copy.file_id, "u1")
    assert content == laptop_content


def test_quota_enforcement():
    store = FileStore(default_quota_bytes=100)
    store.upload_file("small.txt", b"x" * 50, "user1")
    with pytest.raises(ValueError):
        store.upload_file("big.txt", b"x" * 60, "user1")


def test_search():
    store = FileStore()
    store.upload_file("report.pdf", b"data", "user1")
    store.upload_file("notes.txt", b"data", "user1")
    results = store.search("user1", query="report")
    assert len(results) == 1
    assert results[0].name == "report.pdf"


def test_trash_and_restore():
    store = FileStore()
    f = store.upload_file("test.txt", b"data", "user1", current_time=100.0)
    store.delete_file(f.file_id, "user1", current_time=200.0)
    trash = store.list_trash("user1")
    assert any(t.file_id == f.file_id for t in trash)
    store.restore_from_trash(f.file_id, "user1")
    content, _ = store.download_file(f.file_id, "user1")
    assert content == b"data"


def test_permission_inheritance():
    store = FileStore()
    folder = store.create_folder("shared", "user1")
    f = store.upload_file("child.txt", b"data", "user1", parent_folder_id=folder.file_id)
    store.share(folder.file_id, "user1", "user2", Permission.READ)
    content, _ = store.download_file(f.file_id, "user2")
    assert content == b"data"


def test_empty_trash():
    store = FileStore()
    f = store.upload_file("old.txt", b"data", "user1", current_time=100.0)
    store.delete_file(f.file_id, "user1", current_time=100.0)
    # 31 days later
    store.empty_trash("user1", current_time=100.0 + 31 * 86400)
    assert len(store.list_trash("user1")) == 0


def test_move_and_rename():
    store = FileStore()
    f1 = store.create_folder("a", "user1")
    f2 = store.create_folder("b", "user1")
    f = store.upload_file("test.txt", b"data", "user1", parent_folder_id=f1.file_id)
    store.move_file(f.file_id, f2.file_id, "user1")
    assert store.get_path(f.file_id) == "/b/test.txt"
    store.rename_file(f.file_id, "renamed.txt", "user1")
    assert store.get_path(f.file_id) == "/b/renamed.txt"


def test_recursive_folder_delete():
    """Deleting a folder cascades to its children."""
    store = FileStore()
    parent = store.create_folder("parent", "user1")
    child = store.create_folder("child", "user1", parent_folder_id=parent.file_id)
    f = store.upload_file("deep.txt", b"data", "user1", parent_folder_id=child.file_id)
    store.delete_file(parent.file_id, "user1", current_time=100.0)
    assert store.files[child.file_id].is_deleted
    assert store.files[f.file_id].is_deleted


def test_move_checks_destination_permission():
    """Cannot move a file into a folder the user doesn't have WRITE on."""
    store = FileStore()
    src = store.create_folder("src", "user1")
    dst = store.create_folder("dst", "user2")
    f = store.upload_file("test.txt", b"data", "user1", parent_folder_id=src.file_id)
    with pytest.raises(PermissionError):
        store.move_file(f.file_id, dst.file_id, "user1")


def test_chunked_upload_reserves_quota():
    """Chunked upload reserves quota upfront and releases on abort."""
    store = FileStore(default_quota_bytes=500)
    uid = store.init_chunked_upload("big.bin", 400, 200, "user1")
    used, _ = store.get_usage("user1")
    assert used == 400
    # Can't upload another file that exceeds remaining quota
    with pytest.raises(ValueError):
        store.upload_file("extra.txt", b"x" * 200, "user1")
    store.abort_chunked_upload(uid)
    used_after, _ = store.get_usage("user1")
    assert used_after == 0


def test_conflict_detection_uses_version_vectors():
    """Conflict detection uses version vectors, not just version counter."""
    store = FileStore()
    f = store.upload_file("doc.txt", b"v1", "u1", current_time=100.0)
    # Same device edits twice — no conflict for that device
    store.update_file(f.file_id, b"v2", "u1", device_id="phone", current_time=200.0)
    store.update_file(f.file_id, b"v3", "u1", device_id="phone", current_time=300.0)
    # Phone knows about its own edits, no conflict
    assert store.detect_conflict(f.file_id, "phone", base_version=1) is False
    # Laptop hasn't edited, but phone has — conflict for laptop
    assert store.detect_conflict(f.file_id, "laptop", base_version=1) is True


def test_api_spec_example():
    """Run the API specification example from the task."""
    store = FileStore(default_quota_bytes=1_000_000)
    docs = store.create_folder("documents", "alice", current_time=1000.0)
    work = store.create_folder("work", "alice", parent_folder_id=docs.file_id, current_time=1000.0)
    report = store.upload_file("report.pdf", b"PDF content here...", "alice",
                               parent_folder_id=work.file_id, current_time=1001.0)
    assert report.name == "report.pdf"
    assert store.get_path(report.file_id) == "/documents/work/report.pdf"

    content, meta = store.download_file(report.file_id, "alice")
    assert content == b"PDF content here..."

    v2 = store.update_file(report.file_id, b"Updated PDF content", "alice", current_time=1002.0)
    assert v2.version_number == 2

    versions = store.get_versions(report.file_id)
    assert len(versions) == 2

    store.restore_version(report.file_id, version_number=1, user_id="alice", current_time=1003.0)
    content, _ = store.download_file(report.file_id, "alice")
    assert content == b"PDF content here..."

    store.share(report.file_id, "alice", "bob", Permission.READ)
    content, _ = store.download_file(report.file_id, "bob")
    with pytest.raises(PermissionError):
        store.update_file(report.file_id, b"Hacked!", "bob")

    upload_id = store.init_chunked_upload("big_file.zip", total_size=3000, chunk_size=1000,
                                           owner_id="alice", current_time=2000.0)
    store.upload_chunk(upload_id, 0, b"x" * 1000)
    store.upload_chunk(upload_id, 1, b"y" * 1000)
    store.upload_chunk(upload_id, 2, b"z" * 1000)
    big_file = store.complete_chunked_upload(upload_id, current_time=2001.0)
    assert big_file.size_bytes == 3000

    used, total = store.get_usage("alice")
    assert used > 0

    store.update_file(report.file_id, b"Device A edit", "alice", device_id="phone", current_time=3000.0)
    has_conflict = store.detect_conflict(report.file_id, device_id="laptop", base_version=1)
    assert has_conflict is True

    results = store.search("alice", query="report")
    assert len(results) >= 1

    store.delete_file(report.file_id, "alice", current_time=4000.0)
    trash = store.list_trash("alice")
    assert any(f.file_id == report.file_id for f in trash)

    store.restore_from_trash(report.file_id, "alice")
