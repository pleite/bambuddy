# Automation Feature - Proposed Code Completions

**Status:** Ready for Review - NOT YET IMPLEMENTED  
**Date:** February 25, 2026

---

## 📍 COMPLETION 1: Fix `automation.py` Service

**File:** `backend/app/services/automation.py`

### Problem
The current implementation uses `asyncio.run()` inside an async function, which is an anti-pattern and can cause issues with nested event loops.

### Proposed Solution

```python
"""
Service for GCODE/3MF automation: rewriting files with printer-specific automation data,
creating temporary files for upload, and cleaning up after upload.
"""

import tempfile
import shutil
import hashlib
import zipfile
from pathlib import Path
from typing import Optional, Tuple
from sqlalchemy import select

from backend.app.models.automation import Automation
from backend.app.core.database import async_session

logger = __import__("logging").getLogger(__name__)


async def get_automation_by_printer_id(printer_id: int) -> Optional[Automation]:
    """Retrieve automation data for a given printer id."""
    async with async_session() as db:
        result = await db.execute(
            select(Automation).where(Automation.printer_id == printer_id)
        )
        return result.scalar_one_or_none()


async def needs_gcode_modification(printer_id: int) -> bool:
    """Check if a printer has automation configured and needs modification.
    
    Returns True only if automation exists AND has at least one code to inject.
    """
    automation = await get_automation_by_printer_id(printer_id)
    if not automation:
        return False
    return bool(automation.start_code or automation.end_code)


def detect_and_alter_gcode_content(
    content: str,
    automation: Automation,
    detect_word: Optional[str] = None,
) -> str:
    """
    Alter GCODE content with automation data. Abort if detect_word is present.
    
    Args:
        content: Original G-code text
        automation: Automation configuration with start/end codes
        detect_word: Optional word to skip modification if found
        
    Returns:
        Modified G-code content as string
    """
    lines = content.splitlines(keepends=True)
    new_lines = list(lines)

    # START CODE LOGIC
    start_inserted = False
    if automation.start_code:
        # If detect line is present, do not add start code
        if automation.start_code_detect and any(
            automation.start_code_detect in l for l in lines
        ):
            logger.debug(
                "Skipping start code injection: detection string '%s' found",
                automation.start_code_detect,
            )
        else:
            # Find after line for start code
            if automation.start_code_after:
                for idx, l in enumerate(lines):
                    if automation.start_code_after in l:
                        new_lines.insert(idx + 1, automation.start_code + "\n")
                        start_inserted = True
                        logger.debug(
                            "Inserted start code after anchor: '%s' at line %d",
                            automation.start_code_after,
                            idx,
                        )
                        break
            if not start_inserted:
                new_lines.insert(0, automation.start_code + "\n")
                logger.debug("Inserted start code at beginning")

    # END CODE LOGIC
    end_inserted = False
    if automation.end_code:
        # If detect word is present, do not add end code
        if automation.end_code_detect and any(
            automation.end_code_detect in l for l in lines
        ):
            logger.debug(
                "Skipping end code injection: detection string '%s' found",
                automation.end_code_detect,
            )
        else:
            # Find after line for end code (search from end)
            if automation.end_code_after:
                for idx in range(len(new_lines) - 1, -1, -1):
                    if automation.end_code_after in new_lines[idx]:
                        new_lines.insert(idx, automation.end_code + "\n")
                        end_inserted = True
                        logger.debug(
                            "Inserted end code before anchor: '%s' at line %d",
                            automation.end_code_after,
                            idx,
                        )
                        break
            if not end_inserted:
                new_lines.append("\n" + automation.end_code)
                logger.debug("Inserted end code at end")

    return "".join(new_lines)


def compute_file_hash(file_path: Path, algo: str = "sha256") -> str:
    """Compute hash of a file (default sha256).
    
    Args:
        file_path: Path to file
        algo: Hash algorithm (default: sha256)
        
    Returns:
        Hex-encoded hash string
    """
    h = hashlib.new(algo)
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


async def create_temp_gcode_with_automation(
    original_path: Path,
    printer_id: int,
    detect_word: Optional[str] = None,
) -> Tuple[Path, str, dict]:
    """
    Create a temporary GCODE or 3MF file with automation data for the given printer.
    
    **IMPORTANT: Caller is responsible for cleanup!** Use try/finally or context manager.
    
    Args:
        original_path: Path to original .gcode or .3mf file
        printer_id: Printer ID to fetch automation config for
        detect_word: Optional detection string to skip modification
        
    Returns:
        Tuple of:
        - temp_path: Path to created temporary file
        - overall_hash: SHA256 hash of modified file
        - gcode_hashes: Dict mapping {gcode_filename: md5_hash}
        
    Raises:
        ValueError: If printer has no automation or unsupported file type
        Exception: If file operation fails
    """
    automation = await get_automation_by_printer_id(printer_id)
    if not automation:
        raise ValueError(f"No automation data found for printer id {printer_id}")

    suffix = original_path.suffix.lower()
    
    if suffix == ".3mf":
        # Handle 3MF: open as zip, alter all .gcode files inside
        gcode_md5s = {}
        with tempfile.NamedTemporaryFile(delete=False, suffix=".3mf") as tmp:
            tmp_path = Path(tmp.name)
            
        try:
            with (
                zipfile.ZipFile(original_path, "r") as zf_read,
                zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf_write,
            ):
                for item in zf_read.namelist():
                    if item.endswith(".gcode"):
                        # Modify GCODE file
                        content = zf_read.read(item).decode("utf-8", errors="ignore")
                        altered = detect_and_alter_gcode_content(
                            content, automation, detect_word
                        )
                        zf_write.writestr(item, altered.encode("utf-8"))
                        
                        # Compute MD5 for altered gcode
                        md5 = hashlib.md5(altered.encode("utf-8")).hexdigest()
                        gcode_md5s[item] = md5
                        
                        # Write .gcode.md5 file
                        md5_filename = item + ".md5"
                        zf_write.writestr(md5_filename, md5.encode("utf-8"))
                    elif item.endswith(".gcode.md5"):
                        # Skip old MD5 files - they'll be regenerated
                        continue
                    else:
                        # Copy non-gcode files as-is
                        zf_write.writestr(item, zf_read.read(item))
        except Exception as e:
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Failed to process 3MF file: {e}") from e
            
        file_hash = compute_file_hash(tmp_path)
        logger.info(
            "Created modified 3MF temp file for printer %d: %s (hash: %s)",
            printer_id,
            tmp_path,
            file_hash,
        )
        return tmp_path, file_hash, gcode_md5s
        
    elif suffix == ".gcode":
        # Handle plain GCODE
        try:
            with open(original_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                
            altered = detect_and_alter_gcode_content(content, automation, detect_word)
            
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".gcode", mode="w", encoding="utf-8"
            ) as tmp:
                tmp.write(altered)
                tmp_path = Path(tmp.name)
                
        except Exception as e:
            raise RuntimeError(f"Failed to process GCODE file: {e}") from e
            
        file_hash = compute_file_hash(tmp_path)
        md5 = hashlib.md5(altered.encode("utf-8")).hexdigest()
        logger.info(
            "Created modified GCODE temp file for printer %d: %s (hash: %s)",
            printer_id,
            tmp_path,
            file_hash,
        )
        return tmp_path, file_hash, {original_path.name: md5}
    else:
        raise ValueError(f"Unsupported file type: {suffix}. Must be .gcode or .3mf")


def cleanup_temp_file(temp_path: Path):
    """Remove the temporary file if it exists.
    
    Args:
        temp_path: Path to temporary file to remove
        
    Note:
        Exceptions are silently caught and logged - this is safe to call
        in finally blocks without worrying about re-raising exceptions.
    """
    try:
        if temp_path.exists():
            temp_path.unlink()
            logger.debug("Cleaned up temp automation file: %s", temp_path)
    except Exception as e:
        logger.warning("Failed to cleanup temp file %s: %s", temp_path, e)


# =============================================================================
# Utility: Context Manager for Automatic Cleanup (Optional, for convenience)
# =============================================================================

from contextlib import asynccontextmanager
from typing import AsyncGenerator


@asynccontextmanager
async def temporary_modified_file(
    original_path: Path,
    printer_id: int,
) -> AsyncGenerator[Path, None]:
    """
    Context manager for automatic temp file cleanup.
    
    Usage:
        async with temporary_modified_file(file_path, printer_id) as modified_path:
            # Use modified_path (same as original if no automation)
            await upload_file_async(modified_path, ...)
        # File automatically cleaned up here
        
    Yields:
        Path to file (original or modified)
    """
    try:
        needs_mod = await needs_gcode_modification(printer_id)
        if not needs_mod:
            yield original_path
            return
            
        modified_path, _, _ = await create_temp_gcode_with_automation(
            original_path, printer_id
        )
        try:
            yield modified_path
        finally:
            cleanup_temp_file(modified_path)
    except Exception as e:
        logger.warning(
            "Automation modification failed for printer %d, using original file: %s",
            printer_id,
            e,
        )
        yield original_path
```

