# Automated Danmaku Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-command, unattended, self-hosted danmaku service for Forward and SenPlayer, using Misaka as the normal matching engine and a custom Autopilot gateway for automatic anomaly detection, timeline correction, compilation splitting, maintenance, backup, update, and rollback.

**Architecture:** Native Caddy terminates HTTPS and exposes separate player and admin hostnames. A FastAPI Autopilot gateway transparently proxies the player-facing Dandan-compatible routes to a digest-pinned Misaka container, while persistent background jobs analyze failed or suspicious matches and import corrected XML through Misaka's external-control API. MySQL stores Misaka data; SQLite WAL stores the small Autopilot job/rule database; host-side locked scripts perform backup, update, health checks, and rollback without mounting the Docker socket.

**Tech Stack:** Docker Compose v2, `l429609201/misaka_danmu_server`, `mysql:8.1.0-oracle` (the version in the current Misaka quick-start guide), Python 3.12, FastAPI, HTTPX, Pydantic Settings, aiosqlite, defusedxml, RapidFuzz, pytest, Caddy, Bash, systemd, restic-compatible encrypted off-site backups.

## Global Constraints

- The deployed Misaka image must resolve to the latest stable release and then be pinned by immutable image digest; beta, alpha, rc, draft, and GitHub prerelease releases are forbidden.
- MySQL must remain pinned to `mysql:8.1.0-oracle` until a separately tested database-upgrade plan changes it.
- Redis is not included; Misaka uses its default hybrid cache and Autopilot uses SQLite WAL because the expected maximum is three concurrent devices.
- The service must work without Emby administrator access, media-directory access, plugins, or webhooks; first playback is the primary trigger.
- High-, medium-, and low-confidence results all execute automatically. Low-confidence results must be labeled, notified, retained for reprocessing, and must never wait for confirmation.
- Normal scrolling, top, bottom, color, time, text, and basic size fields must be preserved; unsupported advanced platform effects must not be fabricated.
- The system must never bypass membership, payment, copyright, account, or regional access controls; cookies only authorize data the account can already access.
- Raw danmaku must be immutable. All trim, shift, split, merge, filter, and deduplication outputs are derived artifacts with provenance.
- MySQL, Misaka external-control endpoints, Autopilot administration, and Docker Socket must not be publicly exposed.
- Secrets must be excluded from Git, stored in files with mode `0600`, and redacted from logs and notifications.
- The public API must fail open to ordinary Misaka behavior if Autopilot analysis fails, so optional automation cannot remove otherwise available danmaku.
- Every automatic upgrade must create a consistent pre-update backup, run external and internal smoke tests, and automatically restore the previous image and database when required.
- This plan creates local deployment artifacts only. It must not connect to or mutate the user's VPS until the user separately authorizes deployment.

---

## File Map

The implementation creates these focused units:

```text
compose.yaml                         Container topology and loopback-only ports
.env.example                        Non-secret configuration contract
.gitignore                          Secret, backup, state, and scratch exclusions
README.md                           One-command entry point and document index
deploy/images.lock.example          Immutable image-lock schema

autopilot/Dockerfile                Runtime/test image stages
autopilot/pyproject.toml             Python dependencies and tool configuration
autopilot/src/danmu_autopilot/
  __init__.py                       Package version
  config.py                         Environment settings and validation
  domain.py                         Shared immutable dataclasses and enums
  logging.py                        Structured secret-redacting logs
  release.py                        Stable-release selection and image-lock types
  misaka.py                         Typed external-control and proxy client
  gateway.py                        Transparent player API proxy
  normalize.py                      Title, filename, season, episode, alias parsing
  xml.py                            XML parsing, transforms, provenance, serialization
  signals.py                        Metadata, density, semantic, and duration signals
  segment.py                        Boundary optimization and confidence scoring
  sources/bilibili.py               Authorized Bilibili metadata/danmaku adapter
  media_probe.py                    Bounded keyframe/audio fallback analysis
  ai.py                             Optional OpenAI-compatible low-confidence reviewer
  store.py                          SQLite schema, rules, artifacts, and persistent jobs
  pipeline.py                       End-to-end automatic decision state machine
  notify.py                         Webhook/Telegram/ServerChan notification adapter
  main.py                           FastAPI application and worker lifespan
autopilot/tests/                    Unit, contract, integration harness, and synthetic fixtures

caddy/Caddyfile.native.example      Existing native Caddy integration
caddy/Caddyfile.docker.example      Alternative containerized Caddy example

ops/lib.sh                          Shared strict-mode, lock, env, and logging helpers
ops/bootstrap.sh                    Idempotent one-command initialization
ops/preflight.sh                    Docker, DNS, source, proxy, disk, and port checks
ops/healthcheck.sh                  Internal and public smoke tests
ops/backup.sh                       Consistent local and optional encrypted remote backup
ops/restore.sh                      Validated restore into stopped services
ops/update.sh                       Stable release resolution and transactional update
ops/rollback.sh                     Latest or selected successful-version rollback
ops/notify.sh                       Shell-side notification entry point
ops/cloudflare-dns.sh               Idempotent A/AAAA/CNAME record management

systemd/                            Backup, update, health service/timer units
docs/                               Setup, player, proxy, backup, and troubleshooting guides
```

---

### Task 1: Repository Scaffold, Domain Types, and Secret-Redacting Configuration

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `autopilot/pyproject.toml`
- Create: `autopilot/Dockerfile`
- Create: `autopilot/src/danmu_autopilot/__init__.py`
- Create: `autopilot/src/danmu_autopilot/config.py`
- Create: `autopilot/src/danmu_autopilot/domain.py`
- Create: `autopilot/src/danmu_autopilot/logging.py`
- Create: `autopilot/tests/test_config.py`
- Create: `autopilot/tests/test_logging.py`

**Interfaces:**
- Produces: `Settings`, `Comment`, `MatchContext`, `SourceCandidate`, `Evidence`, `Segment`, `AnalysisResult`, `Confidence`, and `redact(value: object) -> object`.
- Consumes: only Python standard library and declared dependencies.

- [ ] **Step 1: Write failing settings and redaction tests**

```python
def test_settings_reject_public_control_api(monkeypatch):
    monkeypatch.setenv("MISAKA_BASE_URL", "http://misaka:7768")
    monkeypatch.setenv("MISAKA_CONTROL_KEY", "secret-control-key")
    monkeypatch.setenv("STATE_DIR", "/data")
    settings = Settings()
    assert settings.misaka_base_url.host == "misaka"
    assert "secret-control-key" not in repr(settings)

def test_redact_nested_secrets():
    value = {"cookie": "SESSDATA=abc", "url": "/token-abc/api/v2/match"}
    assert redact(value) == {"cookie": "[REDACTED]", "url": "/[TOKEN]/api/v2/match"}
```

