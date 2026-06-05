# Plan (Iteration 1)

Task: DESIGN YOUTUBE
System Design Interview Vol 1 - Chapter 14

OVERVIEW
--------
Implement a video sharing platform simulation as a single-process Python
application. The system models the video upload processing pipeline (transcoding
simulation), adaptive bitrate streaming metadata, view counting with approximate
counting techniques, and a basic recommendation feed. Videos are represented as
metadata objects (no actual video files); the focus is on the system design
patterns: processing pipelines, DAG-based task execution, approximate counting,
and content-based recommendations.

REQUIREMENTS
------------
1.  Implement a Video data model with: video_id, title, description, uploader_id,
    upload_timestamp, duration_seconds, original_format, status (uploading,
    processing, ready, failed), tags, and view_count.
2.  Implement a VideoUploadPipeline as a DAG (directed acyclic graph) of
    processing stages:
    - Stage 1: Validation (check format, duration limits, file size simulation)
    - Stage 2: Transcoding (simulate converting to multiple resolutions:
      240p, 360p, 480p, 720p, 1080p). Each resolution is a TranscodedVariant
      with metadata (resolution, bitrate, simulated_size).
    - Stage 3: Thumbnail generation (simulate extracting frames at intervals)
    - Stage 4: Metadata extraction (simulate reading codec info, aspect ratio)
    - Stages 2, 3, 4 run in parallel after stage 1 (DAG structure).
    - Stage 5: Finalization (mark video as ready) runs after all parallel stages.
    Each stage has a configurable simulated failure rate for testing error handling.
3.  Implement a ProcessingDAG class:
    - Define stages and dependencies as a DAG.
    - Execute stages in topological order, running independent stages "in parallel"
      (simulated: all runnable stages execute in sequence but are semantically parallel).
    - Track stage status: PENDING, RUNNING, COMPLETED, FAILED.
    - On failure, mark dependent stages as SKIPPED.
4.  Implement adaptive bitrate streaming metadata:
    - Each video (once processed) has a StreamingManifest listing available qualities.
    - Each quality entry: resolution, bitrate_kbps, codec, segment_duration.
    - Simulate quality selection: given a client's bandwidth_kbps, select the
      highest quality that doesn't exceed bandwidth.
5.  Implement approximate view counting using:
    - Morris counter (probabilistic counting): uses O(log log n) space to
      approximate large counts.
    - HyperLogLog-style approach for unique viewer counting (approximate
      count of distinct viewer IDs).
    - Exact count maintained separately for comparison.
6.  Implement a VideoStore for CRUD operations on videos.
7.  Implement a RecommendationEngine with basic strategies:
    - Content-based: recommend videos with similar tags (Jaccard similarity).
    - Popular: recommend most-viewed videos.
    - Collaborative: users who watched X also watched Y (co-occurrence matrix).
    - Return top-N recommendations for a given user or video.
8.  Implement a VideoFeed for a user: combine recommendations from multiple
    strategies with configurable weights.
9.  Implement video search by title and tags (simple keyword matching).
10. Implement basic engagement metrics per video: view count, like count,
    dislike count, average watch duration percentage (simulated).

DATA MODELS
-----------
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable

