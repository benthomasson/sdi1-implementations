"""Tests for YouTube-like video sharing platform simulation."""

import pytest
from design_youtube import (
    Video, VideoStatus, StageStatus, TranscodedVariant, StreamingManifest,
    ProcessingDAG, ProcessingStage, VideoUploadPipeline, VideoStore,
    MorrisCounter, HyperLogLogCounter, ViewCounter, RecommendationEngine,
)


# 1. Video upload creates video with UPLOADING status
def test_video_upload_status():
    store = VideoStore()
    video = store.upload("Test Video", "desc", "user_1", 120.0, tags=["test"])
    assert video.status == VideoStatus.UPLOADING


# 2. Processing pipeline transitions video to READY status
def test_pipeline_transitions_to_ready():
    store = VideoStore()
    video = store.upload("Test", "desc", "user_1", 120.0)
    pipeline = VideoUploadPipeline()
    pipeline.process(video)
    assert video.status == VideoStatus.READY


# 3. Processing DAG executes stages in correct topological order
def test_dag_topological_order():
    dag = ProcessingDAG()
    dag.add_stage(ProcessingStage("validate", handler=lambda ctx: True))
    dag.add_stage(ProcessingStage("transcode", handler=lambda ctx: True, dependencies=["validate"]))
    dag.add_stage(ProcessingStage("thumbnail", handler=lambda ctx: True, dependencies=["validate"]))
    dag.add_stage(ProcessingStage("finalize", handler=lambda ctx: True, dependencies=["transcode", "thumbnail"]))

    order = dag.get_execution_order()
    assert order[0] == ["validate"]
    assert set(order[1]) == {"transcode", "thumbnail"}
    assert order[2] == ["finalize"]

    result = dag.execute({})
    assert result["validate"] == StageStatus.COMPLETED
    assert result["transcode"] == StageStatus.COMPLETED
    assert result["finalize"] == StageStatus.COMPLETED


# 4. DAG skips dependent stages when a stage fails
def test_dag_skips_on_failure():
    dag = ProcessingDAG()
    dag.add_stage(ProcessingStage("step1", handler=lambda ctx: True))
    dag.add_stage(ProcessingStage("step2", handler=lambda ctx: (_ for _ in ()).throw(RuntimeError("fail")), dependencies=["step1"]))
    dag.add_stage(ProcessingStage("step3", handler=lambda ctx: True, dependencies=["step2"]))

    result = dag.execute({})
    assert result["step1"] == StageStatus.COMPLETED
    assert result["step2"] == StageStatus.FAILED
    assert result["step3"] == StageStatus.SKIPPED


# 5. Transcoding produces multiple resolution variants
def test_transcoding_produces_variants():
    store = VideoStore()
    video = store.upload("Test", "desc", "user_1", 120.0)
    pipeline = VideoUploadPipeline()
    pipeline.process(video)
    assert video.manifest is not None
    assert len(video.manifest.variants) >= 3
    resolutions = {v.resolution for v in video.manifest.variants}
    assert "1080p" in resolutions
    assert "720p" in resolutions
    assert "480p" in resolutions


# 6. Adaptive bitrate selects highest quality within bandwidth
def test_adaptive_bitrate_selection():
    manifest = StreamingManifest(
        video_id="v1",
        variants=[
            TranscodedVariant("240p", 426, 240, 400, "h264", 50.0),
            TranscodedVariant("480p", 854, 480, 1000, "h264", 120.0),
            TranscodedVariant("720p", 1280, 720, 2500, "h264", 250.0),
            TranscodedVariant("1080p", 1920, 1080, 5000, "h264", 500.0),
        ]
    )
    assert manifest.select_quality(3000).resolution == "720p"
    assert manifest.select_quality(800).resolution == "240p"
    assert manifest.select_quality(5000).resolution == "1080p"


# 7. Adaptive bitrate returns None when bandwidth is too low
def test_adaptive_bitrate_none():
    manifest = StreamingManifest(
        video_id="v1",
        variants=[
            TranscodedVariant("240p", 426, 240, 400, "h264", 50.0),
        ]
    )
    assert manifest.select_quality(100) is None


# 8. Morris counter estimate is within 2x of actual count for large N
def test_morris_counter_approximation():
    mc = MorrisCounter()
    n = 10000
    for _ in range(n):
        mc.increment()
    estimate = mc.estimate()
    assert n / 2 < estimate < n * 2, f"Morris estimate {estimate} not within 2x of {n}"