- [ ] **Step 2: Run the tests and confirm the missing-module failure**

Run: `cd autopilot && python -m pytest tests/test_config.py tests/test_logging.py -v`

Expected: FAIL because `danmu_autopilot.config` and `danmu_autopilot.logging` do not exist.

- [ ] **Step 3: Define exact domain contracts**

```python
class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

@dataclass(frozen=True, slots=True)
class Comment:
    time_ms: int
    mode: int
    color: int
    size: int
    text: str
    source_id: str

@dataclass(frozen=True, slots=True)
class Segment:
    episode: int
    source_start_ms: int
    source_end_ms: int
    target_start_ms: int = 0

@dataclass(frozen=True, slots=True)
class AnalysisResult:
    segments: tuple[Segment, ...]
    score: float
    confidence: Confidence
    evidence: tuple[Evidence, ...]
```

- [ ] **Step 4: Implement validated settings and recursive redaction**

`Settings` must validate internal `http://misaka:7768`, require a non-empty control key, cap scratch space at 500 MiB by default, and expose secrets through `SecretStr`. `redact()` must redact keys matching `token`, `cookie`, `authorization`, `password`, `secret`, and token-looking URL path components.

- [ ] **Step 5: Run unit tests and static checks**

Run: `cd autopilot && python -m pytest tests/test_config.py tests/test_logging.py -v && python -m compileall -q src`

Expected: all tests PASS and compileall exits 0.

- [ ] **Step 6: Build both Docker stages**

Run: `docker build --target test -t danmu-autopilot:test autopilot && docker build --target runtime -t danmu-autopilot:local autopilot`

Expected: both images build; runtime runs as numeric non-root UID and contains no pytest dependency.

- [ ] **Step 7: Commit the scaffold**

```bash
git add .gitignore .env.example autopilot
git commit -m "chore: scaffold danmaku autopilot"
```

---

### Task 2: Stable Misaka Release Resolver and Immutable Image Lock

**Files:**
- Create: `deploy/images.lock.example`
- Create: `ops/resolve-images.py`
- Create: `autopilot/src/danmu_autopilot/release.py`
- Create: `autopilot/tests/test_release_resolver.py`
- Create: `autopilot/tests/fixtures/github-releases.json`

**Interfaces:**
- Produces: CLI `python ops/resolve-images.py --lock deploy/images.lock`.
- Produces: `select_latest_stable(releases: list[dict[str, object]]) -> dict[str, object]` and immutable `ImageLock` in `danmu_autopilot.release`; the CLI is a thin wrapper around these tested functions.
- Produces lock keys: `MISAKA_RELEASE`, `MISAKA_IMAGE`, `MISAKA_DIGEST`, `MYSQL_IMAGE`, `AUTOPILOT_IMAGE`.
- Consumes: GitHub Releases API and Docker Registry manifest API; never Docker Hub HTML.

- [ ] **Step 1: Write release-selection tests**

```python
def test_latest_stable_excludes_prereleases():
    releases = [
        {"tag_name": "v2.9.0-rc1", "draft": False, "prerelease": True},
        {"tag_name": "v2.8.3", "draft": False, "prerelease": False},
        {"tag_name": "v2.8.2", "draft": False, "prerelease": False},
    ]
    assert select_latest_stable(releases)["tag_name"] == "v2.8.3"

def test_lock_rejects_mutable_reference():
    with pytest.raises(ValueError, match="sha256"):
        ImageLock(misaka_digest="latest")
```

- [ ] **Step 2: Verify the tests fail**

Run: `cd autopilot && python -m pytest tests/test_release_resolver.py -v`

Expected: FAIL because resolver functions are absent.

- [ ] **Step 3: Implement stable selection and digest resolution**

Selection must require `draft is False`, `prerelease is False`, and reject tag names matching `(?i)(alpha|beta|rc|preview|dev)`. Resolve the image manifest digest after authentication and write the lock atomically with mode `0644`; no credential may enter the file.

- [ ] **Step 4: Test against fixtures and a temporary lock**

Run: `python ops/resolve-images.py --releases-file autopilot/tests/fixtures/github-releases.json --digest sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa --lock /tmp/danmu-images.lock`

Expected: `/tmp/danmu-images.lock` contains `MISAKA_RELEASE=v2.8.3` and a digest-qualified image reference.

- [ ] **Step 5: Commit the resolver**

```bash
git add deploy/images.lock.example ops/resolve-images.py autopilot/src/danmu_autopilot/release.py autopilot/tests
git commit -m "feat: resolve immutable stable images"
```

---

### Task 3: Secure Docker Compose Foundation

**Files:**
- Create: `compose.yaml`
- Create: `autopilot/tests/test_compose.py`
- Modify: `.env.example`

**Interfaces:**
- Produces services `mysql`, `misaka`, and `autopilot` on internal network `danmu-internal`.
- Exposes only `127.0.0.1:${MISAKA_BIND_PORT}:7768` and `127.0.0.1:${AUTOPILOT_BIND_PORT}:8080`.
- Consumes: `deploy/images.lock` and `.env` generated by bootstrap.

- [ ] **Step 1: Write Compose policy tests**

```python
def test_only_loopback_ports_are_published(compose):
    published = [p for service in compose["services"].values() for p in service.get("ports", [])]
    assert published == [
        "127.0.0.1:${MISAKA_BIND_PORT:-7768}:7768",
        "127.0.0.1:${AUTOPILOT_BIND_PORT:-7770}:8080",
    ]

def test_no_service_mounts_docker_socket(compose):
    assert "/var/run/docker.sock" not in json.dumps(compose)
```

- [ ] **Step 2: Run the policy tests and confirm failure**

Run: `cd autopilot && python -m pytest tests/test_compose.py -v`

Expected: FAIL because `compose.yaml` is missing.

- [ ] **Step 3: Create the Compose topology**

Use `mysql:8.1.0-oracle`, `utf8mb4`, three-day binlog expiry, health-gated startup, named volumes, `restart: unless-stopped`, `no-new-privileges:true`, explicit resource limits, and log rotation. Misaka uses hybrid cache. Autopilot has a read-only root filesystem, writable `/data` and `/scratch` mounts, and a tmpfs `/tmp`.

- [ ] **Step 4: Validate rendered Compose**

Run: `cp .env.example .env.test && docker compose --env-file .env.test -f compose.yaml config --quiet`

Expected: exit 0 without contacting a registry.

- [ ] **Step 5: Run policy tests**

Run: `cd autopilot && python -m pytest tests/test_compose.py -v`

Expected: all Compose security-policy tests PASS.

- [ ] **Step 6: Commit the foundation**

```bash
git add compose.yaml .env.example autopilot/tests/test_compose.py
git commit -m "feat: add secure compose foundation"
```

