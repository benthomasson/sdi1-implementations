"""YouTube-like video sharing platform simulation."""

import hashlib
import math
import random
import uuid
from collections import defaultdict
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
    resolution: str
    width: int
    height: int
    bitrate_kbps: int
    codec: str
    simulated_size_mb: float


@dataclass
class StreamingManifest:
    video_id: str
    variants: list
    segment_duration_seconds: float = 4.0

    def select_quality(self, bandwidth_kbps: int) -> Optional[TranscodedVariant]:
        """Select highest quality variant that fits within bandwidth."""
        sorted_variants = sorted(self.variants, key=lambda v: v.bitrate_kbps, reverse=True)
        for v in sorted_variants:
            if v.bitrate_kbps <= bandwidth_kbps:
                return v
        return None


@dataclass
class Video:
    video_id: str
    title: str
    description: str
    uploader_id: str
    upload_timestamp: float
    duration_seconds: float
    original_format: str
    status: VideoStatus = VideoStatus.UPLOADING
    tags: list = field(default_factory=list)
    view_count: int = 0
    like_count: int = 0
    dislike_count: int = 0
    manifest: Optional[StreamingManifest] = None
    thumbnails: list = field(default_factory=list)


@dataclass
class ProcessingStage:
    name: str
    handler: Callable
    dependencies: list = field(default_factory=list)
    status: StageStatus = StageStatus.PENDING
    failure_rate: float = 0.0


class ProcessingDAG:
    """DAG-based processing pipeline with topological execution."""

    def __init__(self):
        self.stages: dict[str, ProcessingStage] = {}

    def add_stage(self, stage: ProcessingStage):
        self.stages[stage.name] = stage

    def _detect_cycle(self):
        """Detect cycles using Kahn's algorithm."""
        in_degree = {name: 0 for name in self.stages}
        for name, stage in self.stages.items():
            for dep in stage.dependencies:
                in_degree[name] += 1
        queue = [n for n, d in in_degree.items() if d == 0]
        visited = 0
        while queue:
            node = queue.pop(0)
            visited += 1
            for name, stage in self.stages.items():
                if node in stage.dependencies:
                    in_degree[name] -= 1
                    if in_degree[name] == 0:
                        queue.append(name)
        if visited != len(self.stages):
            raise ValueError("DAG contains a cycle")

    def get_execution_order(self) -> list[list[str]]:
        """Return stages grouped by execution level."""
        self._detect_cycle()
        in_degree = {name: 0 for name in self.stages}
        for name, stage in self.stages.items():
            for dep in stage.dependencies:
                in_degree[name] += 1
        levels = []
        queue = sorted([n for n, d in in_degree.items() if d == 0])
        while queue:
            levels.append(queue)
            next_queue = []
            for node in queue:
                for name, stage in self.stages.items():
                    if node in stage.dependencies:
                        in_degree[name] -= 1
                        if in_degree[name] == 0:
                            next_queue.append(name)
            queue = sorted(next_queue)
        return levels

    def execute(self, context: dict) -> dict[str, StageStatus]:
        """Execute stages in topological order."""
        for stage in self.stages.values():
            stage.status = StageStatus.PENDING
        levels = self.get_execution_order()
        failed_stages = set()

        for level in levels:
            for stage_name in level:
                stage = self.stages[stage_name]
                # Skip if any dependency failed
                if any(d in failed_stages for d in stage.dependencies):
                    stage.status = StageStatus.SKIPPED
                    failed_stages.add(stage_name)
                    continue

                stage.status = StageStatus.RUNNING
                # Check simulated failure
                if stage.failure_rate > 0 and random.random() < stage.failure_rate:
                    stage.status = StageStatus.FAILED
                    failed_stages.add(stage_name)
                    continue

                try:
                    stage.handler(context)
                    stage.status = StageStatus.COMPLETED
                except Exception:
                    stage.status = StageStatus.FAILED
                    failed_stages.add(stage_name)

        return {name: s.status for name, s in self.stages.items()}


# --- Pipeline Handlers ---

RESOLUTION_CONFIGS = [
    ("240p", 426, 240, 400, 50.0),
    ("360p", 640, 360, 700, 80.0),
    ("480p", 854, 480, 1000, 120.0),
    ("720p", 1280, 720, 2500, 250.0),
    ("1080p", 1920, 1080, 5000, 500.0),
]

VALID_FORMATS = {"mp4", "avi", "mkv", "mov", "webm"}
MAX_DURATION = 43200  # 12 hours


def handle_validate(ctx):
    video = ctx["video"]
    if video.original_format not in VALID_FORMATS:
        raise ValueError(f"Invalid format: {video.original_format}")
    if video.duration_seconds > MAX_DURATION:
        raise ValueError(f"Duration exceeds limit: {video.duration_seconds}")


def handle_transcode(ctx):
    video = ctx["video"]
    variants = []
    for res, w, h, bitrate, size in RESOLUTION_CONFIGS:
        variants.append(TranscodedVariant(res, w, h, bitrate, "h264", size))
    ctx["variants"] = variants