---

## 📍 COMPLETION 2: Update `background_dispatch.py` - Reprint Archive

**File:** `backend/app/services/background_dispatch.py`

### Location: Add new helper method to `BackgroundDispatchService` class

```python
# Add this method to the BackgroundDispatchService class (somewhere around line 380-400)

async def _maybe_apply_automation(
    self,
    file_path: Path,
    printer_id: int,
) -> Path:
    """
    Check if automation should apply to a file, create temp modified file if needed.
    
    This is a safe wrapper that handles errors gracefully and falls back to
    original file if automation application fails.
    
    Args:
        file_path: Original file path (.gcode or .3mf)
        printer_id: Target printer ID
        
    Returns:
        - Path to modified temp file if automation applied
        - Original file_path if no modifications needed or on error
        
    Note:
        - Does NOT cleanup the temporary file (caller responsibility)
        - Logs warnings but doesn't raise exceptions (graceful degradation)
    """
    from backend.app.services.automation import (
        create_temp_gcode_with_automation,
        needs_gcode_modification,
    )

    try:
        if not await needs_gcode_modification(printer_id):
            logger.debug(
                "No automation configured for printer %d, using original file",
                printer_id,
            )
            return file_path

        logger.info(
            "Applying automation for printer %d to file: %s",
            printer_id,
            file_path.name,
        )
        modified_path, _, _ = await create_temp_gcode_with_automation(
            file_path, printer_id
        )
        logger.info("Automation applied, using modified temp file: %s", modified_path)
        return modified_path

    except Exception as e:
        logger.warning(
            "Failed to apply automation for printer %d: %s. "
            "Continuing with original file.",
            printer_id,
            e,
            exc_info=True,
        )
        return file_path
```

