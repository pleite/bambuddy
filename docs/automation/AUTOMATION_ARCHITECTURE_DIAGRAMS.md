# Automation Feature - Architecture & Integration Diagrams

**Date:** February 25, 2026

---

## 🏗️ Current Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          API Routes                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  POST /archives/{archive_id}/reprint                           │
│  ├─ Validates archive ownership/permissions                    │
│  ├─ Calls: background_dispatch.dispatch_reprint_archive()     │
│  └─ Returns: dispatch job info                                 │
│                                                                   │
│  POST /library/files/{file_id}/print                           │
│  ├─ Validates printer access/permissions                       │
│  ├─ Calls: background_dispatch.dispatch_print_library_file()  │
│  └─ Returns: dispatch job info                                 │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│              Background Dispatch Service                         │
│  (Handles async upload + print start)                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  _dispatcher_loop()                                             │
│  ├─ Dequeue PrintDispatchJob                                   │
│  └─ Execute: _run_reprint_archive() or _run_print_library()   │
│                                                                   │
│  ┌── _run_reprint_archive() ──┐                               │
│  │ 1. Get archive metadata    │                               │
│  │ 2. Prepare remote filename │                               │
│  │ 3. DELETE old file on SD   │ [❌ NO AUTOMATION YET]        │
│  │ 4. UPLOAD to printer       │                               │
│  │ 5. START print             │                               │
│  └────────────────────────────┘                               │
│                                                                   │
│  ┌─ _run_print_library() ────┐                                │
│  │ 1. Get library file        │                               │
│  │ 2. CREATE archive          │                               │
│  │ 3. Prepare remote filename │ [❌ NO AUTOMATION YET]        │
│  │ 4. DELETE old file on SD   │                               │
│  │ 5. UPLOAD to printer       │                               │
│  │ 6. START print             │                               │
│  └────────────────────────────┘                               │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│                   FTP Upload Service                             │
│  (Handles low-level file transfer to printer)                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  upload_file_async()      - Upload file to printer             │
│  delete_file_async()      - Remove file from printer           │
│  get_ftp_retry_settings() - Get retry configuration            │
│  with_ftp_retry()         - Wrapper for automatic retries      │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                             ↓
                      [Printer SD Card]
```

---

## 🎯 Proposed Architecture with Automation

```
┌─────────────────────────────────────────────────────────────────┐
│                          API Routes                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  POST /archives/{archive_id}/reprint                           │
│  └─ Calls: background_dispatch.dispatch_reprint_archive()     │
│                                                                   │
│  POST /library/files/{file_id}/print                           │
│  └─ Calls: background_dispatch.dispatch_print_library_file()  │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│              Background Dispatch Service (UPDATED)               │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌── _run_reprint_archive() ──────────┐                        │
│  │ 1. Get archive metadata            │                        │
│  │ 2. Get printer config              │                        │
│  │ 3. ┌─ NEW: CHECK AUTOMATION ────┐  │                        │
│  │    │ IF printer.plate_automation │  │                        │
│  │    │   _enabled == True:          │  │                        │
│  │    │   → Call automation service  │  │                        │
│  │    │   → Get modified temp file   │  │                        │
│  │    │   → Track cleanup needed    │  │                        │
│  │    └────────────────────────────┘  │                        │
│  │ 4. Prepare remote filename         │                        │
│  │ 5. DELETE old file on SD           │                        │
│  │ 6. UPLOAD (modified or original)   │                        │
│  │ 7. START print                     │                        │
│  │ 8. ┌─ NEW: CLEANUP ─────────────┐  │                        │
│  │    │ IF temp file was created:   │  │                        │
│  │    │   → Delete temp file        │  │                        │
│  │    └────────────────────────────┘  │                        │
│  └────────────────────────────────────┘                        │
│                                                                   │
│  ┌─ _run_print_library_file() ────────┐                        │
│  │ 1. Get library file metadata       │                        │
│  │ 2. Get printer config              │                        │
│  │ 3. CREATE archive                  │                        │
│  │ 4. ┌─ NEW: CHECK AUTOMATION ────┐  │                        │
│  │    │ IF printer.plate_automation │  │                        │
│  │    │   _enabled == True:          │  │                        │
│  │    │   → Call automation service  │  │                        │
│  │    │   → Get modified temp file   │  │                        │
│  │    │   → Track cleanup needed    │  │                        │
│  │    └────────────────────────────┘  │                        │
│  │ 5. Prepare remote filename         │                        │
│  │ 6. DELETE old file on SD           │                        │
│  │ 7. UPLOAD (modified or original)   │                        │
│  │ 8. START print                     │                        │
│  │ 9. ┌─ NEW: CLEANUP ─────────────┐  │                        │
│  │    │ IF temp file was created:   │  │                        │
│  │    │   → Delete temp file        │  │                        │
│  │    └────────────────────────────┘  │                        │
│  └────────────────────────────────────┘                        │
│                         ↓ (NEW)                                 │
│  ┌────────────────────────────────────┐                        │
│  │ _maybe_apply_automation()          │                        │
│  │ (NEW helper method)                │                        │
│  │ 1. Check if auto needed            │                        │
│  │ 2. Call automation.service         │                        │
│  │ 3. Return temp path (or original)  │                        │
│  │ 4. Handle errors gracefully        │                        │
│  └────────────────────────────────────┘                        │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                             ║
        ┌────────────────────╨────────────────────┐
        │                                         │
        ↓ (NEW connection)                        ↓