---

### Task 4: Misaka Contract Discovery and Typed Client

**Files:**
- Create: `ops/capture-misaka-contract.sh`
- Create: `autopilot/src/danmu_autopilot/misaka.py`
- Create: `autopilot/tests/test_misaka.py`
- Create: `autopilot/tests/fixtures/misaka-openapi.required.json`

**Interfaces:**
- Produces: `ResponseData`, `XmlImport`, `ImportResult`, `MisakaClient.proxy(request)`, `search(query)`, `auto_import(request)`, `import_xml(request)`, `get_comments(episode_id)`, `replace_comments(episode_id, comments)`, and `task(task_id)`.
- Consumes: Misaka routes `/api/control/import/auto`, `/api/control/search`, `/api/control/import/xml`, `/api/control/danmaku/{episodeId}`, `/api/control/tasks/{taskId}`, and the player API paths.

- [ ] **Step 1: Capture the current OpenAPI contract from a local pinned container**

Run: `docker compose up -d mysql misaka && bash ops/capture-misaka-contract.sh`

Expected: the script waits for `/api/docs`, downloads `/openapi.json`, checks every required route, and writes only the reduced route/schema subset to `autopilot/tests/fixtures/misaka-openapi.required.json`.

- [ ] **Step 2: Write HTTP contract tests with respx**

```python
@pytest.mark.asyncio
async def test_control_key_is_query_parameter_but_redacted(settings, respx_mock):
    route = respx_mock.post("http://misaka:7768/api/control/import/xml").mock(
        return_value=httpx.Response(200, json={"success": True, "episodeId": 42})
    )
    result = await MisakaClient(settings).import_xml(XmlImport(episode_id=42, xml="<i/>"))
    assert result.episode_id == 42
    assert route.calls[0].request.url.params["api_key"] == settings.misaka_control_key.get_secret_value()
```

- [ ] **Step 3: Verify the client tests fail**

Run: `cd autopilot && python -m pytest tests/test_misaka.py -v`

Expected: FAIL because `MisakaClient` is absent.

- [ ] **Step 4: Implement the typed adapter**

Use one shared `httpx.AsyncClient`, strict connect/read timeouts, bounded response sizes, three retries only for idempotent reads, and typed exceptions `MisakaUnavailable`, `MisakaRejected`, and `MisakaContractChanged`. Never log a URL after the control key is appended.

- [ ] **Step 5: Run contract and client tests**

Run: `cd autopilot && python -m pytest tests/test_misaka.py -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit the adapter**

```bash
git add ops/capture-misaka-contract.sh autopilot/src/danmu_autopilot/misaka.py autopilot/tests
git commit -m "feat: add typed Misaka control client"
```

---

### Task 5: Transparent Player Gateway with Fail-Open Behavior

**Files:**
- Create: `autopilot/src/danmu_autopilot/gateway.py`
- Create: `autopilot/src/danmu_autopilot/main.py`
- Create: `autopilot/tests/test_gateway.py`

**Interfaces:**
- Produces: FastAPI routes `/healthz`, `/readyz`, and catch-all player proxy for all HTTP methods.
- Produces callback `enqueue_match(context: MatchContext, upstream: UpstreamResult) -> None`.
- Consumes: `MisakaClient.proxy()` and `redact()`.

- [ ] **Step 1: Write streaming and fail-open tests**

```python
@pytest.mark.asyncio
async def test_match_response_is_unchanged(client, misaka_proxy):
    misaka_proxy.return_value = ResponseData(200, [(b"content-type", b"application/json")], b'{"isMatched":true}')
    response = await client.post("/device-token/api/v2/match", json={"fileName": "Show.S01E01.mkv"})
    assert response.status_code == 200
    assert response.content == b'{"isMatched":true}'

@pytest.mark.asyncio
async def test_analysis_enqueue_failure_does_not_change_response(client, enqueue):
    enqueue.side_effect = RuntimeError("queue unavailable")
    response = await client.post("/device-token/api/v2/match", json={"fileName": "Show.S01E01.mkv"})
    assert response.status_code == 200
```

- [ ] **Step 2: Verify tests fail**

Run: `cd autopilot && python -m pytest tests/test_gateway.py -v`

Expected: FAIL because the application routes are absent.

- [ ] **Step 3: Implement transparent proxying**

Forward method, path, query, selected request headers, body, upstream status, safe response headers, and bytes unchanged. Strip hop-by-hop headers. Enforce request/response limits high enough for danmaku XML but reject unrelated uploads. Schedule analysis only after the upstream body is safely captured and never await the analysis job before returning.

- [ ] **Step 4: Add health semantics**

`/healthz` reports process liveness without dependencies. `/readyz` verifies SQLite and Misaka within two seconds. Neither endpoint includes versions, secrets, source URLs, or exception traces.

- [ ] **Step 5: Run gateway tests**

Run: `cd autopilot && python -m pytest tests/test_gateway.py -v`

Expected: all tests PASS, including byte-for-byte passthrough and token-redaction assertions.

- [ ] **Step 6: Commit the gateway**

```bash
git add autopilot/src/danmu_autopilot/gateway.py autopilot/src/danmu_autopilot/main.py autopilot/tests/test_gateway.py
git commit -m "feat: proxy player requests through autopilot"
```

---

### Task 6: Filename, Season/Episode, and Alias Normalization

**Files:**
- Create: `autopilot/src/danmu_autopilot/normalize.py`
- Create: `autopilot/tests/test_normalize.py`
- Create: `autopilot/tests/fixtures/aliases.json`

**Interfaces:**
- Produces: `parse_match_context(filename: str) -> MatchContext`.
- Produces: `expand_aliases(title: str, catalog: AliasCatalog) -> tuple[str, ...]`.
- Produces: immutable `AliasCatalog(local, metadata, learned)` with deterministic priority `learned > metadata > local > original`.
- Consumes: `MatchContext` and no external network.

- [ ] **Step 1: Write multilingual parsing tests**

```python
@pytest.mark.parametrize(("name", "title", "season", "episode"), [
    ("Show.Name.S03E08.2160p.WEB-DL.mkv", "Show Name", 3, 8),
    ("躲在超市门口抽烟的两人 - 02.mp4", "躲在超市门口抽烟的两人", 1, 2),
    ("东京吃人 第2季 03", "东京吃人", 2, 3),
])
def test_parse_match_context(name, title, season, episode):
    result = parse_match_context(name)
    assert (result.title, result.season, result.episode) == (title, season, episode)