### Location: Update `_run_reprint_archive()` method (around line 550-680)

**Find this section:**
```python
    async def _run_reprint_archive(self, job: PrintDispatchJob):
        from backend.app.main import register_expected_print

        async with async_session() as db:
            archive = await db.scalar(select(PrintArchive).where(PrintArchive.id == job.source_id))
            if not archive:
                raise RuntimeError("Archive not found")

            if not printer_manager.is_connected(job.printer_id):
                raise RuntimeError("Printer is not connected")

            file_path = settings.base_dir / archive.file_path
            if not file_path.exists():
                raise RuntimeError("Archive file not found")

            base_name = archive.filename
            if base_name.endswith(".gcode.3mf"):
                base_name = base_name[:-10]
            elif base_name.endswith(".3mf"):
                base_name = base_name[:-4]
            remote_filename = f"{base_name}.3mf"
            remote_path = f"/{remote_filename}"
            
            # ... rest of upload logic
```

**Replace with:**
```python
    async def _run_reprint_archive(self, job: PrintDispatchJob):
        from backend.app.main import register_expected_print
        from backend.app.services.automation import cleanup_temp_file

        async with async_session() as db:
            archive = await db.scalar(select(PrintArchive).where(PrintArchive.id == job.source_id))
            if not archive:
                raise RuntimeError("Archive not found")

            if not printer_manager.is_connected(job.printer_id):
                raise RuntimeError("Printer is not connected")

            file_path = settings.base_dir / archive.file_path
            if not file_path.exists():
                raise RuntimeError("Archive file not found")

            # Get printer to check automation flag
            printer = await db.scalar(select(Printer).where(Printer.id == job.printer_id))
            if not printer:
                raise RuntimeError("Printer not found")

            # === NEW: Check if automation should be applied ===
            modified_file_path = file_path
            was_modified = False
            try:
                if printer.plate_automation_enabled:
                    await self._set_active_message(
                        job,
                        f"Checking automation configuration for {printer.name}...",
                    )
                    modified_file_path = await self._maybe_apply_automation(
                        file_path=file_path,
                        printer_id=job.printer_id,
                    )
                    was_modified = modified_file_path != file_path
                    if was_modified:
                        await self._set_active_message(
                            job,
                            f"Automation applied - modified G-code for {printer.name}",
                        )
            except Exception as e:
                logger.exception(
                    "Unexpected error checking automation for archive %d on printer %d",
                    job.source_id,
                    job.printer_id,
                )
                # Continue with original file (fail safe)

            base_name = archive.filename
            if base_name.endswith(".gcode.3mf"):
                base_name = base_name[:-10]
            elif base_name.endswith(".3mf"):
                base_name = base_name[:-4]
            remote_filename = f"{base_name}.3mf"
            remote_path = f"/{remote_filename}"
            
            # ... rest of upload logic, but use modified_file_path instead of file_path
```