┌─────────────────────────┐       ┌──────────────────────────────┐
│  Automation Service     │       │    FTP Upload Service        │
│  (automation.py)        │       │  (bambu_ftp.py)              │
├─────────────────────────┤       ├──────────────────────────────┤
│                         │       │                              │
│ • get_automation_... () │       │ • upload_file_async()       │
│                         │       │ • delete_file_async()       │
│ • needs_gcode_mod...()  │       │ • with_ftp_retry()          │
│                         │       │                              │
│ • detect_and_alter...() │       │                              │
│                         │       │                              │
│ • create_temp_gcode...()│ ─────→  Uses original or modified  │
│                         │   (returns file)                    │
│ • cleanup_temp_file()   │       │                              │
│                         │       │                              │
└─────────────────────────┘       └──────────────────────────────┘
                                                ↓
                                        [Printer SD Card]
```

---

## 📊 Data Flow: Reprint Archive with Automation

```
User Input
└─ POST /archives/123/reprint?printer_id=5
   (with optional: ams_mapping, plate_id, etc.)
   
   ↓
   
API Route Handler (routes/archives.py)
├─ Validate archive exists (archive_id=123)
├─ Validate printer exists (printer_id=5)
├─ Validate permissions
└─ Dispatch: background_dispatch.dispatch_reprint_archive(
     archive_id=123,
     printer_id=5,
     ...options
   )
   
   ↓
   
Background Dispatch Service
├─ Create PrintDispatchJob
├─ Enqueue job in _queued_jobs deque
├─ Wake up _dispatcher_loop()
└─ Return immediately to user
   
   ↓
   
