"""SeedanceClient — the primary entry point for the Seedance SDK."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from .asset import AssetClient
from .config import (
    BASE_URL,
    DEFAULT_MODEL,
    DURATION_AUTO,
    FAST_MODEL,
    INCLUDE_RAW,
    LEGACY_MODEL,
    MODELS,
    OUTPUT_FORMATS,
    PAGE_SIZE_MAX,
    POLL_TIMEOUT,
    RATIO_AUTO,
    SUBMIT_TIMEOUT,
    TASK_TYPE_AUTO,
    TASK_TYPE_EDIT,
    TASK_TYPE_EXTEND,
    TASK_TYPE_FIRST_FRAME,
    TASK_TYPE_REFERENCE,
    TASK_TYPES,
    TERMINAL_STATUSES,
    TOS_DEFAULT_BUCKET,
    TOS_ENDPOINT,
    TOS_REGION,
    __version__,
    detect_task_intent,
    is_seedance_25,
    model_caps,
    resolve_model,
)
from .credentials import load_api_key, load_asset_credentials, load_mediakit_api_key
from .exceptions import ValidationError
from .http import (
    extract_nested,
    extract_output_field,
    extract_video_url,
    request_with_retry,
)
from .mediakit import MediaKitClient
from .tos import TOSClient
from .types import (
    AssetGroupResult,
    AssetResult,
    GenerateResult,
    TaskResult,
    TOSUploadResult,
    UpscaleResult,
)

logger = logging.getLogger("seedance")


class SeedanceClient:
    """Client for BytePlus Seedance video generation (2.5 by default, 2.0 opt-in).

    Credentials are resolved in priority order: explicit args → env vars →
    ~/.seedance/credentials file → legacy ark_api_key.txt.

    Usage:
        client = SeedanceClient()   # picks up creds automatically
        result = client.generate(prompt="A sunrise over mountains", ratio="16:9")
        print(result.task_id)

        # Seedance 2.5 video editing / extension
        result = client.submit_video_edit(
            "Video edit: remove everyone in @Video1 except the protagonist.",
            video_urls=["https://example.com/clip.mov"],
        )
    """

    def __init__(
        self,
        api_key: str | None = None,
        ak: str | None = None,
        sk: str | None = None,
        *,
        mediakit_api_key: str | None = None,
        profile: str = "default",
    ) -> None:
        self._api_key_override = api_key
        self._ak_override = ak
        self._sk_override = sk
        self._mediakit_key_override = mediakit_api_key
        self._profile = profile

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api_key(self) -> str:
        return load_api_key(self._api_key_override, profile=self._profile)

    def _asset_client(self) -> AssetClient:
        ak, sk = load_asset_credentials(self._ak_override, self._sk_override, profile=self._profile)
        return AssetClient(ak, sk)

    def _mediakit_client(self) -> MediaKitClient:
        return MediaKitClient(load_mediakit_api_key(self._mediakit_key_override, profile=self._profile))

    def _tos_client(self) -> TOSClient:
        # TOS reuses the same IAM access keys (ARK_AK / ARK_SK) as the asset library.
        ak, sk = load_asset_credentials(self._ak_override, self._sk_override, profile=self._profile)
        return TOSClient(ak, sk)

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _http(
        self,
        path: str,
        *,
        method: str,
        payload: dict[str, Any] | None = None,
        timeout: int = POLL_TIMEOUT,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        return request_with_retry(
            f"{BASE_URL}{path}",
            method=method,
            headers=self._auth_headers(),
            payload=payload,
            timeout=timeout,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _cid() -> str:
        return str(uuid.uuid4())[:8]

    @staticmethod
    def _maybe_raw(resp: dict[str, Any]) -> dict[str, Any]:
        return {"raw": resp} if INCLUDE_RAW else {}

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _pick_model(model: str = "", fast_mode: bool = False) -> str:
        """Resolve the model ID from an explicit selection and/or fast_mode.

        fast_mode wins over an explicit model: there is no Seedance 2.5 fast
        variant, so fast_mode always resolves to the 2.0 fast model.
        """
        if fast_mode:
            return FAST_MODEL
        return resolve_model(model)

    @staticmethod
    def _infer_task_type(
        task_type: str,
        *,
        first_frame_url: str = "",
        last_frame_url: str = "",
    ) -> str:
        """Normalise the caller's task_type hint.

        A first-frame URL is decisive — the API classifies by content role
        before it ever looks at the prompt — so it overrides 'auto'.
        """
        if task_type not in TASK_TYPES:
            raise ValidationError(
                f"Invalid task_type {task_type!r}. Must be one of: "
                f"{', '.join(sorted(TASK_TYPES))}"
            )
        if first_frame_url or last_frame_url:
            return TASK_TYPE_FIRST_FRAME
        return task_type

    @staticmethod
    def _resolve_ratio(
        ratio: str,
        task_type: str,
        model: str,
        *,
        has_video_refs: bool = False,
    ) -> str:
        """Turn the 'auto' sentinel into a concrete ratio, and reject ratios
        that the task type forbids.

        Seedance 2.5 locks the output ratio to the source material for
        first-frame, edit, and extend tasks — those accept only 'adaptive'.
        Rejecting here converts an asynchronous InvalidParameter.TaskTypeConstraint
        failure (returned minutes later, after the task is consumed) into an
        immediate error.

        When reference videos are present the task type is not knowable up front
        — the model picks between reference-to-video, edit, and extend by reading
        the prompt. 'adaptive' is the only value legal under all three, and it is
        also the API's own default, so 'auto' resolves to it rather than to 16:9.
        Defaulting to a concrete ratio there would turn a request that would have
        worked into a guaranteed asynchronous failure.
        """
        caps = model_caps(model)
        adaptive_only = task_type in caps.get("adaptive_only_task_types", [])

        if ratio == RATIO_AUTO or not ratio:
            if adaptive_only:
                return "adaptive"
            if has_video_refs and caps.get("adaptive_only_task_types"):
                return "adaptive"
            return "16:9"
        if adaptive_only and ratio != "adaptive":
            raise ValidationError(
                f"ratio must be 'adaptive' for {task_type} tasks on {model} — got {ratio!r}. "
                "The output ratio is locked to the source image or video. "
                "Pass ratio='adaptive' or leave it unset."
            )
        if ratio not in caps["ratios"]:
            raise ValidationError(
                f"Invalid ratio {ratio!r}. Must be one of: {', '.join(sorted(caps['ratios']))}"
            )
        return ratio

    # Which SDK method / MCP tool to point the caller at per detected intent.
    _INTENT_ENTRYPOINTS = {
        TASK_TYPE_EDIT: ("submit_video_edit()", "seedance_edit_video", "seedance edit"),
        TASK_TYPE_EXTEND: ("submit_video_extend()", "seedance_extend_video", "seedance extend"),
    }

    @classmethod
    def _guard_inferred_task_type(
        cls,
        prompt: str,
        *,
        model: str,
        ratio: str,
        duration: int,
        has_video_refs: bool,
    ) -> None:
        """Reject parameters that clash with the task type the model will infer.

        Only applies when the caller did not declare a task_type and reference
        videos are present — that is the exact situation where Seedance reads the
        prompt to choose between reference-to-video, editing, and extension, and
        reports a clash asynchronously.

        Deliberately advisory: an intent is only an error when the parameters
        actually violate that task type's constraints, so a false positive on an
        otherwise-valid request costs nothing.
        """
        if not has_video_refs or not model_caps(model).get("adaptive_only_task_types"):
            return

        for task_type, matched in detect_task_intent(prompt):
            caps = model_caps(model)
            problems = []
            if (
                task_type in caps.get("adaptive_only_task_types", [])
                and ratio not in (RATIO_AUTO, "", "adaptive")
            ):
                problems.append(f"ratio must be 'adaptive' (got {ratio!r})")
            if (
                task_type in caps.get("auto_duration_only_task_types", [])
                and duration != DURATION_AUTO
            ):
                problems.append(f"duration must be -1 (got {duration})")
            if not problems:
                continue

            sdk_call, mcp_tool, cli_cmd = cls._INTENT_ENTRYPOINTS[task_type]
            raise ValidationError(
                f"This prompt reads as a video {task_type} task (matched {matched!r}), "
                f"which Seedance 2.5 locks: {'; '.join(problems)}. "
                f"Submitting as-is would queue the task and then fail with "
                f"InvalidParameter.TaskTypeConstraint minutes later.\n"
                f"  • If you meant to {task_type} the video, use {sdk_call} / {mcp_tool} "
                f"/ '{cli_cmd}', which set these for you.\n"
                f"  • If you meant a plain reference-to-video generation, reword the prompt "
                f"to avoid {matched!r} — the docs warn that edit/extend wording causes the "
                f"model to misclassify reference-to-video tasks."
            )

    @staticmethod
    def _warn_missing_trigger(prompt: str, task_type: str) -> str:
        """Warn when an edit/extend prompt lacks any trigger word.

        Without one the model classifies the request as reference-to-video and
        generates a brand-new clip instead of operating on the source — a silent
        wrong result rather than an error. Returns the warning text, or "".
        """
        if any(t == task_type for t, _ in detect_task_intent(prompt)):
            return ""
        examples = {
            TASK_TYPE_EDIT: "'edit the video', 'add', 'remove', 'replace', 'change'",
            TASK_TYPE_EXTEND: "'extend forward/backward', 'continue', 'continue the story'",
        }[task_type]
        warning = (
            f"Prompt contains no {task_type} trigger word ({examples}). Seedance decides the "
            f"task type from the prompt, so it will likely treat this as a plain "
            f"reference-to-video generation and produce a NEW clip instead of "
            f"{'editing' if task_type == TASK_TYPE_EDIT else 'extending'} the source. "
            f"Reword the prompt to state the operation explicitly."
        )
        logger.warning("%s", warning)
        return warning

    @staticmethod
    def _validate(
        ratio: str,
        duration: int,
        resolution: str,
        model: str,
        *,
        task_type: str = TASK_TYPE_AUTO,
        output_format: str = "",
        camerafixed: bool = False,
    ) -> None:
        """Validate the request envelope against the model's capabilities.

        `ratio` must already be resolved by _resolve_ratio.
        """
        caps = model_caps(model)
        if ratio not in caps["ratios"]:
            raise ValidationError(
                f"Invalid ratio {ratio!r}. Must be one of: {', '.join(sorted(caps['ratios']))}"
            )

        dur_min, dur_max = caps["duration_range"]
        auto_duration_only = task_type in caps.get("auto_duration_only_task_types", [])
        if auto_duration_only and duration != DURATION_AUTO:
            raise ValidationError(
                f"duration must be -1 for {task_type} tasks on {model} — got {duration}. "
                "The output duration is locked to the source video. "
                "Pass duration=-1 or leave it unset."
            )
        if duration == DURATION_AUTO:
            if not caps.get("supports_duration_auto", False):
                raise ValidationError(
                    f"duration=-1 (model-chosen) is not supported by {model}. "
                    f"Pass an integer between {dur_min} and {dur_max}."
                )
        elif not dur_min <= duration <= dur_max:
            raise ValidationError(
                f"Invalid duration {duration}. Must be {dur_min}–{dur_max}s "
                f"(or -1 to let the model choose) for model {model}."
            )

        if resolution not in caps["resolutions"]:
            raise ValidationError(
                f"Invalid resolution {resolution!r} for {model}. "
                f"Must be one of: {', '.join(caps['resolutions'])}"
            )

        if output_format:
            if not caps.get("supports_output_format", False):
                raise ValidationError(
                    f"output_format is not supported by {model} (Seedance 2.5 only)."
                )
            if output_format not in OUTPUT_FORMATS:
                raise ValidationError(
                    f"Invalid output_format {output_format!r}. "
                    f"Must be one of: {', '.join(sorted(OUTPUT_FORMATS))}"
                )

        if camerafixed and not caps.get("supports_camerafixed", False):
            raise ValidationError(f"camerafixed is not supported by {model}.")

    # ------------------------------------------------------------------
    # Payload builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_content(
        prompt: str,
        image_urls: list[str] | None = None,
        first_frame_url: str | None = None,
        last_frame_url: str | None = None,
        video_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if first_frame_url:
            content.append({"type": "image_url", "image_url": {"url": first_frame_url}, "role": "first_frame"})
        if last_frame_url:
            content.append({"type": "image_url", "image_url": {"url": last_frame_url}, "role": "last_frame"})
        for u in image_urls or []:
            content.append({"type": "image_url", "image_url": {"url": u}, "role": "reference_image"})
        for u in video_urls or []:
            content.append({"type": "video_url", "video_url": {"url": u}, "role": "reference_video"})
        for u in audio_urls or []:
            content.append({"type": "audio_url", "audio_url": {"url": u}, "role": "reference_audio"})
        return content

    @staticmethod
    def _validate_refs(
        image_urls: list[str] | None,
        video_urls: list[str] | None,
        audio_urls: list[str] | None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        """Enforce the model's all-round-reference budgets and reject empty
        entries. Reference videos and audio are URL-only (no asset upload).

        Per-clip and total media duration limits (30s each on 2.5, 15s on 2.0)
        are enforced server-side — validating them here would mean downloading
        and probing every reference.
        """
        caps = model_caps(model)
        label_text = caps["label"]
        for label, urls, limit in (
            ("image_urls", image_urls, caps["max_reference_images"]),
            ("video_urls", video_urls, caps["max_reference_videos"]),
            ("audio_urls", audio_urls, caps["max_reference_audio"]),
        ):
            if not urls:
                continue
            if not all(urls):
                raise ValidationError(f"{label} contains an empty entry.")
            if len(urls) > limit:
                raise ValidationError(
                    f"Too many {label}: {len(urls)} (max {limit} for {label_text})."
                )

    @staticmethod
    def _require_references(
        model: str,
        *,
        image_urls: list[str] | None,
        first_frame_url: str,
        last_frame_url: str,
        video_urls: list[str] | None,
        audio_urls: list[str] | None,
    ) -> None:
        """Ensure at least one reference is present.

        Seedance 2.5 accepts audio-only input; 2.0 requires at least one visual
        reference to accompany any audio.
        """
        if image_urls or first_frame_url or last_frame_url or video_urls:
            return
        if audio_urls and model_caps(model).get("supports_audio_only", False):
            return
        if audio_urls:
            raise ValidationError(
                f"{model_caps(model)['label']} does not support audio-only input. "
                "Pair audio_urls with image_urls, video_urls, or a first frame "
                "(audio-only generation requires Seedance 2.5)."
            )
        raise ValidationError(
            "Provide at least one of: image_urls, first_frame_url, "
            "first_frame_url+last_frame_url, video_urls, or audio_urls (2.5 only)."
        )

    @staticmethod
    def _extra_params(
        seed: int | None,
        camerafixed: bool,
        output_format: str = "",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if seed is not None:
            params["seed"] = seed
        if camerafixed:
            params["camerafixed"] = True
        if output_format:
            params["output_format"] = output_format
        return params

    # ------------------------------------------------------------------
    # Video generation
    # ------------------------------------------------------------------

    def submit_text_to_video(
        self,
        prompt: str,
        *,
        ratio: str = RATIO_AUTO,
        duration: int = 5,
        resolution: str = "720p",
        generate_audio: bool = False,
        fast_mode: bool = False,
        model: str = "",
        output_format: str = "",
        seed: int | None = None,
        camerafixed: bool = False,
    ) -> TaskResult:
        """Submit a text-to-video job. Returns immediately with task_id.

        Args:
            ratio: Aspect ratio, or 'auto' to let the SDK pick (16:9 here).
            duration: Seconds, or -1 to let the model choose within its range.
            model: Model ID or alias ('2.5', '2.0', '2.0-fast'). Defaults to 2.5.
            output_format: 'mp4' or 'mov' (Seedance 2.5 only).
        """
        cid = self._cid()
        model = self._pick_model(model, fast_mode)
        ratio = self._resolve_ratio(ratio, TASK_TYPE_REFERENCE, model)
        self._validate(
            ratio, duration, resolution, model,
            task_type=TASK_TYPE_REFERENCE,
            output_format=output_format,
            camerafixed=camerafixed,
        )

        payload = {
            "model": model,
            "content": self._build_content(prompt),
            "ratio": ratio,
            "duration": duration,
            "resolution": resolution,
            "generate_audio": generate_audio,
            "watermark": False,
            **self._extra_params(seed, camerafixed, output_format),
        }
        logger.info(
            "[%s] T2V | model=%s ratio=%s dur=%ss res=%s", cid, model, ratio, duration, resolution
        )
        resp = self._http(
            "/contents/generations/tasks",
            method="POST",
            payload=payload,
            timeout=SUBMIT_TIMEOUT,
            correlation_id=cid,
        )
        return TaskResult(
            task_id=resp.get("id") or resp.get("task_id", ""),
            status=resp.get("status", "queued"),
            mode="T2V",
            model=model,
            raw=resp,
        )

    def submit_image_to_video(
        self,
        prompt: str,
        *,
        image_urls: list[str] | None = None,
        first_frame_url: str = "",
        last_frame_url: str = "",
        video_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        ratio: str = RATIO_AUTO,
        duration: int = 5,
        resolution: str = "720p",
        generate_audio: bool = False,
        fast_mode: bool = False,
        model: str = "",
        output_format: str = "",
        task_type: str = TASK_TYPE_AUTO,
        seed: int | None = None,
        camerafixed: bool = False,
    ) -> TaskResult:
        """Submit a reference-to-video job (image / video / audio references).

        Returns immediately with task_id. Video and audio references are bound
        by their content[] role; to *extend* or *edit* an existing clip, pass it
        as a reference_video and describe the operation in the prompt — or use
        submit_video_extend / submit_video_edit, which apply the parameter
        constraints those task types carry.

        Args:
            ratio: Aspect ratio, or 'auto' to resolve from the task type.
            duration: Seconds, or -1 to let the model choose.
            model: Model ID or alias ('2.5', '2.0', '2.0-fast'). Defaults to 2.5.
            output_format: 'mp4' or 'mov' (Seedance 2.5 only).
            task_type: Hint used only for local validation — 'edit'/'extend'
                       apply the ratio and duration constraints those task types
                       require, catching violations before submission.
        """
        cid = self._cid()
        model = self._pick_model(model, fast_mode)

        if last_frame_url and not first_frame_url:
            raise ValidationError(
                "last_frame_url requires first_frame_url. The API does not support last-frame-only mode."
            )
        self._require_references(
            model,
            image_urls=image_urls,
            first_frame_url=first_frame_url,
            last_frame_url=last_frame_url,
            video_urls=video_urls,
            audio_urls=audio_urls,
        )
        self._validate_refs(image_urls, video_urls, audio_urls, model)

        declared_task_type = task_type
        task_type = self._infer_task_type(
            task_type, first_frame_url=first_frame_url, last_frame_url=last_frame_url
        )
        has_video_refs = bool(video_urls)
        if declared_task_type == TASK_TYPE_AUTO:
            self._guard_inferred_task_type(
                prompt, model=model, ratio=ratio, duration=duration,
                has_video_refs=has_video_refs,
            )
        ratio = self._resolve_ratio(ratio, task_type, model, has_video_refs=has_video_refs)
        self._validate(
            ratio, duration, resolution, model,
            task_type=task_type,
            output_format=output_format,
            camerafixed=camerafixed,
        )

        has_first = bool(first_frame_url)
        has_last = bool(last_frame_url)
        n = len(image_urls or [])
        nv = len(video_urls or [])
        na = len(audio_urls or [])
        mode = (
            "I2V-FirstLastFrame" if has_first and has_last
            else "I2V-FirstFrame" if has_first
            else f"V2V-Edit(vid={nv})" if task_type == TASK_TYPE_EDIT
            else f"V2V-Extend(vid={nv})" if task_type == TASK_TYPE_EXTEND
            else f"R2V-Reference(img={n},vid={nv},aud={na})"
        )

        payload = {
            "model": model,
            "content": self._build_content(
                prompt,
                image_urls=image_urls,
                first_frame_url=first_frame_url or None,
                last_frame_url=last_frame_url or None,
                video_urls=video_urls,
                audio_urls=audio_urls,
            ),
            "ratio": ratio,
            "duration": duration,
            "resolution": resolution,
            "generate_audio": generate_audio,
            "watermark": False,
            **self._extra_params(seed, camerafixed, output_format),
        }
        logger.info(
            "[%s] I2V | model=%s mode=%s ratio=%s dur=%ss res=%s",
            cid, model, mode, ratio, duration, resolution,
        )
        resp = self._http(
            "/contents/generations/tasks",
            method="POST",
            payload=payload,
            timeout=SUBMIT_TIMEOUT,
            correlation_id=cid,
        )
        return TaskResult(
            task_id=resp.get("id") or resp.get("task_id", ""),
            status=resp.get("status", "queued"),
            mode=mode,
            model=model,
            raw=resp,
        )

    def generate(
        self,
        prompt: str,
        *,
        image_url: str = "",
        image_urls: list[str] | None = None,
        first_frame_url: str = "",
        last_frame_url: str = "",
        video_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        ratio: str = RATIO_AUTO,
        duration: int = 5,
        resolution: str = "720p",
        generate_audio: bool = False,
        fast_mode: bool = False,
        model: str = "",
        output_format: str = "",
        task_type: str = TASK_TYPE_AUTO,
        seed: int | None = None,
        camerafixed: bool = False,
        asset_group_id: str = "",
        on_progress: Any = None,   # optional callback(step, detail) for CLI progress reporting
    ) -> GenerateResult:
        """High-level composite generate: auto-uploads portrait images to the asset
        library before submitting the generation job.

        Pipeline:
          1. For each plain HTTPS reference image:
               a. Create asset group once (or reuse asset_group_id)
               b. Upload the image and poll until Active
          2. Images already given as "asset://" refs skip the upload.
          3. Submit generation job.
          4. Return GenerateResult with task_id — poll check_task() to get video_url.

        `image_url` (single) and `image_urls` (list) are combined, in that order,
        so the reference tags in the prompt line up with argument order.

        The optional on_progress callback receives (step: str, detail: str) after
        each pipeline stage — used by the CLI to drive a progress display without
        coupling the SDK to Rich or any output library.
        """
        cid = self._cid()
        model = self._pick_model(model, fast_mode)

        if last_frame_url and not first_frame_url:
            raise ValidationError(
                "last_frame_url requires first_frame_url. The API does not support last-frame-only mode."
            )

        all_image_urls = [u for u in ([image_url] if image_url else []) + list(image_urls or []) if u]
        self._validate_refs(all_image_urls, video_urls, audio_urls, model)

        declared_task_type = task_type
        task_type = self._infer_task_type(
            task_type, first_frame_url=first_frame_url, last_frame_url=last_frame_url
        )
        has_video_refs = bool(video_urls)
        if declared_task_type == TASK_TYPE_AUTO:
            self._guard_inferred_task_type(
                prompt, model=model, ratio=ratio, duration=duration,
                has_video_refs=has_video_refs,
            )
        ratio = self._resolve_ratio(ratio, task_type, model, has_video_refs=has_video_refs)
        self._validate(
            ratio, duration, resolution, model,
            task_type=task_type,
            output_format=output_format,
            camerafixed=camerafixed,
        )

        steps: list[dict[str, Any]] = []
        asset_ids_used: list[str] = []
        resolved_image_urls: list[str] = []

        # --- Asset upload pipeline (only for plain HTTPS image URLs) ---
        pending_uploads = [u for u in all_image_urls if not u.startswith("asset://")]
        group_id = asset_group_id

        if pending_uploads:
            ac = self._asset_client()

            if not group_id:
                group_name = f"seedance-{cid}"
                logger.info("[%s] Creating asset group: %s", cid, group_name)
                group_id = ac.create_group(group_name, correlation_id=cid)
                steps.append({"step": "create_asset_group", "group_id": group_id, "outcome": "ok"})
                if on_progress:
                    on_progress("create_asset_group", group_id)
            else:
                steps.append({"step": "reuse_asset_group", "group_id": group_id, "outcome": "ok"})
                if on_progress:
                    on_progress("reuse_asset_group", group_id)

            def _asset_poll_cb(aid: str, status: str) -> None:
                if on_progress:
                    on_progress("asset_poll", f"{aid}:{status}")

            for url in all_image_urls:
                if url.startswith("asset://"):
                    resolved_image_urls.append(url)
                    continue
                asset_id = ac.upload_and_wait(
                    url, group_id,
                    correlation_id=cid,
                    on_poll=_asset_poll_cb,
                )
                asset_ids_used.append(asset_id)
                resolved_image_urls.append(f"asset://{asset_id}")
                steps.append({"step": "upload_asset", "asset_id": asset_id, "outcome": "Active"})
                if on_progress:
                    on_progress("upload_asset", asset_id)
        else:
            resolved_image_urls = list(all_image_urls)

        # --- Determine mode and submit ---
        has_image = bool(resolved_image_urls)
        has_first = bool(first_frame_url)
        has_last = bool(last_frame_url)
        has_av = bool(video_urls or audio_urls)

        if has_image or has_first or has_last or has_av:
            mode = (
                "I2V-FirstLastFrame" if has_first and has_last
                else "I2V-FirstFrame" if has_first
                else "R2V-Reference" if has_av
                else "I2V-Reference"
            )
            image_urls_payload = resolved_image_urls or None
        else:
            mode = "T2V"
            image_urls_payload = None

        payload = {
            "model": model,
            "content": self._build_content(
                prompt,
                image_urls=image_urls_payload,
                first_frame_url=first_frame_url or None,
                last_frame_url=last_frame_url or None,
                video_urls=video_urls,
                audio_urls=audio_urls,
            ),
            "ratio": ratio,
            "duration": duration,
            "resolution": resolution,
            "generate_audio": generate_audio,
            "watermark": False,
            **self._extra_params(seed, camerafixed, output_format),
        }

        logger.info(
            "[%s] Submitting | model=%s mode=%s ratio=%s dur=%ss res=%s",
            cid, model, mode, ratio, duration, resolution,
        )
        resp = self._http(
            "/contents/generations/tasks",
            method="POST",
            payload=payload,
            timeout=SUBMIT_TIMEOUT,
            correlation_id=cid,
        )
        task_id = resp.get("id") or resp.get("task_id", "")
        steps.append({"step": "submit_job", "task_id": task_id, "outcome": "queued"})
        if on_progress:
            on_progress("submit_job", task_id)

        return GenerateResult(
            task_id=task_id,
            status=resp.get("status", "queued"),
            mode=mode,
            model=model,
            steps=steps,
            asset_id=asset_ids_used[0] if asset_ids_used else "",
            asset_ids=asset_ids_used,
            raw=resp,
        )

    # ------------------------------------------------------------------
    # Seedance 2.5 task types: video edit and video extension
    # ------------------------------------------------------------------

    def submit_video_edit(
        self,
        prompt: str,
        video_urls: list[str],
        *,
        image_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        resolution: str = "720p",
        generate_audio: bool = True,
        model: str = "",
        output_format: str = "mov",
        seed: int | None = None,
    ) -> TaskResult:
        """Edit an existing video (Seedance 2.5 only).

        Add, remove, or replace elements in the visuals or audio of a reference
        video — e.g. "Video edit: remove everyone in @Video1 except the
        protagonist." The model picks the video to edit from the prompt, so name
        it explicitly when passing more than one.

        Ratio and duration are locked to the source video and are not settable:
        the request always sends ratio='adaptive' and duration=-1. The output may
        run up to ~0.4s shorter than the input because of input-frame handling,
        and the source video must itself be 4–30s.

        `output_format` defaults to 'mov' — the format BytePlus recommends for
        edit tasks, since its higher colour precision keeps audio and video in
        sync and survives further post-processing. Pass 'mp4' for a
        broadly-playable file instead.
        """
        model = self._pick_model(model)
        if not is_seedance_25(model):
            raise ValidationError(
                f"Video editing requires Seedance 2.5 — {model} does not support it. "
                "Pass model='2.5' or leave model unset."
            )
        if not video_urls:
            raise ValidationError("video_urls is required for a video edit task.")
        warning = self._warn_missing_trigger(prompt, TASK_TYPE_EDIT)

        result = self.submit_image_to_video(
            prompt,
            image_urls=image_urls,
            video_urls=video_urls,
            audio_urls=audio_urls,
            ratio="adaptive",
            duration=DURATION_AUTO,
            resolution=resolution,
            generate_audio=generate_audio,
            model=model,
            output_format=output_format,
            task_type=TASK_TYPE_EDIT,
            seed=seed,
        )
        result.warning = warning
        return result

    def submit_video_extend(
        self,
        prompt: str,
        video_urls: list[str],
        *,
        duration: int = DURATION_AUTO,
        image_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        resolution: str = "720p",
        generate_audio: bool = True,
        model: str = "",
        output_format: str = "mov",
        seed: int | None = None,
    ) -> TaskResult:
        """Extend an existing video forwards or backwards (Seedance 2.5 only).

        Describe the continuation in the prompt — e.g. "Extend @Video1, then
        after the window opens, enter the gallery in @Video2." The model picks
        the video to extend from the prompt.

        Ratio is locked to the source video (always sent as 'adaptive').
        Duration is settable: 4–30s, or -1 to let the model choose.

        `output_format` defaults to 'mov' for the same audio-video sync reasons
        as submit_video_edit.
        """
        model = self._pick_model(model)
        if not is_seedance_25(model):
            raise ValidationError(
                f"Video extension requires Seedance 2.5 — {model} does not support it. "
                "Pass model='2.5' or leave model unset."
            )
        if not video_urls:
            raise ValidationError("video_urls is required for a video extension task.")
        warning = self._warn_missing_trigger(prompt, TASK_TYPE_EXTEND)

        result = self.submit_image_to_video(
            prompt,
            image_urls=image_urls,
            video_urls=video_urls,
            audio_urls=audio_urls,
            ratio="adaptive",
            duration=duration,
            resolution=resolution,
            generate_audio=generate_audio,
            model=model,
            output_format=output_format,
            task_type=TASK_TYPE_EXTEND,
            seed=seed,
        )
        result.warning = warning
        return result

    # ------------------------------------------------------------------
    # Task management
    # ------------------------------------------------------------------

    def check_task(self, task_id: str) -> TaskResult:
        """Fetch current status of a task. Returns TaskResult with video_url when succeeded."""
        if not task_id:
            raise ValidationError("task_id is required.")
        cid = self._cid()
        resp = self._http(
            f"/contents/generations/tasks/{task_id}",
            method="GET",
            correlation_id=cid,
        )
        status = resp.get("status", "unknown")
        duration = extract_output_field(resp, "duration")
        return TaskResult(
            task_id=task_id,
            status=status,
            video_url=extract_video_url(resp),
            error=resp.get("error") if status in TERMINAL_STATUSES else None,
            model=str(resp.get("model") or ""),
            duration=int(duration) if isinstance(duration, (int, float)) else None,
            ratio=extract_output_field(resp, "ratio"),
            resolution=extract_output_field(resp, "resolution"),
            output_format=extract_output_field(resp, "output_format"),
            raw=resp,
        )

    def list_tasks(
        self,
        page_num: int = 1,
        page_size: int = 10,
        status_filter: str = "",
        model_filter: str = "",
    ) -> dict[str, Any]:
        """List recent tasks, optionally filtered by status and/or model.

        `model_filter` accepts an alias ('2.5') or a full model ID.
        """
        page_size = min(max(1, page_size), PAGE_SIZE_MAX)
        cid = self._cid()
        qs = f"page_num={page_num}&page_size={page_size}"
        if status_filter:
            qs += f"&filter.status={status_filter}"
        if model_filter:
            qs += f"&filter.model={resolve_model(model_filter)}"

        resp = self._http(
            f"/contents/generations/tasks?{qs}",
            method="GET",
            correlation_id=cid,
        )
        tasks = resp.get("items") or resp.get("data") or []
        return {
            "total": resp.get("total", len(tasks)),
            "page_num": page_num,
            "page_size": page_size,
            "tasks": [
                TaskResult(
                    task_id=t.get("id", ""),
                    status=t.get("status", ""),
                    video_url=extract_video_url(t),
                    model=str(t.get("model") or ""),
                    output_format=extract_output_field(t, "output_format"),
                )
                for t in tasks
            ],
        }

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        """Cancel a queued or running task."""
        if not task_id:
            raise ValidationError("task_id is required.")
        cid = self._cid()
        resp = self._http(
            f"/contents/generations/tasks/{task_id}",
            method="DELETE",
            correlation_id=cid,
        )
        return {"task_id": task_id, "cancelled": True, **self._maybe_raw(resp)}

    # ------------------------------------------------------------------
    # Video upscaling / enhancement (AI MediaKit)
    # ------------------------------------------------------------------

    def submit_video_enhance(
        self,
        video_url: str,
        *,
        tool_version: str = "standard",
        scene: str | None = None,
        resolution: str | None = None,
        resolution_limit: int | None = None,
        bitrate_level: str | None = None,
        fps: float | None = None,
        client_token: str | None = None,
        callback_args: str | None = None,
        force_new: bool = False,
    ) -> UpscaleResult:
        """Submit a video-enhancement (upscale) task. Returns immediately with task_id.

        Idempotent by default: identical parameters reuse the same task within 24h
        (via a deterministic client_token + local cache). Pass force_new=True or a
        distinct client_token to force a brand-new task.
        """
        cid = self._cid()
        resp = self._mediakit_client().submit_enhance(
            video_url,
            tool_version=tool_version,
            scene=scene,
            resolution=resolution,
            resolution_limit=resolution_limit,
            bitrate_level=bitrate_level,
            fps=fps,
            client_token=client_token,
            callback_args=callback_args,
            force_new=force_new,
            correlation_id=cid,
        )
        return UpscaleResult(
            task_id=resp.get("task_id", ""),
            status="submitted",
            request_id=resp.get("request_id", ""),
            idempotent_hit=bool(resp.get("idempotent_hit")),
            raw=resp if INCLUDE_RAW else {},
        )

    def check_enhance_task(self, task_id: str) -> UpscaleResult:
        """Fetch current status of an upscale task. Includes video_url when completed."""
        if not task_id:
            raise ValidationError("task_id is required.")
        cid = self._cid()
        resp = self._mediakit_client().get_task(task_id, correlation_id=cid)
        status = resp.get("status", "unknown")
        result = resp.get("result") or {}
        return UpscaleResult(
            task_id=resp.get("task_id", task_id),
            status=status,
            video_url=result.get("video_url") or extract_video_url(resp) or None,
            error=resp.get("error") if status == "failed" else None,
            request_id=resp.get("request_id", ""),
            duration=result.get("duration"),
            resolution=result.get("resolution"),
            fps=result.get("fps"),
            tool_version=result.get("tool_version"),
            raw=resp if INCLUDE_RAW else {},
        )

    # ------------------------------------------------------------------
    # Asset library
    # ------------------------------------------------------------------

    def create_asset_group(self, name: str, description: str = "") -> AssetGroupResult:
        if not name:
            raise ValidationError("name is required.")
        ac = self._asset_client()
        group_id = ac.create_group(name, description)
        return AssetGroupResult(group_id=group_id, name=name)

    def upload_asset(
        self,
        image_url: str,
        group_id: str,
        *,
        on_poll: Any = None,
    ) -> AssetResult:
        """Upload an image and poll until Active. Returns AssetResult."""
        if not image_url:
            raise ValidationError("image_url is required.")
        if not group_id:
            raise ValidationError("group_id is required. Call create_asset_group() first.")
        ac = self._asset_client()
        cid = self._cid()
        asset_id = ac.upload_and_wait(image_url, group_id, correlation_id=cid, on_poll=on_poll)
        return AssetResult(
            asset_id=asset_id,
            asset_ref=f"asset://{asset_id}",
            status="Active",
        )

    def get_asset(self, asset_id: str) -> AssetResult:
        """Check the status of an existing asset."""
        if not asset_id:
            raise ValidationError("asset_id is required.")
        ac = self._asset_client()
        status, resp = ac.get_asset_status(asset_id)
        error_msg = ""
        if status == "Failed":
            error_msg = (
                extract_nested(resp, "Result", "Error")
                or extract_nested(resp, "Error")
                or "unknown error"
            )
        return AssetResult(
            asset_id=asset_id,
            asset_ref=f"asset://{asset_id}",
            status=status,
            error=error_msg,
            raw=resp,
        )

    # ------------------------------------------------------------------
    # TOS object storage
    # ------------------------------------------------------------------

    def list_tos_buckets(self) -> list[dict[str, str]]:
        """List the buckets available to the configured TOS credentials."""
        return self._tos_client().list_buckets()

    def upload_to_tos(
        self,
        file_path: str,
        bucket: str = "",
        key: str = "",
        *,
        public: bool = True,
        content_type: str = "",
    ) -> TOSUploadResult:
        """Upload a local file to a TOS bucket and return its public URL.

        Args:
            file_path: Path to a local file to upload.
            bucket: Target bucket. Falls back to SEEDANCE_TOS_BUCKET if empty.
            key: Object key (path within the bucket). Defaults to the filename.
            public: Write a public-read ACL so the URL is directly fetchable.
            content_type: Override the guessed MIME type.
        """
        import mimetypes
        from pathlib import Path

        bucket = bucket or TOS_DEFAULT_BUCKET
        if not bucket:
            raise ValidationError(
                "No TOS bucket specified. Pass bucket=... or set SEEDANCE_TOS_BUCKET. "
                "Call list_tos_buckets() to see available buckets."
            )

        path = Path(file_path).expanduser()
        if not path.is_file():
            raise ValidationError(f"File not found: {file_path}")

        data = path.read_bytes()
        if not data:
            raise ValidationError(f"File is empty: {file_path}")

        key = (key or path.name).lstrip("/")
        ctype = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"

        tos = self._tos_client()
        url = tos.put_object(bucket, key, data, content_type=ctype, public=public)
        logger.info("[%s] Uploaded %s to TOS %s/%s", self._cid(), file_path, bucket, key)
        return TOSUploadResult(
            bucket=bucket,
            key=key,
            url=url,
            region=TOS_REGION,
            size=len(data),
            content_type=ctype,
        )

    # ------------------------------------------------------------------
    # Meta
    # ------------------------------------------------------------------

    def list_models(self) -> dict[str, Any]:
        return {
            "default_model": DEFAULT_MODEL,
            "fast_model": FAST_MODEL,
            "legacy_model": LEGACY_MODEL,
            "models": [
                {
                    "model_id": mid,
                    "label": caps["label"],
                    "alias": caps["alias"],
                    "resolutions": caps["resolutions"],
                    "ratios": caps["ratios"],
                    "duration_range": caps["duration_range"],
                    "reference_limits": {
                        "images": caps["max_reference_images"],
                        "videos": caps["max_reference_videos"],
                        "audio": caps["max_reference_audio"],
                        "seconds_per_clip": caps["max_reference_media_seconds"],
                        "seconds_total": caps["max_reference_media_total_seconds"],
                    },
                    "output_formats": (
                        sorted(OUTPUT_FORMATS)
                        if caps.get("supports_output_format") else ["mp4"]
                    ),
                    "features": {
                        "first_frame": caps.get("supports_first_frame", False),
                        "last_frame": caps.get("supports_last_frame", False),
                        "camerafixed": caps.get("supports_camerafixed", False),
                        "seed": caps.get("supports_seed", False),
                        "auto_duration": caps.get("supports_duration_auto", False),
                        "audio_only_input": caps.get("supports_audio_only", False),
                        "output_format": caps.get("supports_output_format", False),
                        "video_edit": is_seedance_25(mid),
                        "video_extend": is_seedance_25(mid),
                    },
                }
                for mid, caps in MODELS.items()
            ],
        }

    def ping(self) -> dict[str, Any]:
        from .credentials import credentials_configured
        status = credentials_configured(profile=self._profile)
        return {
            "status": "ok",
            "version": __version__,
            "default_model": DEFAULT_MODEL,
            "fast_model": FAST_MODEL,
            "base_url": BASE_URL,
            "credentials": status,
            "tos": {
                "region": TOS_REGION,
                "endpoint": TOS_ENDPOINT,
                "default_bucket": TOS_DEFAULT_BUCKET,
            },
        }