# 9. HyperLogLog distinct count is within 20% of actual for 10k items
def test_hyperloglog_accuracy():
    hll = HyperLogLogCounter(precision=14)
    n = 10000
    for i in range(n):
        hll.add(f"item_{i}")
    estimate = hll.estimate()
    assert n * 0.8 < estimate < n * 1.2, f"HLL estimate {estimate} not within 20% of {n}"


# 10. View counter tracks exact view count correctly
def test_view_counter_exact():
    counter = ViewCounter()
    for i in range(1000):
        counter.record_view("vid_1", f"viewer_{i % 100}")
    assert counter.get_view_count("vid_1") == 1000
    unique = counter.get_unique_viewers("vid_1")
    assert 80 < unique < 120, f"Unique viewers estimate {unique} not near 100"


# 11. Content-based recommendation ranks similar tags higher
def test_content_based_recommendation():
    store = VideoStore()
    v1 = store.upload("Cat Video", "", "u1", 60, tags=["cats", "funny", "pets"])
    v2 = store.upload("Dog Video", "", "u1", 60, tags=["dogs", "funny", "pets"])
    v3 = store.upload("Python Tutorial", "", "u2", 60, tags=["python", "coding"])

    engine = RecommendationEngine(store, ViewCounter())
    recs = engine.recommend_by_content(v1.video_id, n=2)
    assert len(recs) >= 1
    assert recs[0].video_id == v2.video_id


# 12. Collaborative filtering recommends based on co-occurrence
def test_collaborative_filtering():
    store = VideoStore()
    v1 = store.upload("Vid 1", "", "u1", 60, tags=["a"])
    v2 = store.upload("Vid 2", "", "u1", 60, tags=["b"])
    v3 = store.upload("Vid 3", "", "u1", 60, tags=["c"])

    counter = ViewCounter()
    engine = RecommendationEngine(store, counter)
    engine.record_watch("user_1", v1.video_id)
    engine.record_watch("user_1", v2.video_id)
    engine.record_watch("user_2", v1.video_id)
    engine.record_watch("user_2", v3.video_id)

    recs = engine.recommend_collaborative("user_1", n=5)
    rec_ids = [r.video_id for r in recs]
    assert v3.video_id in rec_ids


# 13. Video search by title returns matching videos
def test_search_by_title():
    store = VideoStore()
    v1 = store.upload("Funny Cat Video", "", "u1", 60, tags=["cats"])
    v2 = store.upload("Dog Training", "", "u1", 60, tags=["dogs"])
    results = store.search("cat")
    assert any(r.video_id == v1.video_id for r in results)
    assert not any(r.video_id == v2.video_id for r in results)


# 14. Video search by tag returns matching videos
def test_search_by_tag():
    store = VideoStore()
    v1 = store.upload("Video One", "", "u1", 60, tags=["cats", "funny"])
    v2 = store.upload("Video Two", "", "u1", 60, tags=["dogs"])
    results = store.search("cats")
    assert any(r.video_id == v1.video_id for r in results)


# 15. Processing DAG detects cycles and raises error
def test_dag_cycle_detection():
    dag = ProcessingDAG()
    dag.add_stage(ProcessingStage("a", handler=lambda ctx: True, dependencies=["c"]))
    dag.add_stage(ProcessingStage("b", handler=lambda ctx: True, dependencies=["a"]))
    dag.add_stage(ProcessingStage("c", handler=lambda ctx: True, dependencies=["b"]))

    with pytest.raises(ValueError, match="cycle"):
        dag.get_execution_order()


def test_dag_re_execution():
    """DAG can be executed multiple times with fresh stage status."""
    dag = ProcessingDAG()
    dag.add_stage(ProcessingStage("a", handler=lambda ctx: True))
    dag.add_stage(ProcessingStage("b", handler=lambda ctx: True, dependencies=["a"]))

    result1 = dag.execute({})
    assert result1["a"] == StageStatus.COMPLETED
    result2 = dag.execute({})
    assert result2["a"] == StageStatus.COMPLETED


def test_engagement_metrics():
    """Watch duration percentage is tracked per video."""
    counter = ViewCounter()
    counter.record_view("vid_1", "viewer_1", watch_percentage=80.0)
    counter.record_view("vid_1", "viewer_2", watch_percentage=60.0)
    counter.record_view("vid_1", "viewer_3", watch_percentage=100.0)
    avg = counter.get_average_watch_percentage("vid_1")
    assert abs(avg - 80.0) < 0.01


def test_tag_substring_search():
    """Tag search uses substring matching, not exact match."""
    store = VideoStore()
    v1 = store.upload("Video", "", "u1", 60, tags=["cats", "funny"])
    results = store.search("cat")
    assert any(r.video_id == v1.video_id for r in results)