Background: _dispatcher_loop() (async/concurrent)
├─ Dequeue job
├─ Call: _run_reprint_archive(job)
│  │
│  ├─ [1] db.scalar() → get PrintArchive
│  │
│  ├─ [2] db.scalar() → get Printer
│  │      ✓ printer.plate_automation_enabled = True/False
│  │
│  ├─ [3] IF plate_automation_enabled:
│  │      │
│  │      ├─ Call: _maybe_apply_automation(file_path, printer_id)
│  │      │  │
│  │      │  ├─ Call: automation.needs_gcode_modification(printer_id)
│  │      │  │  │
│  │      │  │  ├─ db → get Automation record
│  │      │  │  └─ RETURN: True/False
│  │      │  │
│  │      │  ├─ IF True:
│  │      │  │  │
│  │      │  │  ├─ Call: create_temp_gcode_with_automation(
│  │      │  │  │   file_path,
│  │      │  │  │   printer_id
│  │      │  │  │ )
│  │      │  │  │  │
│  │      │  │  │  ├─ db → get Automation config
│  │      │  │  │  │
│  │      │  │  │  ├─ Open original file (3MF or GCODE)
│  │      │  │  │  │
│  │      │  │  │  ├─ FOR EACH gcode section:
│  │      │  │  │  │  ├─ Read gcode content
│  │      │  │  │  │  ├─ detect_and_alter_gcode_content()
│  │      │  │  │  │  │  ├─ Check if start_code_detect marker exists
│  │      │  │  │  │  │  ├─ IF NOT: inject start_code at anchor
│  │      │  │  │  │  │  ├─ Check if end_code_detect marker exists
│  │      │  │  │  │  │  ├─ IF NOT: inject end_code at anchor
│  │      │  │  │  │  │  └─ RETURN modified gcode
│  │      │  │  │  │  │
│  │      │  │  │  │  ├─ Write modified gcode to temp ZIP
│  │      │  │  │  │  ├─ Compute MD5 of modified gcode
│  │      │  │  │  │  └─ Write .gcode.md5 file
│  │      │  │  │  │
│  │      │  │  │  ├─ Write non-gcode files as-is
│  │      │  │  │  ├─ Skip old .gcode.md5 files
│  │      │  │  │  │
│  │      │  │  │  ├─ Compute SHA256 of temp 3MF
│  │      │  │  │  │
│  │      │  │  │  └─ RETURN: (temp_path, hash, md5_dict)
│  │      │  │  │
│  │      │  │  └─ modified_file_path = temp_path
│  │      │  │      was_modified = True
│  │      │  │
│  │      │  └─ CATCH exceptions:
│  │      │     ├─ Log warning
│  │      │     ├─ modified_file_path = original file_path
│  │      │     └─ was_modified = False (graceful fallback)
│  │      │
│  │      └─ ELSE:
│  │         └─ modified_file_path = original file_path
│  │            was_modified = False
│  │
│  ├─ [4] DELETE old file from printer SD (FTP)
│  │
│  ├─ [5] UPLOAD file to printer (FTP)
│  │      ✓ Using: modified_file_path (not original)
│  │      ✓ With progress callbacks
│  │
│  ├─ [6] register_expected_print() → main.py
│  │      (Track print to avoid duplicate archive)
│  │
│  ├─ [7] START print via printer_manager
│  │      ✓ Using: remote_filename, plate_id, options
│  │
│  ├─ [8] FINALLY block:
│  │      IF was_modified:
│  │         └─ automation.cleanup_temp_file(modified_file_path)
│  │            ├─ Try to delete temp file
│  │            └─ Log any cleanup errors (swallow exception)
│  │
│  └─ EMIT WebSocket event → Frontend
│     └─ "dispatch_updated" with status
│
└─ Repeat for next queued job
```

---

## 🔄 Data Flow: Print Library File with Automation

```
User Input
└─ POST /library/files/42/print?printer_id=5
   
   ↓
   
API Route Handler (routes/library.py)
├─ Validate library file exists (file_id=42)
├─ Validate printer exists (printer_id=5)
├─ Dispatch: background_dispatch.dispatch_print_library_file(
     file_id=42,
     printer_id=5,
     ...options
   )
   
   ↓
   
Background Dispatch (enqueue + return immediately)
   
   ↓
   
Background: _run_print_library_file(job)
├─ [1] db.scalar() → get LibraryFile (file_id=42)
├─ [2] Validate it's sliced (.gcode or .gcode.3mf)
├─ [3] Get file path from disk
├─ [4] db.scalar() → get Printer config
│      ✓ printer.plate_automation_enabled = True/False
├─ [5] archive_service.archive_print()
│      ├─ Create PrintArchive record
│      └─ Copy file to archive location
├─ [6] IF plate_automation_enabled:
│      │
│      └─ Call: _maybe_apply_automation(file_path, printer_id)
│         └─ [Same automation flow as reprint above]
│
├─ [7] DELETE old file from printer SD
├─ [8] UPLOAD file to printer
│      ✓ Using: modified_file_path (or original)
├─ [9] START print
├─ [10] FINALLY block:
│       IF was_modified:
│          └─ cleanup_temp_file(modified_file_path)
│
└─ EMIT WebSocket event → Frontend
```

---

## 🔌 Integration Points

### Point 1: Reprint Archive Dispatch
```
Location: background_dispatch.py::_run_reprint_archive()
Line: ~560

Before:                          After:
├─ Get archive              ├─ Get archive
├─ Get printer              ├─ Get printer
├─ Prepare filename    →    ├─ [NEW] Check automation
├─ Delete SD file           ├─ [NEW] Apply automation if needed
├─ Upload file              ├─ Prepare filename
├─ Register print           ├─ Delete SD file
├─ Start print              ├─ Upload (modified if needed)
└─ Track user               ├─ Register print
                            ├─ Start print
                            ├─ Track user
                            └─ [NEW] Cleanup temp file

