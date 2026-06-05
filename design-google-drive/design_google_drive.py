"""Google Drive-like cloud file storage simulation."""

import hashlib
import math
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Permission(Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


PERMISSION_LEVEL = {Permission.READ: 0, Permission.WRITE: 1, Permission.ADMIN: 2}


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
    chunks: dict[int, bytes] = field(default_factory=dict)
    chunk_checksums: dict[int, str] = field(default_factory=dict)
    started_at: float = 0.0
    completed: bool = False


class FileStore:
    """In-memory file storage system with versioning, sharing, and conflict detection."""

    def __init__(self, max_versions: int = 100, default_quota_bytes: int = 1_073_741_824):
        self.max_versions = max_versions
        self.default_quota_bytes = default_quota_bytes
        self.files: dict[str, FileMetadata] = {}
        self.content: dict[str, bytes] = {}
        self.versions: dict[str, list[FileVersion]] = {}
        self.chunked_uploads: dict[str, ChunkedUpload] = {}
        self.user_quotas: dict[str, int] = {}  # used bytes
        self.user_roots: dict[str, str] = {}  # user_id -> root folder_id

    def _get_or_create_root(self, user_id: str, current_time: float = 0.0) -> str:
        """Get or create the root folder for a user."""
        if user_id not in self.user_roots:
            fid = str(uuid.uuid4())
            meta = FileMetadata(
                file_id=fid, name="", size_bytes=0, mime_type="folder",
                owner_id=user_id, created_at=current_time, modified_at=current_time,
                checksum="", is_folder=True,
            )
            self.files[fid] = meta
            self.user_roots[user_id] = fid
        return self.user_roots[user_id]

    def _check_permission(self, file_id: str, user_id: str, required: Permission) -> None:
        """Check if user has required permission on file. Raises PermissionError."""
        meta = self.files.get(file_id)
        if not meta:
            raise FileNotFoundError(f"File {file_id} not found")
        if meta.owner_id == user_id:
            return
        # Check direct permission
        perm = meta.shared_with.get(user_id)
        if perm and PERMISSION_LEVEL[perm] >= PERMISSION_LEVEL[required]:
            return
        # Check inherited permission from parent folders
        parent_id = meta.parent_folder_id
        while parent_id:
            parent = self.files.get(parent_id)
            if not parent:
                break
            if parent.owner_id == user_id:
                return
            pp = parent.shared_with.get(user_id)
            if pp and PERMISSION_LEVEL[pp] >= PERMISSION_LEVEL[required]:
                return
            parent_id = parent.parent_folder_id
        raise PermissionError(f"User {user_id} lacks {required.value} permission on {file_id}")

    def _update_quota(self, user_id: str, delta: int) -> None:
        """Update user's used storage. Raises ValueError if quota exceeded."""
        current = self.user_quotas.get(user_id, 0)
        new_usage = current + delta
        if delta > 0 and new_usage > self.default_quota_bytes:
            raise ValueError(f"Quota exceeded for user {user_id}")
        self.user_quotas[user_id] = max(0, new_usage)

    def _get_children(self, folder_id: str) -> list[str]:
        """Get all file IDs that are direct children of a folder."""
        return [f.file_id for f in self.files.values() if f.parent_folder_id == folder_id]

    def _get_descendants(self, folder_id: str) -> list[str]:
        """Get all descendant file IDs (recursive) of a folder."""
        result = []
        queue = [folder_id]
        while queue:
            parent = queue.pop()
            for child_id in self._get_children(parent):
                result.append(child_id)
                if self.files[child_id].is_folder:
                    queue.append(child_id)
        return result

    # --- Folder operations ---

    def create_folder(self, name: str, owner_id: str, parent_folder_id: Optional[str] = None,
                      current_time: float = None) -> FileMetadata:
        """Create a folder."""
        t = current_time if current_time is not None else 0.0
        if parent_folder_id is None:
            parent_folder_id = self._get_or_create_root(owner_id, t)
        fid = str(uuid.uuid4())
        meta = FileMetadata(
            file_id=fid, name=name, size_bytes=0, mime_type="folder",
            owner_id=owner_id, created_at=t, modified_at=t, checksum="",
            is_folder=True, parent_folder_id=parent_folder_id,
        )
        self.files[fid] = meta
        return meta

    def list_folder(self, folder_id: str, user_id: str) -> list[FileMetadata]:
        """List non-deleted children of a folder."""
        self._check_permission(folder_id, user_id, Permission.READ)
        return [f for f in self.files.values()
                if f.parent_folder_id == folder_id and not f.is_deleted]

    def get_path(self, file_id: str) -> str:
        """Get full path string for a file or folder."""
        parts = []
        current = self.files.get(file_id)
        while current:
            if current.name:
                parts.append(current.name)
            parent_id = current.parent_folder_id
            current = self.files.get(parent_id) if parent_id else None
        return "/" + "/".join(reversed(parts))

    # --- File operations ---

    def upload_file(self, name: str, content: bytes, owner_id: str,
                    parent_folder_id: Optional[str] = None,
                    current_time: float = None) -> FileMetadata:
        """Upload a new file."""
        t = current_time if current_time is not None else 0.0
        size = len(content)
        self._update_quota(owner_id, size)
        if parent_folder_id is None:
            parent_folder_id = self._get_or_create_root(owner_id, t)
        checksum = hashlib.sha256(content).hexdigest()
        fid = str(uuid.uuid4())
        meta = FileMetadata(
            file_id=fid, name=name, size_bytes=size,
            mime_type=self._guess_mime(name), owner_id=owner_id,
            created_at=t, modified_at=t, checksum=checksum,
            parent_folder_id=parent_folder_id,
        )
        self.files[fid] = meta
        self.content[fid] = content
        v = FileVersion(version_number=1, content_hash=checksum, size_bytes=size,
                        modified_at=t, modified_by=owner_id, content=content)
        self.versions[fid] = [v]
        return meta

    def download_file(self, file_id: str, user_id: str) -> tuple[bytes, FileMetadata]:
        """Download a file's content."""
        meta = self.files.get(file_id)
        if not meta or meta.is_deleted:
            raise FileNotFoundError(f"File {file_id} not found")
        self._check_permission(file_id, user_id, Permission.READ)
        return self.content[file_id], meta

    def update_file(self, file_id: str, new_content: bytes, user_id: str,
                    device_id: str = "default", current_time: float = None) -> FileVersion:
        """Update file content, creating a new version."""
        meta = self.files.get(file_id)
        if not meta or meta.is_deleted:
            raise FileNotFoundError(f"File {file_id} not found")
        self._check_permission(file_id, user_id, Permission.WRITE)
        t = current_time if current_time is not None else 0.0
        old_size = meta.size_bytes
        new_size = len(new_content)
        self._update_quota(meta.owner_id, new_size - old_size)
        checksum = hashlib.sha256(new_content).hexdigest()
        meta.size_bytes = new_size
        meta.modified_at = t
        meta.checksum = checksum
        meta.current_version += 1
        # Update version vector
        meta.version_vector[device_id] = meta.current_version
        self.content[file_id] = new_content
        v = FileVersion(version_number=meta.current_version, content_hash=checksum,
                        size_bytes=new_size, modified_at=t, modified_by=user_id,
                        content=new_content)
        self.versions.setdefault(file_id, []).append(v)
        # Prune old versions
        vlist = self.versions[file_id]
        if len(vlist) > self.max_versions:
            self.versions[file_id] = vlist[-self.max_versions:]
        return v

    def delete_file(self, file_id: str, user_id: str, current_time: float = None) -> bool:
        """Soft-delete a file (move to trash). Cascades to children for folders."""
        meta = self.files.get(file_id)
        if not meta:
            return False
        self._check_permission(file_id, user_id, Permission.WRITE)
        t = current_time if current_time is not None else 0.0
        meta.is_deleted = True
        meta.deleted_at = t
        if meta.is_folder:
            for child_id in self._get_descendants(file_id):
                child = self.files[child_id]
                child.is_deleted = True
                child.deleted_at = t
        return True

    def move_file(self, file_id: str, new_parent_id: str, user_id: str) -> FileMetadata:
        """Move a file to a different folder. Checks WRITE on both source and destination."""
        meta = self.files.get(file_id)
        if not meta or meta.is_deleted:
            raise FileNotFoundError(f"File {file_id} not found")
        self._check_permission(file_id, user_id, Permission.WRITE)
        self._check_permission(new_parent_id, user_id, Permission.WRITE)
        meta.parent_folder_id = new_parent_id
        return meta

    def rename_file(self, file_id: str, new_name: str, user_id: str) -> FileMetadata:
        """Rename a file."""
        meta = self.files.get(file_id)
        if not meta or meta.is_deleted:
            raise FileNotFoundError(f"File {file_id} not found")
        self._check_permission(file_id, user_id, Permission.WRITE)
        meta.name = new_name
        return meta

    # --- Versioning ---

    def get_versions(self, file_id: str) -> list[FileVersion]:
        """Get version history for a file."""
        return list(self.versions.get(file_id, []))

    def restore_version(self, file_id: str, version_number: int, user_id: str,
                        current_time: float = None) -> FileMetadata:
        """Restore a file to a previous version."""
        meta = self.files.get(file_id)
        if not meta:
            raise FileNotFoundError(f"File {file_id} not found")
        self._check_permission(file_id, user_id, Permission.WRITE)
        vlist = self.versions.get(file_id, [])
        target = None
        for v in vlist:
            if v.version_number == version_number:
                target = v
                break
        if not target:
            raise ValueError(f"Version {version_number} not found")
        self.update_file(file_id, target.content, user_id, current_time=current_time)
        return self.files[file_id]

    # --- Chunked upload ---

    def init_chunked_upload(self, name: str, total_size: int, chunk_size: int,
                            owner_id: str, current_time: float = None) -> str:
        """Initialize a chunked upload session. Reserves quota upfront."""
        self._update_quota(owner_id, total_size)
        uid = str(uuid.uuid4())
        total_chunks = math.ceil(total_size / chunk_size)
        self.chunked_uploads[uid] = ChunkedUpload(
            upload_id=uid, file_name=name, total_size=total_size,
            chunk_size=chunk_size, total_chunks=total_chunks,
            owner_id=owner_id, started_at=current_time if current_time is not None else 0.0,
        )
        return uid

    def upload_chunk(self, upload_id: str, chunk_index: int, chunk_data: bytes) -> bool:
        """Upload a single chunk."""
        upload = self.chunked_uploads.get(upload_id)
        if not upload or upload.completed:
            return False
        upload.chunks[chunk_index] = chunk_data
        upload.chunk_checksums[chunk_index] = hashlib.sha256(chunk_data).hexdigest()
        return True

    def complete_chunked_upload(self, upload_id: str, parent_folder_id: Optional[str] = None,
                                current_time: float = None) -> FileMetadata:
        """Complete a chunked upload by assembling all chunks."""
        upload = self.chunked_uploads.get(upload_id)
        if not upload:
            raise ValueError(f"Upload {upload_id} not found")
        for i in range(upload.total_chunks):
            if i not in upload.chunks:
                raise ValueError(f"Missing chunk {i}")
        data = b"".join(upload.chunks[i] for i in range(upload.total_chunks))
        upload.completed = True
        # Release reservation; upload_file will re-account the actual size
        self._update_quota(upload.owner_id, -upload.total_size)
        meta = self.upload_file(upload.file_name, data, upload.owner_id,
                                parent_folder_id=parent_folder_id,
                                current_time=current_time)
        del self.chunked_uploads[upload_id]
        return meta

    def abort_chunked_upload(self, upload_id: str) -> bool:
        """Abort a chunked upload and release reserved quota."""
        upload = self.chunked_uploads.get(upload_id)
        if upload:
            self._update_quota(upload.owner_id, -upload.total_size)
            del self.chunked_uploads[upload_id]
            return True
        return False

    # --- Sharing ---

    def share(self, file_id: str, owner_id: str, target_user_id: str,
              permission: Permission) -> None:
        """Share a file with another user."""
        meta = self.files.get(file_id)
        if not meta:
            raise FileNotFoundError(f"File {file_id} not found")
        # Owner or admin can share
        if meta.owner_id != owner_id:
            perm = meta.shared_with.get(owner_id)
            if not perm or perm != Permission.ADMIN:
                raise PermissionError("Only owner or admin can share")
        meta.shared_with[target_user_id] = permission

    def revoke(self, file_id: str, owner_id: str, target_user_id: str) -> None:
        """Revoke a user's access to a file."""
        meta = self.files.get(file_id)
        if not meta:
            raise FileNotFoundError(f"File {file_id} not found")
        if meta.owner_id != owner_id:
            raise PermissionError("Only owner can revoke")
        meta.shared_with.pop(target_user_id, None)

    def get_shared_with(self, file_id: str) -> dict[str, Permission]:
        """Get sharing info for a file."""
        meta = self.files.get(file_id)
        if not meta:
            raise FileNotFoundError(f"File {file_id} not found")
        return dict(meta.shared_with)

    # --- Conflict detection ---

    def detect_conflict(self, file_id: str, device_id: str, base_version: int) -> bool:
        """Detect if a conflict exists using version vectors.

        A conflict exists when the device's base_version is behind the file's
        current version AND another device has made edits the requesting device
        hasn't seen (concurrent edits, not just staleness).
        """
        meta = self.files.get(file_id)
        if not meta:
            raise FileNotFoundError(f"File {file_id} not found")
        if meta.current_version <= base_version:
            return False
        device_known = meta.version_vector.get(device_id, 0)
        for other_device, other_ver in meta.version_vector.items():
            if other_device != device_id and other_ver > device_known:
                return True
        return False

    def resolve_conflict(self, file_id: str, strategy: str = "latest_wins",
                         user_id: str = None, current_time: float = None,
                         conflicting_content: bytes = None) -> FileMetadata:
        """Resolve a sync conflict.

        For "keep_both", conflicting_content is the other device's version of the file.
        The original file keeps the server's current content, and a conflict copy is
        created with the other device's content.
        """
        meta = self.files.get(file_id)
        if not meta:
            raise FileNotFoundError(f"File {file_id} not found")
        if strategy == "latest_wins":
            return meta
        elif strategy == "keep_both":
            conflict_data = conflicting_content if conflicting_content is not None else self.content.get(file_id, b"")
            name_base, *ext_parts = meta.name.rsplit(".", 1)
            if ext_parts:
                new_name = f"{name_base} (conflict).{ext_parts[0]}"
            else:
                new_name = f"{meta.name} (conflict)"
            copy = self.upload_file(new_name, conflict_data, user_id or meta.owner_id,
                                    parent_folder_id=meta.parent_folder_id,
                                    current_time=current_time)
            return copy
        raise ValueError(f"Unknown strategy: {strategy}")

    # --- Quota ---

    def get_usage(self, user_id: str) -> tuple[int, int]:
        """Get (used_bytes, total_bytes) for a user."""
        return self.user_quotas.get(user_id, 0), self.default_quota_bytes

    # --- Search ---

    def search(self, user_id: str, query: str = None,
               mime_type: str = None) -> list[FileMetadata]:
        """Search files by name substring and/or mime type."""
        results = []
        for f in self.files.values():
            if f.is_deleted or f.is_folder:
                continue
            # Check access
            try:
                self._check_permission(f.file_id, user_id, Permission.READ)
            except PermissionError:
                continue
            if query and query.lower() not in f.name.lower():
                continue
            if mime_type and f.mime_type != mime_type:
                continue
            results.append(f)
        return results

    # --- Trash ---

    def list_trash(self, user_id: str) -> list[FileMetadata]:
        """List deleted files owned by or accessible to user."""
        return [f for f in self.files.values()
                if f.is_deleted and f.owner_id == user_id]

    def restore_from_trash(self, file_id: str, user_id: str) -> FileMetadata:
        """Restore a file from trash."""
        meta = self.files.get(file_id)
        if not meta or not meta.is_deleted:
            raise FileNotFoundError(f"File {file_id} not found in trash")
        if meta.owner_id != user_id:
            raise PermissionError("Only owner can restore from trash")
        meta.is_deleted = False
        meta.deleted_at = None
        return meta

    def empty_trash(self, user_id: str, current_time: float = None,
                    auto_days: float = 30.0) -> None:
        """Permanently delete trash items older than auto_days."""
        t = current_time if current_time is not None else 0.0
        cutoff = t - (auto_days * 86400)
        to_remove = []
        for fid, f in self.files.items():
            if f.is_deleted and f.owner_id == user_id:
                if f.deleted_at is not None and f.deleted_at <= cutoff:
                    to_remove.append(fid)
        for fid in to_remove:
            f = self.files.pop(fid)
            self.content.pop(fid, None)
            self.versions.pop(fid, None)
            self._update_quota(user_id, -f.size_bytes)

    @staticmethod
    def _guess_mime(name: str) -> str:
        """Guess mime type from file extension."""
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        return {
            "txt": "text/plain", "pdf": "application/pdf",
            "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "zip": "application/zip", "json": "application/json",
            "html": "text/html", "csv": "text/csv",
        }.get(ext, "application/octet-stream")