def handle_thumbnail(ctx):
    video = ctx["video"]
    interval = max(1, int(video.duration_seconds / 5))
    ctx["thumbnails"] = [f"thumb_{i}.jpg" for i in range(0, int(video.duration_seconds), interval)]


def handle_metadata(ctx):
    video = ctx["video"]
    ctx["metadata"] = {
        "codec": "h264",
        "aspect_ratio": "16:9",
        "duration": video.duration_seconds,
    }


def handle_finalize(ctx):
    video = ctx["video"]
    variants = ctx.get("variants", [])
    thumbnails = ctx.get("thumbnails", [])
    video.manifest = StreamingManifest(video_id=video.video_id, variants=variants)
    video.thumbnails = thumbnails
    video.status = VideoStatus.READY


class VideoUploadPipeline:
    """Orchestrates video processing through a DAG pipeline."""

    def __init__(self, failure_rates: dict = None):
        self.failure_rates = failure_rates or {}

    def process(self, video: Video) -> dict[str, StageStatus]:
        video.status = VideoStatus.PROCESSING
        dag = ProcessingDAG()
        fr = self.failure_rates

        dag.add_stage(ProcessingStage("validate", handle_validate, failure_rate=fr.get("validate", 0.0)))
        dag.add_stage(ProcessingStage("transcode", handle_transcode, dependencies=["validate"], failure_rate=fr.get("transcode", 0.0)))
        dag.add_stage(ProcessingStage("thumbnail", handle_thumbnail, dependencies=["validate"], failure_rate=fr.get("thumbnail", 0.0)))
        dag.add_stage(ProcessingStage("metadata", handle_metadata, dependencies=["validate"], failure_rate=fr.get("metadata", 0.0)))
        dag.add_stage(ProcessingStage("finalize", handle_finalize, dependencies=["transcode", "thumbnail", "metadata"], failure_rate=fr.get("finalize", 0.0)))

        ctx = {"video": video}
        result = dag.execute(ctx)

        if result.get("finalize") != StageStatus.COMPLETED:
            video.status = VideoStatus.FAILED

        return result


# --- Approximate Counters ---

class MorrisCounter:
    """Probabilistic counter using Morris+ (averaged independent counters)."""

    def __init__(self, num_counters: int = 32):
        self.counters = [0.0] * num_counters

    def increment(self):
        for i in range(len(self.counters)):
            if random.random() < 1.0 / (2 ** self.counters[i]):
                self.counters[i] += 1

    def estimate(self) -> int:
        estimates = [2 ** x - 1 for x in self.counters]
        return int(sum(estimates) / len(estimates))


class HyperLogLogCounter:
    """Approximate distinct count using HyperLogLog."""

    def __init__(self, precision: int = 14):
        self.p = precision
        self.m = 1 << precision
        self.registers = [0] * self.m

    def _hash(self, item: str) -> int:
        return int(hashlib.sha256(item.encode()).hexdigest(), 16)

    def add(self, item: str):
        h = self._hash(item)
        idx = h & (self.m - 1)
        remaining = h >> self.p
        self.registers[idx] = max(self.registers[idx], self._leading_zeros(remaining) + 1)

    def _leading_zeros(self, value: int) -> int:
        if value == 0:
            return 64 - self.p
        count = 0
        for i in range(63, -1, -1):
            if value & (1 << i):
                break
            count += 1
        return count

    def estimate(self) -> int:
        alpha = 0.7213 / (1 + 1.079 / self.m)
        raw = alpha * self.m * self.m / sum(2.0 ** (-r) for r in self.registers)
        # Small range correction
        if raw <= 2.5 * self.m:
            zeros = self.registers.count(0)
            if zeros > 0:
                raw = self.m * math.log(self.m / zeros)
        return int(raw)


class ViewCounter:
    """Combines exact and approximate counting with engagement metrics."""

    def __init__(self):
        self.exact_counts: dict[str, int] = defaultdict(int)
        self.morris_counters: dict[str, MorrisCounter] = {}
        self.hll_counters: dict[str, HyperLogLogCounter] = {}
        self.watch_percentages: dict[str, list[float]] = defaultdict(list)

    def record_view(self, video_id: str, viewer_id: str, watch_percentage: float = 100.0):
        self.exact_counts[video_id] += 1
        if video_id not in self.morris_counters:
            self.morris_counters[video_id] = MorrisCounter()
            self.hll_counters[video_id] = HyperLogLogCounter()
        self.morris_counters[video_id].increment()
        self.hll_counters[video_id].add(viewer_id)
        self.watch_percentages[video_id].append(min(100.0, max(0.0, watch_percentage)))

    def get_view_count(self, video_id: str) -> int:
        return self.exact_counts.get(video_id, 0)

    def get_approximate_count(self, video_id: str) -> int:
        if video_id in self.morris_counters:
            return self.morris_counters[video_id].estimate()
        return 0

    def get_unique_viewers(self, video_id: str) -> int:
        if video_id in self.hll_counters:
            return self.hll_counters[video_id].estimate()
        return 0

    def get_average_watch_percentage(self, video_id: str) -> float:
        pcts = self.watch_percentages.get(video_id, [])
        if not pcts:
            return 0.0
        return sum(pcts) / len(pcts)