Entry:     file_path: Path, printer_id: int
Exit:      modified_file_path: Path (same as input if no modification)
Cleanup:   finally block calls cleanup_temp_file()
```

### Point 2: Library File Print Dispatch
```
Location: background_dispatch.py::_run_print_library_file()
Line: ~730

Before:                          After:
├─ Get library file         ├─ Get library file
├─ Create archive      →    ├─ Create archive
├─ Prepare filename         ├─ [NEW] Check automation
├─ Delete SD file           ├─ [NEW] Apply automation if needed
├─ Upload file              ├─ Prepare filename
├─ Register print           ├─ Delete SD file
├─ Start print              ├─ Upload (modified if needed)
└─ Track user               ├─ Register print
                            ├─ Start print
                            ├─ Track user
                            └─ [NEW] Cleanup temp file

Entry:     file_path: Path (from LibraryFile), printer_id: int
Exit:      modified_file_path: Path (same as input if no modification)
Cleanup:   finally block calls cleanup_temp_file()
```

---

## 🌳 Dependency Graph

```
API Routes (archives.py, library.py)
    ↓
Background Dispatch Service (*)
    ├─ imports: FTP service
    ├─ imports: Printer Manager
    ├─ imports: Archive Service
    ├─ imports: [NEW] Automation Service
    └─ imports: Database models
    
    ↓
    
┌─────────────────────────────────────────────────────┐
│ Automation Service (automation.py) - NO DEPS        │
├─────────────────────────────────────────────────────┤
│  • Only imports: models.automation, database        │
│  • No circular imports                              │
│  • No dependency on dispatch/routes                 │
│  • Pure service layer - reusable                    │
└─────────────────────────────────────────────────────┘

(*) The dispatch service becomes the orchestrator:
    - Calls automation service when needed
    - Owns cleanup responsibility
    - Handles error propagation
```

---

## ⏱️ Timeline: Request to Print Execution

```
t=0ms    User clicks "Reprint"
         └─ POST /archives/{id}/reprint

t=10ms   API validates, dispatches job
         └─ background_dispatch.dispatch_reprint_archive()
         └─ Returns immediately with job_id

t=15ms   User gets response ✓
         
t=50ms   Background dispatcher awakens
         └─ Dequeues job
         └─ Starts _run_reprint_archive()
         
t=60ms   Get archive metadata
         
t=70ms   Get printer config
         
t=80ms   [NEW] Check automation_enabled flag
         └─ IF True: async get Automation record
         
t=100ms  [NEW] IF automation needed:
         └─ Read original file (~500KB → few ms)
         └─ Parse and modify G-code (~50ms for 10K lines)
         └─ Create temp 3MF file (~100ms for large file)
         
t=150ms  (Without automation: skip to here)
         Delete old file from printer SD (FTP, ~1s)
         
t=1150ms Upload file to printer (FTP)
         └─ 5MB file at ~5-10MBps → ~500-1000ms
         └─ Progress emitted every 256KB
         
t=1650ms Register as expected print
         
t=1660ms Send start_print command
         
t=1680ms [NEW] CLEANUP: Delete temp file from /tmp
         
t=1690ms Complete!
         └─ WebSocket: "dispatch_completed"
         
         Total with automation: ~1700ms
         Total without automation: ~1600ms
         (Automation overhead: ~100ms for typical 5MB file)
```

---

## 🛡️ Error Handling Paths

```
Apply Automation
    │
    ├─ NO (automation_enabled=False or no config)
    │  └─ Use original file
    │
    ├─ YES → get_automation_by_printer_id() fails
    │  └─ Log warning → Use original file (graceful)
    │
    ├─ YES → create_temp_gcode_with_automation() throws
    │  └─ Log error → Use original file (graceful)
    │  └─ Continue upload with original
    │
    ├─ YES → Temp file created successfully ✓
    │  │
    │  ├─ Upload fails
    │  │  └─ Cleanup temp → Raise error
    │  │
    │  ├─ Upload succeeds
    │  │  └─ Print starts
    │  │  └─ Cleanup temp in finally
    │  │
    │  └─ Cancel requested during upload
    │     └─ Cleanup temp → Raise DispatchJobCancelled
    │
    └─ Cleanup phase
       └─ Delete temp file (exception-safe)
```