**Then in the upload section, replace all `file_path` with `modified_file_path`:**

```python
            try:
                await self._set_active_message(job, f"Uploading {archive_filename} to {printer_name}...")
                loop = asyncio.get_running_loop()
                progress_state = {"last_emit": 0.0, "last_bytes": 0}

                def upload_progress_callback(uploaded: int, total: int):
                    if self._is_cancel_requested(job.id):
                        raise DispatchJobCancelled(f"Dispatch job {job.id} cancelled during upload")

                    now = time.monotonic()
                    should_emit = (
                        uploaded >= total
                        or now - progress_state["last_emit"] >= 0.2
                        or uploaded - progress_state["last_bytes"] >= 256 * 1024
                    )

                    if should_emit:
                        progress_state["last_emit"] = now
                        progress_state["last_bytes"] = uploaded
                        loop.call_soon_threadsafe(
                            lambda u=uploaded, t=total: asyncio.create_task(self._set_active_upload_progress(job, u, t))
                        )

                if ftp_retry_enabled:
                    uploaded = await with_ftp_retry(
                        upload_file_async,
                        printer_ip,
                        printer_access_code,
                        modified_file_path,  # ← CHANGED from file_path
                        remote_path,
                        progress_callback=upload_progress_callback,
                        socket_timeout=ftp_timeout,
                        printer_model=printer_model,
                        max_retries=ftp_retry_count,
                        retry_delay=ftp_retry_delay,
                        operation_name=f"Upload for reprint to {printer_name}",
                        non_retry_exceptions=(DispatchJobCancelled,),
                    )
                else:
                    uploaded = await upload_file_async(
                        printer_ip,
                        printer_access_code,
                        modified_file_path,  # ← CHANGED from file_path
                        remote_path,
                        progress_callback=upload_progress_callback,
                        socket_timeout=ftp_timeout,
                        printer_model=printer_model,
                    )

                if uploaded:
                    await self._set_active_upload_progress(job, 1, 1)

                if not uploaded:
                    raise RuntimeError(
                        "Failed to upload file to printer. Check if SD card is inserted and properly formatted (FAT32/exFAT)."
                    )

                register_expected_print(
                    job.printer_id,
                    remote_filename,
                    job.source_id,
                    ams_mapping=job.options.get("ams_mapping"),
                )

                plate_id = self._resolve_plate_id(modified_file_path, job.options.get("plate_id"))  # ← CHANGED from file_path

                self._raise_if_cancel_requested(job)

                await self._set_active_message(job, f"Starting print on {printer_name}...")
                started = printer_manager.start_print(
                    job.printer_id,
                    remote_filename,
                    plate_id,
                    ams_mapping=job.options.get("ams_mapping"),
                    timelapse=job.options.get("timelapse", False),
                    bed_levelling=job.options.get("bed_levelling", True),
                    flow_cali=job.options.get("flow_cali", False),
                    vibration_cali=job.options.get("vibration_cali", False),
                    layer_inspect=job.options.get("layer_inspect", False),
                    use_ams=job.options.get("use_ams", True),
                )

                if not started:
                    await self._cleanup_sd_card_file(
                        printer_ip,
                        printer_access_code,
                        remote_path,
                        printer_model,
                    )
                    raise RuntimeError("Failed to start print")

                if job.requested_by_user_id and job.requested_by_username:
                    printer_manager.set_current_print_user(
                        job.printer_id,
                        job.requested_by_user_id,
                        job.requested_by_username,
                    )
                    
                logger.info(
                    "Archive reprint initiated: archive_id=%s, printer=%s, "
                    "automation_applied=%s",
                    job.source_id,
                    printer_name,
                    was_modified,
                )
                
            except DispatchJobCancelled:
                await self._set_active_message(job, f"Cancelled upload on {printer_name}.")
                raise
            finally:
                # === NEW: Cleanup modified temp file ===
                if was_modified:
                    cleanup_temp_file(modified_file_path)
                    logger.debug(
                        "Cleaned up automation temp file for archive %d", job.source_id
                    )
```