```

- [ ] **Step 2: Verify parsing tests fail**

Run: `cd autopilot && python -m pytest tests/test_normalize.py -v`

Expected: FAIL because normalization is absent.

- [ ] **Step 3: Implement deterministic normalization**

Remove extensions, codec/release/noise tokens, normalize Unicode NFKC, parse `SxxExx`, Chinese season/episode forms, bracketed release tags, and preserve the original filename. Alias expansion merges the local curated catalog, Misaka/TMDB/Bangumi aliases when present, and learned user rules while keeping deterministic priority and deduplication.

- [ ] **Step 4: Add ambiguity tests**

Movie years must not become episode numbers, `1080p` must not become episode 1080, and a bare trailing number is accepted only when the remaining title contains meaningful characters.

- [ ] **Step 5: Run tests and commit**

Run: `cd autopilot && python -m pytest tests/test_normalize.py -v`

```bash
git add autopilot/src/danmu_autopilot/normalize.py autopilot/tests
git commit -m "feat: normalize media names and aliases"
```

---

### Task 7: Loss-Aware XML Parsing, Timeline Mapping, Splitting, and Deduplication

**Files:**
- Create: `autopilot/src/danmu_autopilot/xml.py`
- Create: `autopilot/tests/test_xml.py`
- Create: `autopilot/tests/fixtures/synthetic-comments.xml`

**Interfaces:**
- Produces: `parse_xml(data: bytes, source_id: str) -> tuple[Comment, ...]`.
- Produces: `map_timeline(comments, pieces)`, `split_comments(comments, segments)`, `deduplicate(comments, window_ms)`, and `serialize_xml(comments, provenance) -> bytes`.
- Produces: immutable `TimelinePiece(source_start_ms, source_end_ms, target_start_ms)` and `Provenance(source_url_hash, fetched_at, algorithm_version, evidence_ids)`.
- Consumes: `Comment` and `Segment`.

- [ ] **Step 1: Write transform invariants**

```python
def test_negative_shift_drops_only_pre_roll():
    comments = (
        Comment(7_100_000, 1, 0xFFFFFF, 25, "垫片", "bili:1"),
        Comment(7_205_000, 5, 0xFF0000, 36, "正片", "bili:1"),
    )
    result = map_timeline(comments, (TimelinePiece(7_200_000, 8_460_000, 0),))
    assert result == (Comment(5_000, 5, 0xFF0000, 36, "正片", "bili:1"),)

def test_round_trip_preserves_mode_color_and_size():
    parsed = parse_xml(serialize_xml(COMMENTS, PROVENANCE), "fixture")
    assert [(c.mode, c.color, c.size) for c in parsed] == [(c.mode, c.color, c.size) for c in COMMENTS]
```

- [ ] **Step 2: Verify XML tests fail**

Run: `cd autopilot && python -m pytest tests/test_xml.py -v`

Expected: FAIL because XML functions are absent.

- [ ] **Step 3: Implement safe parsing and serialization**

Use `defusedxml`, reject documents above the configured byte/comment limits, parse the Bilibili `p` tuple without executing entities, preserve supported fields, escape text correctly, and write provenance outside player-visible comment text.

- [ ] **Step 4: Implement piecewise mapping and stable deduplication**

Timeline pieces are half-open `[source_start_ms, source_end_ms)`. Deduplication normalizes whitespace and Unicode, groups by mode/color/text within a configurable time window, and preserves the earliest stable source-priority winner.

- [ ] **Step 5: Run tests and commit**

Run: `cd autopilot && python -m pytest tests/test_xml.py -v`

```bash
git add autopilot/src/danmu_autopilot/xml.py autopilot/tests/test_xml.py autopilot/tests/fixtures/synthetic-comments.xml
git commit -m "feat: transform danmaku timelines safely"
```

---

### Task 8: Metadata, Density, Semantic, and Duration Signal Extraction

**Files:**
- Create: `autopilot/src/danmu_autopilot/signals.py`
- Create: `autopilot/tests/test_signals.py`
- Create: `autopilot/tests/fixtures/two-hour-padding.xml`

**Interfaces:**
- Produces: `extract_signals(comments, source_meta, work_meta) -> tuple[Evidence, ...]`.
- Produces evidence kinds `duration_ratio`, `density_change`, `semantic_anchor`, `chapter`, `episode_count_fit`, `title_cue`, and `access_restriction`.
- Produces: immutable `SourceMeta`, `WorkMeta`, and test/helper function `strongest(evidence, kind)`.
- Consumes: parsed comments, source duration/pages/view points, expected episode count/runtime.

- [ ] **Step 1: Write the two-hour-padding signal test**

```python
def test_two_hour_padding_emits_start_and_eight_episode_fit(fixture_comments):
    evidence = extract_signals(
        fixture_comments,
        SourceMeta(duration_ms=17_283_000, pages=1, view_points=()),
        WorkMeta(episode_count=8, expected_episode_ms=1_260_000),
    )
    assert strongest(evidence, "density_change").time_ms in range(7_180_000, 7_221_000)
    assert strongest(evidence, "episode_count_fit").score >= 0.9
```

- [ ] **Step 2: Verify signal tests fail**

Run: `cd autopilot && python -m pytest tests/test_signals.py -v`

Expected: FAIL because signal extraction is absent.

- [ ] **Step 3: Implement deterministic signals**

Use rolling density windows, robust median/MAD change detection, weighted Chinese/Japanese/English semantic patterns, title cues, duration ratios, chapter boundaries, and expected-runtime fit. Semantic matches must contribute evidence but cannot alone produce high confidence.

- [ ] **Step 4: Test false positives**

A normal 24-minute episode with a comment saying “终于开始了” at 15 minutes must not be classified as padded. A zero-comment source must return low-confidence metadata evidence instead of raising.

- [ ] **Step 5: Run tests and commit**

Run: `cd autopilot && python -m pytest tests/test_signals.py -v`

```bash
git add autopilot/src/danmu_autopilot/signals.py autopilot/tests
git commit -m "feat: extract anomaly timeline signals"
```

---

### Task 9: Episode Boundary Optimizer and Confidence Policy

**Files:**
- Create: `autopilot/src/danmu_autopilot/segment.py`
- Create: `autopilot/tests/test_segment.py`

**Interfaces:**
- Produces: `analyze_timeline(comments, source_meta, work_meta, evidence) -> AnalysisResult`.
- Consumes: evidence from Task 8 and outputs segment boundaries for Task 7.

- [ ] **Step 1: Write exact policy tests**

```python
def test_strong_two_hour_sample_splits_eight_episodes(input_data):
    result = analyze_timeline(**input_data)
    assert result.confidence is Confidence.HIGH
    assert len(result.segments) == 8
    assert abs(result.segments[0].source_start_ms - 7_200_000) <= 30_000
    assert result.segments[-1].source_end_ms == 17_283_000

def test_weak_input_still_returns_best_effort():
    result = analyze_timeline(comments=(), source_meta=WEAK_SOURCE, work_meta=EIGHT_EPISODES, evidence=())
    assert result.confidence is Confidence.LOW
    assert len(result.segments) == 8