class VideoStatus(Enum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"

class StageStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

@dataclass
class TranscodedVariant:
    resolution: str       # e.g., "1080p"
    width: int
    height: int
    bitrate_kbps: int
    codec: str            # e.g., "h264"
    simulated_size_mb: float

@dataclass
class StreamingManifest:
    video_id: str
    variants: list[TranscodedVariant]
    segment_duration_seconds: float = 4.0

    def select_quality(self, bandwidth_kbps: int) -> Optional[TranscodedVariant]: ...

@dataclass
class Video:
    video_id: str
    title: str
    description: str
    uploader_id: str
    upload_timestamp: float
    duration_seconds: float
    original_format: str     # e.g., "mp4"
    status: VideoStatus = VideoStatus.UPLOADING
    tags: list[str] = field(default_factory=list)
    view_count: int = 0
    like_count: int = 0
    dislike_count: int = 0
    manifest: Optional[StreamingManifest] = None
    thumbnails: list[str] = field(default_factory=list)

@dataclass
class ProcessingStage:
    name: str
    handler: Callable
    dependencies: list[str] = field(default_factory=list)
    status: StageStatus = StageStatus.PENDING
    failure_rate: float = 0.0

class ProcessingDAG:
    def __init__(self): ...
    def add_stage(self, stage: ProcessingStage): ...
    def execute(self, context: dict) -> dict[str, StageStatus]: ...
    def get_execution_order(self) -> list[list[str]]:
        """Return stages grouped by execution level (parallelizable stages together)."""
        ...

class MorrisCounter:
    """Probabilistic counter using O(log log n) space."""
    def __init__(self): ...
    def increment(self): ...
    def estimate(self) -> int: ...

class HyperLogLogCounter:
    """Approximate distinct count using HyperLogLog."""
    def __init__(self, precision: int = 14): ...
    def add(self, item: str): ...
    def estimate(self) -> int: ...

class ViewCounter:
    """Combines exact and approximate counting."""
    def __init__(self): ...
    def record_view(self, video_id: str, viewer_id: str): ...
    def get_view_count(self, video_id: str) -> int: ...
    def get_unique_viewers(self, video_id: str) -> int: ...

class VideoStore:
    def upload(self, title: str, description: str, uploader_id: str,
               duration_seconds: float, format: str = "mp4",
               tags: list[str] = None, current_time: float = None) -> Video: ...
    def get(self, video_id: str) -> Optional[Video]: ...
    def search(self, query: str, limit: int = 20) -> list[Video]: ...
    def get_by_uploader(self, uploader_id: str) -> list[Video]: ...
    def delete(self, video_id: str) -> bool: ...

class RecommendationEngine:
    def __init__(self, video_store: VideoStore, view_counter: ViewCounter): ...
    def record_watch(self, user_id: str, video_id: str): ...
    def recommend_by_content(self, video_id: str, n: int = 10) -> list[Video]: ...
    def recommend_popular(self, n: int = 10) -> list[Video]: ...
    def recommend_collaborative(self, user_id: str, n: int = 10) -> list[Video]: ...
    def get_feed(self, user_id: str, n: int = 20,
                 weights: dict[str, float] = None) -> list[Video]: ...

API SPECIFICATION
-----------------
# Video upload and processing
store = VideoStore()
video = store.upload(
    title="My Cat Video",
    description="Funny cat doing things",
    uploader_id="user_1",
    duration_seconds=120.0,
    format="mp4",
    tags=["cats", "funny", "pets"]
)

# Process through pipeline
pipeline = VideoUploadPipeline()
result = pipeline.process(video)
assert video.status == VideoStatus.READY
assert video.manifest is not None
assert len(video.manifest.variants) >= 3  # multiple resolutions

# Adaptive bitrate selection
variant = video.manifest.select_quality(bandwidth_kbps=2500)
assert variant.resolution in ["720p", "480p"]  # best fit for 2500 kbps

# View counting
counter = ViewCounter()
for i in range(1000):
    counter.record_view(video.video_id, f"viewer_{i % 100}")  # 100 unique viewers
exact = counter.get_view_count(video.video_id)
unique = counter.get_unique_viewers(video.video_id)
assert exact == 1000
assert 80 < unique < 120  # approximate, should be near 100

# Recommendations
engine = RecommendationEngine(store, counter)
engine.record_watch("user_1", "vid_1")
engine.record_watch("user_1", "vid_2")
engine.record_watch("user_2", "vid_1")
engine.record_watch("user_2", "vid_3")
# user_1 watched vid_1, vid_2; user_2 watched vid_1, vid_3
# Collaborative: recommend vid_3 to user_1 (user_2 also watched vid_1)

content_recs = engine.recommend_by_content("vid_1", n=5)
popular_recs = engine.recommend_popular(n=5)
collab_recs = engine.recommend_collaborative("user_1", n=5)

# Search
results = store.search("cat")

EXAMPLE USAGE WITH ASSERTIONS
------------------------------
# Processing DAG
dag = ProcessingDAG()
dag.add_stage(ProcessingStage("validate", handler=lambda ctx: True))
dag.add_stage(ProcessingStage("transcode", handler=lambda ctx: True, dependencies=["validate"]))
dag.add_stage(ProcessingStage("thumbnail", handler=lambda ctx: True, dependencies=["validate"]))
dag.add_stage(ProcessingStage("finalize", handler=lambda ctx: True, dependencies=["transcode", "thumbnail"]))

order = dag.get_execution_order()
# order == [["validate"], ["transcode", "thumbnail"], ["finalize"]]
assert order[0] == ["validate"]
assert set(order[1]) == {"transcode", "thumbnail"}
assert order[2] == ["finalize"]

result = dag.execute({})
assert result["validate"] == StageStatus.COMPLETED
assert result["transcode"] == StageStatus.COMPLETED
assert result["finalize"] == StageStatus.COMPLETED

# Morris counter approximation
mc = MorrisCounter()
for _ in range(10000):
    mc.increment()
estimate = mc.estimate()
assert 5000 < estimate < 20000  # rough approximation

# HyperLogLog
hll = HyperLogLogCounter(precision=14)
for i in range(10000):
    hll.add(f"item_{i}")
estimate = hll.estimate()
assert 8000 < estimate < 12000  # within ~20% error

# Streaming quality selection
manifest = StreamingManifest(
    video_id="v1",
    variants=[
        TranscodedVariant("240p", 426, 240, 400, "h264", 50.0),
        TranscodedVariant("480p", 854, 480, 1000, "h264", 120.0),
        TranscodedVariant("720p", 1280, 720, 2500, "h264", 250.0),
        TranscodedVariant("1080p", 1920, 1080, 5000, "h264", 500.0),
    ]
)
assert manifest.select_quality(3000).resolution == "720p"  # 2500 <= 3000
assert manifest.select_quality(800).resolution == "240p"    # 400 <= 800
assert manifest.select_quality(100) is None                 # nothing fits

# Content-based recommendation (Jaccard similarity on tags)
store = VideoStore()
v1 = store.upload("Cat Video", "", "u1", 60, tags=["cats", "funny", "pets"])
v2 = store.upload("Dog Video", "", "u1", 60, tags=["dogs", "funny", "pets"])
v3 = store.upload("Python Tutorial", "", "u2", 60, tags=["python", "coding"])

engine = RecommendationEngine(store, ViewCounter())
recs = engine.recommend_by_content(v1.video_id, n=2)
# v2 should rank higher (2 shared tags: funny, pets) than v3 (0 shared tags)
assert recs[0].video_id == v2.video_id

CONSTRAINTS
-----------
- All data in-memory (no actual video files)
- Video processing is simulated (no actual transcoding)
- Morris counter uses O(log log n) space (a single float)
- HyperLogLog uses configurable precision (default 14 bits = 16384 registers)
- Processing DAG must detect cycles and reject them
- Support up to 10,000 videos in store
- No external dependencies beyond Python standard library
- Target: 350-500 lines of code

TESTING REQUIREMENTS
--------------------
Write tests in test_design_youtube.py using pytest. Include these test cases:

1.  Video upload creates video with UPLOADING status
2.  Processing pipeline transitions video to READY status
3.  Processing DAG executes stages in correct topological order
4.  DAG skips dependent stages when a stage fails
5.  Transcoding produces multiple resolution variants
6.  Adaptive bitrate selects highest quality within bandwidth
7.  Adaptive bitrate returns None when bandwidth is too low
8.  Morris counter estimate is within 2x of actual count for large N
9.  HyperLogLog distinct count is within 20% of actual for 10k items
10. View counter tracks exact view count correctly
11. Content-based recommendation ranks similar tags higher
12. Collaborative filtering recommends based on co-occurrence
13. Video search by title returns matching videos
14. Video search by tag returns matching videos
15. Processing DAG detects cycles and raises error

IMPORTANT - EFFORT LEVEL: MINIMAL
Keep plan VERY brief (2-3 paragraphs max). Focus only on algorithm choice. Skip architectural discussions and detailed analysis.

Plan written to `PLAN.md`. It covers the key algorithm choices (Morris counter, HyperLogLog, Kahn's topological sort, Jaccard similarity, co-occurrence collaborative filtering) and implementation order. The spec is detailed enough that this is a high-confidence, mechanical implementation.

[Committed changes to planner branch]