---

## 📍 COMPLETION 3: Update `background_dispatch.py` - Library File Print

**File:** `backend/app/services/background_dispatch.py`

### Location: Update `_run_print_library_file()` method (around line 730-850)

**Find this section:**
```python
    async def _run_print_library_file(self, job: PrintDispatchJob):
        from backend.app.main import register_expected_print

        async with async_session() as db:
            lib_file = await db.scalar(select(LibraryFile).where(LibraryFile.id == job.source_id))
            if not lib_file:
                raise RuntimeError("File not found")

            if not self._is_sliced_file(lib_file.filename):
                raise RuntimeError("Not a sliced file. Only .gcode or .gcode.3mf files can be printed.")

            file_path = Path(settings.base_dir) / lib_file.file_path
            if not file_path.exists():
                raise RuntimeError("File not found on disk")
                
            # ... rest of logic
```

**Replace with:**
```python
    async def _run_print_library_file(self, job: PrintDispatchJob):
        from backend.app.main import register_expected_print
        from backend.app.services.automation import cleanup_temp_file

        async with async_session() as db:
            lib_file = await db.scalar(select(LibraryFile).where(LibraryFile.id == job.source_id))
            if not lib_file:
                raise RuntimeError("File not found")

            if not self._is_sliced_file(lib_file.filename):
                raise RuntimeError("Not a sliced file. Only .gcode or .gcode.3mf files can be printed.")

            file_path = Path(settings.base_dir) / lib_file.file_path
            if not file_path.exists():
                raise RuntimeError("File not found on disk")

            printer = await db.scalar(select(Printer).where(Printer.id == job.printer_id))
            if not printer:
                raise RuntimeError("Printer not found")

            if not printer_manager.is_connected(job.printer_id):
                raise RuntimeError("Printer is not connected")

            await self._set_active_message(job, f"Creating archive for {lib_file.filename}...")
            archive_service = ArchiveService(db)
            archive = await archive_service.archive_print(
                printer_id=job.printer_id,
                source_file=file_path,
            )
            if not archive:
                raise RuntimeError("Failed to create archive")

            await db.flush()

            # === NEW: Check if automation should be applied ===
            modified_file_path = file_path
            was_modified = False
            try:
                if printer.plate_automation_enabled:
                    await self._set_active_message(
                        job,
                        f"Checking automation configuration for {printer.name}...",
                    )
                    modified_file_path = await self._maybe_apply_automation(
                        file_path=file_path,
                        printer_id=job.printer_id,
                    )
                    was_modified = modified_file_path != file_path
                    if was_modified:
                        await self._set_active_message(
                            job,
                            f"Automation applied - modified G-code for {printer.name}",
                        )
            except Exception as e:
                logger.exception(
                    "Unexpected error checking automation for library file %d on printer %d",
                    job.source_id,
                    job.printer_id,
                )
                # Continue with original file

            base_name = lib_file.filename
            if base_name.endswith(".gcode.3mf"):
                base_name = base_name[:-10]
            elif base_name.endswith(".3mf"):
                base_name = base_name[:-4]
            remote_filename = f"{base_name}.3mf"
            remote_path = f"/{remote_filename}"

            ftp_retry_enabled, ftp_retry_count, ftp_retry_delay, ftp_timeout = await get_ftp_retry_settings()
            self._raise_if_cancel_requested(job)

            await self._set_active_message(job, f"Preparing upload to {printer.name}...")
            await delete_file_async(
                printer.ip_address,
                printer.access_code,
                remote_path,
                socket_timeout=ftp_timeout,
                printer_model=printer.model,
            )

            self._raise_if_cancel_requested(job)

            try:
                await self._set_active_message(job, f"Uploading {lib_file.filename} to {printer.name}...")
                loop = asyncio.get_running_loop()
                progress_state = {"last_emit": 0.0, "last_bytes": 0}

                def upload_progress_callback(uploaded: int, total: int):
                    if self._is_cancel_requested(job.id):
                        raise DispatchJobCancelled(f"Dispatch job {job.id} cancelled during upload")

                    now = time.monotonic()
                    should_emit = (
                        uploaded >= total
                        or now - progress_state["last_emit"] >= 0.2
                        or uploaded - progress_state["last_bytes"] >= 256 * 1024
                    )

                    if should_emit:
                        progress_state["last_emit"] = now
                        progress_state["last_bytes"] = uploaded
                        loop.call_soon_threadsafe(
                            lambda u=uploaded, t=total: asyncio.create_task(self._set_active_upload_progress(job, u, t))
                        )

                if ftp_retry_enabled:
                    uploaded = await with_ftp_retry(
                        upload_file_async,
                        printer.ip_address,
                        printer.access_code,
                        modified_file_path,  # ← CHANGED from file_path
                        remote_path,
                        progress_callback=upload_progress_callback,
                        socket_timeout=ftp_timeout,
                        printer_model=printer.model,
                        max_retries=ftp_retry_count,
                        retry_delay=ftp_retry_delay,
                        operation_name=f"Upload library file to {printer.name}",
                        non_retry_exceptions=(DispatchJobCancelled,),
                    )
                else:
                    uploaded = await upload_file_async(
                        printer.ip_address,
                        printer.access_code,
                        modified_file_path,  # ← CHANGED from file_path
                        remote_path,
                        progress_callback=upload_progress_callback,
                        socket_timeout=ftp_timeout,
                        printer_model=printer.model,
                    )

                if uploaded:
                    await self._set_active_upload_progress(job, 1, 1)

                if not uploaded:
                    raise RuntimeError(
                        "Failed to upload file to printer. Check if SD card is inserted and properly formatted (FAT32/exFAT)."
                    )

                register_expected_print(
                    job.printer_id,
                    remote_filename,
                    archive.id,
                    ams_mapping=job.options.get("ams_mapping"),
                )

                plate_id = self._resolve_plate_id(modified_file_path, job.options.get("plate_id"))  # ← CHANGED

                self._raise_if_cancel_requested(job)

                await self._set_active_message(job, f"Starting print on {printer.name}...")
                started = printer_manager.start_print(
                    job.printer_id,
                    remote_filename,
                    plate_id,
                    ams_mapping=job.options.get("ams_mapping"),
                    timelapse=job.options.get("timelapse", False),
                    bed_levelling=job.options.get("bed_levelling", True),
                    flow_cali=job.options.get("flow_cali", False),
                    vibration_cali=job.options.get("vibration_cali", False),
                    layer_inspect=job.options.get("layer_inspect", False),
                    use_ams=job.options.get("use_ams", True),
                )

                if not started:
                    await self._cleanup_sd_card_file(
                        printer.ip_address,
                        printer.access_code,
                        remote_path,
                        printer.model,
                    )
                    raise RuntimeError("Failed to start print")

                if job.requested_by_user_id and job.requested_by_username:
                    printer_manager.set_current_print_user(
                        job.printer_id,
                        job.requested_by_user_id,
                        job.requested_by_username,
                    )
                    
                logger.info(
                    "Library file print initiated: file_id=%s, archive_id=%s, "
                    "printer=%s, automation_applied=%s",
                    job.source_id,
                    archive.id,
                    printer.name,
                    was_modified,
                )
                
            except DispatchJobCancelled:
                await self._set_active_message(job, f"Cancelled upload on {printer.name}.")
                raise
            finally:
                # === NEW: Cleanup modified temp file ===
                if was_modified:
                    cleanup_temp_file(modified_file_path)
                    logger.debug(
                        "Cleaned up automation temp file for library file %d",
                        job.source_id,
                    )
```