```

- [ ] **Step 2: Verify optimizer tests fail**

Run: `cd autopilot && python -m pytest tests/test_segment.py -v`

Expected: FAIL because the optimizer is absent.

- [ ] **Step 3: Implement constrained boundary selection**

Generate candidate boundaries from evidence plus expected-runtime intervals. Use dynamic programming to minimize runtime deviation, boundary-distance penalties, missing evidence, and leftover duration. Require monotonic non-overlapping segments and a minimum runtime floor. Convert normalized score to `HIGH >= 0.82`, `MEDIUM >= 0.60`, otherwise `LOW`.

- [ ] **Step 4: Add movie and mid-episode-cut cases**

A movie returns one shifted segment. A synthetic deletion creates two `TimelinePiece` mappings rather than one global offset. Impossible negative or overlapping segments must raise `InvalidTimeline` before data is imported.

- [ ] **Step 5: Run tests and commit**

Run: `cd autopilot && python -m pytest tests/test_segment.py -v`

```bash
git add autopilot/src/danmu_autopilot/segment.py autopilot/tests/test_segment.py
git commit -m "feat: optimize automatic episode boundaries"
```

---

### Task 10: Authorized Bilibili Adapter and Bounded Media Probe

**Files:**
- Create: `autopilot/src/danmu_autopilot/sources/__init__.py`
- Create: `autopilot/src/danmu_autopilot/sources/bilibili.py`
- Create: `autopilot/src/danmu_autopilot/media_probe.py`
- Create: `autopilot/tests/test_bilibili.py`
- Create: `autopilot/tests/test_media_probe.py`

**Interfaces:**
- Produces: `BilibiliClient.resolve(url_or_bvid) -> BilibiliSourceMeta` and `fetch_comments(cid) -> bytes`.
- Produces: `probe_media(url, cookie_file, limits) -> tuple[Evidence, ...]`.
- Consumes: HTTPX, optional mounted cookie file, `yt-dlp` and `ffmpeg` only in the analysis image layer.

- [ ] **Step 1: Write metadata and access-control tests**

```python
@pytest.mark.asyncio
async def test_empty_view_points_are_valid(bili_client, respx_mock):
    mock_view(duration=17_283, cid=35_321_351_311)
    mock_player(view_points=[], preview_toast="")
    meta = await bili_client.resolve("BV1HS6ZBiE43")
    assert meta.duration_ms == 17_283_000
    assert meta.view_points == ()

@pytest.mark.asyncio
async def test_paid_preview_without_entitlement_is_not_bypassed(bili_client):
    mock_player(preview_toast="购买观看", permission="0")
    with pytest.raises(SourceAccessDenied):
        await bili_client.fetch_comments(35_321_351_311)
```

- [ ] **Step 2: Verify adapter tests fail**

Run: `cd autopilot && python -m pytest tests/test_bilibili.py tests/test_media_probe.py -v`

Expected: FAIL because source adapters are absent.

- [ ] **Step 3: Implement the public metadata and cookie-aware comment flow**

Resolve BV/AV/CID, accept empty chapters, send a browser-like but honest User-Agent, apply source-specific rate limiting, and load cookies only from a mounted `0600` file. Detect login, payment, and entitlement errors from structured responses and stop without alternate bypass requests.

- [ ] **Step 4: Implement bounded fallback probing**

Use `yt-dlp --cookies <file> --no-playlist` only when the same account is authorized. Request the lowest suitable audio/storyboard representation, cap scratch use at 500 MiB, terminate after the configured duration, extract scene and audio-energy timestamps with ffmpeg, and delete scratch files in a `finally` block. No full video is retained.

- [ ] **Step 5: Run source tests without live network**

Run: `cd autopilot && python -m pytest tests/test_bilibili.py tests/test_media_probe.py -v`

Expected: all mocked tests PASS; no test contacts Bilibili.

- [ ] **Step 6: Add an opt-in live diagnostic**

Run: `BILI_LIVE_TEST=1 BILI_TEST_URL='https://www.bilibili.com/video/BV1HS6ZBiE43/' python -m pytest autopilot/tests/live/test_bilibili_live.py -v`

Expected: the test skips without `BILI_LIVE_TEST=1`; with authorization it reports metadata and signal counts but never saves full comment text as a fixture.

- [ ] **Step 7: Commit the adapter**

```bash
git add autopilot/src/danmu_autopilot/sources autopilot/src/danmu_autopilot/media_probe.py autopilot/tests
git commit -m "feat: analyze authorized Bilibili sources"
```

---

### Task 11: Persistent Job Store, Rules, Artifacts, and Automatic Pipeline

**Files:**
- Create: `autopilot/src/danmu_autopilot/store.py`
- Create: `autopilot/src/danmu_autopilot/pipeline.py`
- Create: `autopilot/src/danmu_autopilot/ai.py`
- Create: `autopilot/tests/test_store.py`
- Create: `autopilot/tests/test_pipeline.py`

**Interfaces:**
- Produces: `JobStore.enqueue()`, `claim()`, `succeed()`, `retry()`, `fail()`, `save_rule()`, and `save_artifact()`.
- Produces: `AutopilotPipeline.handle(job_id: str) -> JobOutcome`.
- Consumes: normalization, Misaka client, XML transforms, signal extraction, segment optimizer, source adapters, and notifier.

- [ ] **Step 1: Write crash-recovery and idempotency tests**

```python
@pytest.mark.asyncio
async def test_running_job_is_reclaimed_after_lease(store):
    job = await store.enqueue(MATCH_REQUEST)
    claimed = await store.claim(worker="one", lease_seconds=1)
    await advance_clock(seconds=2)
    reclaimed = await store.claim(worker="two", lease_seconds=30)
    assert reclaimed.id == claimed.id == job.id

@pytest.mark.asyncio
async def test_same_match_is_enqueued_once(store):
    first = await store.enqueue(MATCH_REQUEST)
    second = await store.enqueue(MATCH_REQUEST)
    assert first.id == second.id
