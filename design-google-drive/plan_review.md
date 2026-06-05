# Plan Review: Design Google Drive

## Plan Strengths

- Comprehensive feature set: file CRUD, folder hierarchy, versioning, chunked upload, sharing with inheritance, conflict detection, quotas, search, and trash — all 10 requirements covered.
- Clean data model separation: `FileMetadata`, `FileVersion`, and `ChunkedUpload` are well-scoped.
- Permission inheritance via parent folder traversal is the right approach for a hierarchical file system.
- Version pruning with configurable max keeps memory bounded.
- SHA-256 checksums for both files and individual chunks.

## Plan Gaps

1. **Conflict detection is too simple.** The plan specifies version vectors (`dict[device_id, version_number]`) but the implementation only checks `current_version > base_version`. This is a plain version counter comparison, not a vector clock. True version vectors detect concurrent edits (neither happened-before the other); a simple counter just detects staleness. The plan's data model has the right field but the design doesn't use it properly.

2. **Quota accounting doesn't include version history.** Each `update_file` call adjusts quota by `new_size - old_size`, but old versions still hold content in memory. The plan doesn't discuss whether quota should account for all stored versions or just the current one. In the implementation, restoring a version calls `update_file` which creates yet another version — so version count grows but quota only tracks the current file size.

3. **Recursive folder operations are missing.** Deleting or moving a folder doesn't affect its children. If you delete a folder, its children become orphaned — still accessible by ID but with a broken path. The plan doesn't address cascading deletes or moves.

4. **`list_folder` scans all files.** It iterates every file in the store to find children of a given folder. The plan doesn't discuss indexing children by parent. Fine for a simulation but worth noting.

5. **No max file size enforcement.** The constraints mention "Maximum file size: 100MB simulated" but neither the plan nor implementation enforces it.

6. **`current_time or 0.0` falsy pattern** appears throughout, same issue as chat-system — explicit `0.0` is treated as no argument.

## Implementation Issues

1. **Soft delete doesn't free quota.** `delete_file` marks `is_deleted=True` but doesn't reduce `user_quotas`. Only `empty_trash` frees quota. This means a user's usable space shrinks permanently until they empty trash, but the plan doesn't make this tradeoff explicit.

2. **`restore_version` creates a new version via `update_file`.** This means restoring version 1 of a file at version 3 creates version 4 with version 1's content. The version list grows every restore. This is arguably correct (preserving the audit trail) but the plan doesn't discuss it.

3. **`resolve_conflict("keep_both")` copies the current file.** It doesn't preserve the conflicting edit from the other device — it just duplicates the latest version. A real "keep both" should save both the current version and the conflicting device's version. The conflict copy is identical to the original.

4. **Chunked upload doesn't check quota.** `init_chunked_upload` knows the `total_size` but doesn't reserve quota. Quota is only checked when `complete_chunked_upload` calls `upload_file`. A user could upload all chunks only to fail at completion.

5. **Permission inheritance doesn't cache.** Every operation walks the parent chain. Deeply nested files in shared folders pay O(depth) per operation.

6. **`search` calls `_check_permission` for every file in the store.** This is O(files * folder_depth) in the worst case. No indexing by owner or shared-with.

7. **`move_file` doesn't check destination permissions.** A user with WRITE on a file can move it into any folder, even one they don't own or have access to.

8. **`delete_file` requires WRITE permission, but the plan says the owner should be able to delete.** An admin who shared with WRITE can delete, but a READ user cannot — which is correct. However, the plan says "Check permission before any file operation" without specifying which permission level delete requires. WRITE is reasonable but ADMIN could also be argued.