# --- Video Store ---

class VideoStore:
    """CRUD operations on videos."""

    def __init__(self):
        self.videos: dict[str, Video] = {}

    def upload(self, title: str, description: str, uploader_id: str,
               duration_seconds: float, format: str = "mp4",
               tags: list = None, current_time: float = None) -> Video:
        video_id = str(uuid.uuid4())
        video = Video(
            video_id=video_id,
            title=title,
            description=description,
            uploader_id=uploader_id,
            upload_timestamp=current_time if current_time is not None else 0.0,
            duration_seconds=duration_seconds,
            original_format=format,
            tags=tags or [],
        )
        self.videos[video_id] = video
        return video

    def get(self, video_id: str) -> Optional[Video]:
        return self.videos.get(video_id)

    def search(self, query: str, limit: int = 20) -> list[Video]:
        query_lower = query.lower()
        results = []
        for v in self.videos.values():
            if v.status == VideoStatus.READY or v.status == VideoStatus.UPLOADING:
                if query_lower in v.title.lower() or any(query_lower in t.lower() for t in v.tags):
                    results.append(v)
        return results[:limit]

    def get_by_uploader(self, uploader_id: str) -> list[Video]:
        return [v for v in self.videos.values() if v.uploader_id == uploader_id]

    def delete(self, video_id: str) -> bool:
        if video_id in self.videos:
            del self.videos[video_id]
            return True
        return False


# --- Recommendations ---

class RecommendationEngine:
    """Multi-strategy video recommendation engine."""

    def __init__(self, video_store: VideoStore, view_counter: ViewCounter):
        self.store = video_store
        self.view_counter = view_counter
        self.user_watches: dict[str, list[str]] = defaultdict(list)

    def record_watch(self, user_id: str, video_id: str):
        if video_id not in self.user_watches[user_id]:
            self.user_watches[user_id].append(video_id)

    def _jaccard(self, tags_a: list, tags_b: list) -> float:
        a, b = set(tags_a), set(tags_b)
        if not a and not b:
            return 0.0
        intersection = len(a & b)
        union = len(a | b)
        return intersection / union if union else 0.0

    def recommend_by_content(self, video_id: str, n: int = 10) -> list[Video]:
        """Recommend videos with similar tags using Jaccard similarity."""
        target = self.store.get(video_id)
        if not target:
            return []
        candidates = []
        for v in self.store.videos.values():
            if v.video_id == video_id:
                continue
            score = self._jaccard(target.tags, v.tags)
            if score > 0:
                candidates.append((score, v))
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [v for _, v in candidates[:n]]

    def recommend_popular(self, n: int = 10) -> list[Video]:
        """Recommend most-viewed videos."""
        videos = list(self.store.videos.values())
        videos.sort(key=lambda v: self.view_counter.get_view_count(v.video_id), reverse=True)
        return videos[:n]

    def recommend_collaborative(self, user_id: str, n: int = 10) -> list[Video]:
        """Recommend based on co-occurrence: users who watched X also watched Y."""
        watched = set(self.user_watches.get(user_id, []))
        if not watched:
            return []

        # Find co-watchers and their videos
        co_occurrence: dict[str, int] = defaultdict(int)
        for other_user, other_videos in self.user_watches.items():
            if other_user == user_id:
                continue
            other_set = set(other_videos)
            if watched & other_set:  # shares at least one video
                for vid in other_set - watched:
                    co_occurrence[vid] += 1

        ranked = sorted(co_occurrence.items(), key=lambda x: x[1], reverse=True)
        results = []
        for vid, _ in ranked[:n]:
            v = self.store.get(vid)
            if v:
                results.append(v)
        return results

    def get_feed(self, user_id: str, n: int = 20, weights: dict = None) -> list[Video]:
        """Combine recommendations from multiple strategies with weights."""
        weights = weights or {"popular": 0.3, "collaborative": 0.5, "content": 0.2}

        scores: dict[str, float] = defaultdict(float)
        watched = set(self.user_watches.get(user_id, []))

        # Popular
        popular = self.recommend_popular(n=n * 2)
        for rank, v in enumerate(popular):
            if v.video_id not in watched:
                scores[v.video_id] += weights.get("popular", 0.3) * (1.0 / (rank + 1))

        # Collaborative
        collab = self.recommend_collaborative(user_id, n=n * 2)
        for rank, v in enumerate(collab):
            scores[v.video_id] += weights.get("collaborative", 0.5) * (1.0 / (rank + 1))

        # Content-based (from user's watched videos)
        for vid in list(watched)[:5]:
            content = self.recommend_by_content(vid, n=n)
            for rank, v in enumerate(content):
                if v.video_id not in watched:
                    scores[v.video_id] += weights.get("content", 0.2) * (1.0 / (rank + 1))

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        results = []
        for vid, _ in ranked[:n]:
            v = self.store.get(vid)
            if v:
                results.append(v)
        return results