```

- [ ] **Step 2: Verify persistence tests fail**

Run: `cd autopilot && python -m pytest tests/test_store.py tests/test_pipeline.py -v`

Expected: FAIL because store and pipeline are absent.

- [ ] **Step 3: Implement the SQLite WAL schema and migrations**

Tables: `schema_version`, `jobs`, `artifacts`, `analysis_runs`, `rules`, `source_scores`, and `notifications`. Raw artifacts are content-addressed SHA-256 files under `/data/raw`; derived artifacts go under `/data/derived/<algorithm-version>`. Transactions claim jobs with leases and unique idempotency keys.

- [ ] **Step 4: Implement the pipeline state machine**

States are `queued`, `normal_match`, `candidate_search`, `source_fetch`, `analyze`, `derive`, `import`, `verify`, `succeeded`, `retry_wait`, and `failed`. Permanent access denial does not retry. Transient network failures retry with capped exponential backoff and deterministic jitter. Every confidence level proceeds to import when no better source exists.

The worker also performs a daily reconciliation against Misaka's library/source records. A user correction made in the Misaka Web UI becomes a protected learned rule; later automatic reprocessing may read and reuse it but cannot overwrite it unless the user removes that rule.

- [ ] **Step 5: Implement optional AI review without control authority**

The OpenAI-compatible reviewer accepts only normalized title, numeric signals, and short selected anchor texts. It returns typed JSON suggestions. Its output may raise or lower the score within a small bounded range but may not authorize access, delete artifacts, or directly select a source. With no API key, it returns `AiReview.disabled()` and the deterministic pipeline continues.

- [ ] **Step 6: Verify import and post-import readback**

Pipeline tests must assert that XML is imported through `MisakaClient.import_xml()`, then read back through `get_comments()`, with episode count and first/last timestamps checked before marking success.

- [ ] **Step 7: Run tests and commit**

Run: `cd autopilot && python -m pytest tests/test_store.py tests/test_pipeline.py -v`

```bash
git add autopilot/src/danmu_autopilot/store.py autopilot/src/danmu_autopilot/pipeline.py autopilot/src/danmu_autopilot/ai.py autopilot/tests
git commit -m "feat: run persistent automatic correction jobs"
```

---

### Task 12: Network Preflight, Per-Source Proxying, and Source Circuit Breakers

**Files:**
- Create: `ops/lib.sh`
- Create: `ops/preflight.sh`
- Create: `autopilot/src/danmu_autopilot/circuit.py`
- Create: `autopilot/tests/test_circuit.py`
- Modify: `.env.example`

**Interfaces:**
- Produces report `state/preflight.json` and human-readable terminal summary.
- Produces: `CircuitBreaker.allow(source)`, `record_success(source)`, and `record_failure(source, kind)`.
- Consumes optional `SOURCE_PROXY_BILIBILI`, `SOURCE_PROXY_TENCENT`, and equivalent HTTP/SOCKS5 URLs.

- [ ] **Step 1: Write breaker transition tests**

```python
def test_breaker_opens_then_half_opens(clock):
    breaker = CircuitBreaker(threshold=3, cool_down_seconds=60, clock=clock)
    for _ in range(3):
        breaker.record_failure("bilibili", FailureKind.TRANSIENT)
    assert not breaker.allow("bilibili")
    clock.advance(61)
    assert breaker.allow("bilibili", probe=True)
```

- [ ] **Step 2: Implement strict shell helpers and preflight checks**

`ops/lib.sh` enables `set -Eeuo pipefail`, validates the project directory is not `/`, `$HOME`, or empty, loads `.env` without printing it, and uses `flock`. Preflight checks Docker/Compose versions, x86_64 architecture, ports 7768/7770/80/443, free disk, DNS A/AAAA, TLS reachability, GitHub, Docker registry, Bilibili, Tencent, iQiyi, Youku, Mango, and configured proxy paths.

- [ ] **Step 3: Distinguish routing failures**

The report must distinguish DNS error, TCP timeout, TLS error, HTTP block, login required, geographic restriction, rate limit, and success. Never infer that a same-host Dallas Snell server provides a different regional egress.

- [ ] **Step 4: Implement per-source proxy and breaker integration**

HTTP clients choose proxy by source key. Misaka proxy configuration is generated only for affected scrapers where the current version exposes it. A failed proxy falls back to direct access only when direct access passed preflight.

- [ ] **Step 5: Run shell and Python tests**

Run: `bash -n ops/lib.sh ops/preflight.sh && cd autopilot && python -m pytest tests/test_circuit.py -v`

Expected: syntax and unit tests PASS.

- [ ] **Step 6: Commit network automation**

```bash
git add ops/lib.sh ops/preflight.sh .env.example autopilot/src/danmu_autopilot/circuit.py autopilot/tests/test_circuit.py
git commit -m "feat: automate source network diagnostics"
```

---

### Task 13: Caddy, Cloudflare DNS, and Idempotent Bootstrap

**Files:**
- Create: `caddy/Caddyfile.native.example`
- Create: `caddy/Caddyfile.docker.example`
- Create: `ops/cloudflare-dns.sh`
- Create: `ops/bootstrap.sh`
- Create: `autopilot/tests/test_caddy.py`
- Create: `autopilot/tests/test_bootstrap.py`

**Interfaces:**
- Produces public `https://${DANMU_API_HOST}` and protected `https://${DANMU_ADMIN_HOST}`.
- Produces generated `.env`, `secrets/`, `deploy/images.lock`, volumes, and Caddy snippet.
- Consumes optional Cloudflare API token with only Zone DNS Edit and Zone Read for the selected zone.

- [ ] **Step 1: Write route exposure tests**

```python
def test_control_routes_are_not_on_player_host(caddy_text):
    player_block = site_block(caddy_text, "{$DANMU_API_HOST}")
    assert "/api/control" in player_block
    assert "respond 404" in player_block
    assert "reverse_proxy 127.0.0.1:7770" in player_block

def test_admin_has_two_auth_layers(caddy_text):
    admin_block = site_block(caddy_text, "{$DANMU_ADMIN_HOST}")
    assert "basic_auth" in admin_block
    assert "reverse_proxy 127.0.0.1:7768" in admin_block
```

- [ ] **Step 2: Verify policy tests fail**

Run: `cd autopilot && python -m pytest tests/test_caddy.py tests/test_bootstrap.py -v`

Expected: FAIL because templates and bootstrap are absent.

- [ ] **Step 3: Implement the native Caddy template**

Player host routes only compatible player paths to 127.0.0.1:7770, returns 404 for `/api/control*`, `/api/docs*`, admin paths, and unknown uploads, disables sensitive access logging, and sets safe proxy headers. Admin host uses Caddy hashed Basic Auth before proxying to 127.0.0.1:7768.

- [ ] **Step 4: Implement Cloudflare DNS idempotency**

With a scoped token, look up zone ID and existing records, create or update only the two exact hostnames, preserve unrelated records, and print a dry-run diff before mutation unless `--apply` is supplied.

- [ ] **Step 5: Implement one-command bootstrap**

Bootstrap runs preflight, generates 32-byte random database/JWT/control secrets, generates separate device tokens, writes all secret files mode `0600`, resolves image digests, renders a Caddy snippet, validates Compose, starts containers, waits for health, configures Misaka through supported control/config APIs, creates tokens, and prints redacted player URLs. Re-running must not rotate existing secrets unless `--rotate <name>` is explicit.