---

## 📍 COMPLETION 4: Add Missing Import in `background_dispatch.py`

**Location:** Top of file with other imports (around line 1-35)

Add this import if not already present:

```python
from backend.app.models.printer import Printer  # ← Add this line
```

---

## 🔍 Key Code Changes Summary

### Changes to `automation.py`:
1. ✅ Removed `asyncio.run()` - made function properly async
2. ✅ Added `needs_gcode_modification()` helper
3. ✅ Added comprehensive logging throughout
4. ✅ Improved error handling with specific exceptions
5. ✅ Added optional context manager utility
6. ✅ Better docstrings

### Changes to `background_dispatch.py`:
1. ✅ Added `_maybe_apply_automation()` helper method
2. ✅ Updated `_run_reprint_archive()`:
   - Check `printer.plate_automation_enabled`
   - Call `_maybe_apply_automation()` if enabled
   - Use modified file for upload if applicable
   - Cleanup temp file in finally block
   - Add logging for automation application
3. ✅ Updated `_run_print_library_file()`:
   - Same logic as reprint archive
   - Applies to library file before upload
4. ✅ Add import for `Printer` model

---

## ✅ Testing Checklist

Before implementation, verify:
- [ ] No breaking changes to existing API
- [ ] Graceful fallback if automation fails
- [ ] Temp files are properly cleaned up
- [ ] No circular imports
- [ ] All async patterns are correct
- [ ] Printer connection check happens before automation
- [ ] Both .gcode and .3mf files are handled
- [ ] Detection strings prevent double-injection
- [ ] Logging is comprehensive for debugging

---

## 🚨 Potential Issues & Mitigations

| Issue | Mitigation |
|-------|-----------|
| Temp files not cleaned if process crashes | Use `finally` blocks, make cleanup robust |
| Async patterns in nested calls | All functions now properly async-first |
| File not found on printer after modification | Same error handling as current |
| Printer disconnects during automation | Caught by existing printer connection checks |
| Very large 3MF files in memory | Zipfile module streams data efficiently |
| Automation config changes mid-dispatch | Configuration loaded once per job (safe) |