The initial Misaka policy enables match fallback, fallback search, sequential fallback, and next-episode predownload; sets hybrid cache; orders exact single-episode sources ahead of compilations; uses a 5,000-comment output cap for mixed mobile/desktop clients; preserves existing colors; leaves random-color injection off; and loads the recommended advertisement/spam blacklist into a disabled-by-default profile the user can enable from the Web UI.

- [ ] **Step 6: Test bootstrap in a temporary project directory**

Run: `python -m pytest autopilot/tests/test_bootstrap.py -v`

Expected: two dry-run executions produce the same secret hashes and neither attempts SSH or VPS access.

- [ ] **Step 7: Commit ingress and bootstrap**

```bash
git add caddy ops/cloudflare-dns.sh ops/bootstrap.sh autopilot/tests
git commit -m "feat: automate secure ingress and bootstrap"
```

---

### Task 14: Notifications, Health Checks, and Self-Healing Timers

**Files:**
- Create: `autopilot/src/danmu_autopilot/notify.py`
- Create: `ops/notify.sh`
- Create: `ops/healthcheck.sh`
- Create: `systemd/danmu-health.service`
- Create: `systemd/danmu-health.timer`
- Create: `autopilot/tests/test_notify.py`
- Create: `autopilot/tests/test_healthcheck.py`

**Interfaces:**
- Produces notification severity `info`, `warning`, `critical` and deduplication key.
- Produces health exit codes: `0 healthy`, `1 degraded source`, `2 service unhealthy`, `3 secret/config error`.
- Consumes generic webhook, Telegram, ServerChan, or log-only configuration.

- [ ] **Step 1: Write notification redaction and deduplication tests**

```python
@pytest.mark.asyncio
async def test_notification_never_contains_cookie_or_token(notifier):
    await notifier.send("cookie expired", {"cookie": "SESSDATA=abc", "token": "xyz"})
    body = notifier.transport.last_body
    assert "SESSDATA" not in body
    assert "xyz" not in body

@pytest.mark.asyncio
async def test_same_warning_is_sent_once_per_window(notifier):
    assert await notifier.send("source-down", {}, dedupe="bili-down")
    assert not await notifier.send("source-down", {}, dedupe="bili-down")
```

- [ ] **Step 2: Implement notification channels and severity policy**

Send low-confidence imports, cookie expiry, consecutive backup failures, source circuits, update/rollback, and service failures. Do not send routine match successes. A failed notification records locally and never fails the import pipeline.

Generate a weekly quiet summary containing match success rate, low-confidence count, source failure rate, cookie state, backup/restore-rehearsal status, and current locked versions. Send the summary only when a remote notification channel is configured; always retain it locally.

- [ ] **Step 3: Implement layered health checks**

Check Docker health, MySQL ping, Misaka UI, Misaka control API, Gateway readiness, public API hostname, certificate expiry, disk/inodes, latest backup age, cookie state, and source circuit summary. `--repair` may restart only the named unhealthy application container after capturing logs; it may not restart Docker or delete data.

- [ ] **Step 4: Add systemd health timer**

Run every five minutes with randomized delay, project path set explicitly, `NoNewPrivileges=true`, and output to journald. Install script validates units before enabling them.

- [ ] **Step 5: Run tests and commit**

Run: `bash -n ops/notify.sh ops/healthcheck.sh && cd autopilot && python -m pytest tests/test_notify.py tests/test_healthcheck.py -v`

```bash
git add autopilot/src/danmu_autopilot/notify.py autopilot/tests ops/notify.sh ops/healthcheck.sh systemd
git commit -m "feat: monitor and notify unattended service"
```

---

### Task 15: Consistent Backup, Verified Restore, and Off-Site Replication

**Files:**
- Create: `ops/backup.sh`
- Create: `ops/restore.sh`
- Create: `systemd/danmu-backup.service`
- Create: `systemd/danmu-backup.timer`
- Create: `autopilot/tests/test_backup_scripts.py`

**Interfaces:**
- Produces backup manifest fields `format_version`, `created_at`, `reason`, `misaka_release`, `images`, `sha256`, and `files`.
- Produces CLI `backup.sh --reason daily|pre-update|manual` and `restore.sh <backup-id> --verify|--apply`.
- Consumes optional restic repository credentials from a root-readable environment file.

- [ ] **Step 1: Write destructive-safety policy tests**

```python
def test_restore_requires_explicit_apply(script):
    assert "--apply" in script
    assert "refusing restore" in script.lower()

def test_scripts_never_recursive_delete_broad_paths(scripts):
    forbidden = ("rm -rf /", "rm -rf $HOME", "rm -rf ~")
    assert not any(text in scripts for text in forbidden)
```

- [ ] **Step 2: Implement locked consistent backup**

Use `flock`, run `mysqldump --single-transaction --routines --events --hex-blob`, checkpoint SQLite WAL, archive Misaka config plus Autopilot raw/derived/rules and image lock, hash every file, write manifest last, then atomically rename the completed directory. Keep 14 daily and five pre-update backups.

- [ ] **Step 3: Implement verified restore**

`--verify` checks manifest schema, hashes, decompression, SQL readability, SQLite integrity, and required files without stopping production. `--apply` requires an explicit backup ID, creates a safety backup, stops only application services, restores MySQL and files, starts services, runs health checks, and automatically restores the safety backup if verification fails.

- [ ] **Step 4: Implement weekly restore rehearsal and optional restic upload**

Restore the newest backup into temporary named volumes and a non-public temporary MySQL container, verify table counts and Autopilot integrity, then remove only the validated temporary resources. When restic is configured, run `restic backup`, `check --read-data-subset`, and retention; otherwise health output warns that backups are local-only.

- [ ] **Step 5: Run policy and shell tests**

Run: `bash -n ops/backup.sh ops/restore.sh && python -m pytest autopilot/tests/test_backup_scripts.py -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit backup and restore**

```bash
git add ops/backup.sh ops/restore.sh systemd/danmu-backup.service systemd/danmu-backup.timer autopilot/tests/test_backup_scripts.py
git commit -m "feat: back up and verify danmaku data"
```

---

### Task 16: Transactional Latest-Stable Update and One-Command Rollback

**Files:**
- Create: `ops/update.sh`
- Create: `ops/rollback.sh`
- Create: `systemd/danmu-update.service`
- Create: `systemd/danmu-update.timer`
- Create: `autopilot/tests/test_update_scripts.py`

**Interfaces:**
- Produces `update.sh --check|--apply` and `rollback.sh latest|<release>`.
- Consumes image resolver, backup, Compose, health check, and notification scripts.

- [ ] **Step 1: Write transaction-order tests**

```python
def test_update_orders_backup_before_recreate(trace):
    assert trace.index("backup --reason pre-update") < trace.index("compose up")

def test_failed_migration_restores_image_and_database(trace):
    assert "restore pre-update --apply" in trace
    assert "write old images.lock" in trace
    assert trace[-1] == "healthcheck"
```

- [ ] **Step 2: Implement check mode**

Resolve the latest stable GitHub release and registry digest, compare against `deploy/images.lock`, display release and digest changes, verify free disk and backup freshness, and make no changes in `--check` mode.

- [ ] **Step 3: Implement apply mode as a transaction**

Acquire the global maintenance lock, create pre-update backup, save old lock, pull the new digest, recreate only Misaka, wait for migrations, run internal and public smoke tests, observe a bounded stability window, write a successful-version record, and notify. On any failure restore old lock/image; if database compatibility checks fail, restore the pre-update database and data snapshot before final health check.

- [ ] **Step 4: Implement rollback selector**

`latest` selects the most recent successful prior version, not merely the latest backup. A named release must exist in backup manifests. Rollback prints the selected image/database pair, requires confirmation unless `--yes`, creates a safety backup, restores, verifies, and reports recoverability.

- [ ] **Step 5: Add daily stable-check timer**

Timer runs once daily with randomized delay. It applies stable updates automatically because that is the confirmed user policy. It excludes prereleases and never upgrades MySQL.

- [ ] **Step 6: Run simulated update tests and commit**

Run: `bash -n ops/update.sh ops/rollback.sh && python -m pytest autopilot/tests/test_update_scripts.py -v`

```bash
git add ops/update.sh ops/rollback.sh systemd/danmu-update.service systemd/danmu-update.timer autopilot/tests/test_update_scripts.py
git commit -m "feat: update and roll back automatically"
```

---

### Task 17: End-to-End Tests, Player Compatibility, and Beginner Documentation

**Files:**
- Create: `autopilot/tests/integration/conftest.py`
- Create: `autopilot/tests/integration/test_end_to_end.py`
- Create: `autopilot/tests/integration/test_two_hour_compilation.py`
- Create: `autopilot/tests/integration/test_update_rollback.py`
- Create: `README.md`
- Create: `docs/initial-setup.md`
- Create: `docs/cloudflare-caddy.md`
- Create: `docs/forward-senplayer.md`
- Create: `docs/cookies-and-proxy.md`
- Create: `docs/aliases-and-filters.md`
- Create: `docs/backup-update-rollback.md`
- Create: `docs/troubleshooting.md`

**Interfaces:**
- Produces the user-facing deployment and operation path.
- Consumes every prior task.
- Produces the `stack` integration fixture with `submit_fixture()`, `wait()`, disposable Compose project naming, and automatic cleanup limited to that exact project.

- [ ] **Step 1: Write the synthetic two-hour compilation acceptance test**

```python
@pytest.mark.integration
def test_two_hour_padding_becomes_eight_zero_based_episodes(stack):
    job = stack.submit_fixture("two-hour-padding.xml", episodes=8, runtime_ms=1_260_000)
    outcome = stack.wait(job, timeout=60)
    assert outcome.confidence == "high"
    assert outcome.imported_episodes == list(range(1, 9))
    for episode in outcome.episodes:
        assert 0 <= episode.first_comment_ms < 60_000
        assert episode.last_comment_ms <= 1_320_000
```

- [ ] **Step 2: Write public-boundary and rollback acceptance tests**

Assert player API works through Caddy, admin requires Basic Auth, `/api/control` returns 404 on the player host, secrets do not appear in logs, a simulated bad Misaka image restores the prior digest and database, and local backup restore rehearsal succeeds.

- [ ] **Step 3: Run the complete automated suite**

Run: `docker build --target test -t danmu-autopilot:test autopilot && docker compose --profile test run --rm autopilot-test`

Expected: unit, policy, contract, and integration tests PASS; live source tests remain skipped unless explicitly enabled.

- [ ] **Step 4: Write the beginner path**

README must begin with: required values, one bootstrap command, two Caddy lines to import, one health command, and the exact Forward/SenPlayer API URL locations. Separate guides cover Cloudflare, Cookie export/rotation, source proxy results, filters, alias corrections, backup recovery, one-command rollback, and common no-danmaku/wrong-episode cases.

- [ ] **Step 5: Perform real closed-client compatibility checks**

On current Forward and SenPlayer versions, verify automatic match, manual search fallback, async task polling, token format, comment modes/colors, error display, three concurrent devices, and player-local offset. Record the tested app versions and date in `docs/forward-senplayer.md`; do not claim unsupported behavior.

- [ ] **Step 6: Run final repository verification**

Run: `git diff --check && docker compose config --quiet && bash -n ops/*.sh && docker build --target test -t danmu-autopilot:test autopilot`

Expected: all commands exit 0.

- [ ] **Step 7: Commit documentation and acceptance tests**

```bash
git add README.md docs autopilot/tests/integration
git commit -m "docs: complete automated danmaku deployment guide"
```

---

## Execution Checkpoints

1. **Foundation checkpoint after Task 5:** Misaka, MySQL, and transparent Gateway run securely; player behavior is unchanged even if Autopilot is disabled.
2. **Matching checkpoint after Task 9:** names, XML transforms, anomaly signals, and boundary optimizer pass synthetic tests without live source access.
3. **Automation checkpoint after Task 13:** authorized sources, persistent pipeline, source routing, Caddy, DNS dry-run, and bootstrap work end to end.
4. **Operations checkpoint after Task 16:** notification, health, backup, restore, stable update, and rollback simulations pass.
5. **Release checkpoint after Task 17:** full test suite and real Forward/SenPlayer acceptance pass, and beginner documentation matches the verified deployment.

## Final Verification Matrix

| Requirement | Verification |
| --- | --- |
| Latest stable Misaka | Fixture tests exclude prereleases; deployed image lock contains release and digest |
| No Docker Socket | Compose policy test and rendered config inspection |
| Public player API only | Caddy policy and external HTTP integration tests |
| Three concurrent Apple devices | real Forward/SenPlayer concurrency check |
| Normal automatic matching | Misaka fallback contract and end-to-end match test |
| Hidden two-hour padding | synthetic 4:48:03/8-episode acceptance fixture |
| Ads and mid-episode cuts | XML piecewise-timeline unit tests |
| Low confidence stays automatic | optimizer and pipeline policy tests |
| No access-control bypass | paid-preview adapter test and cookie-only media probe |
| Secret privacy | nested redaction, file-mode, log scan, and ingress tests |
| Overseas routing | source-by-source preflight report and proxy circuit tests |
| Automatic backup | daily timer plus manifest/hash tests |
| Real restore | temporary database weekly rehearsal |
| Automatic update | transaction-order and bad-image simulation |
| One-command rollback | named/latest rollback integration test |
| Player compatibility | dated real-device checklist for latest Forward and SenPlayer |
