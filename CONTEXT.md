# Footage Crawler

This context describes how people index and retrieve useful moments from local video footage.

## Language

**Footage Crawler**:
The local desktop application that builds and searches a Footage Library.
_Avoid_: Footage Search

**Footage Library**:
The collection of local photo and video files a person has selected for indexing and search.
_Avoid_: Database, upload collection

**Media Asset**:
An original photo or video file selected as part of a Footage Library.
_Avoid_: Source, item, footage file

**Capture Date**:
The date a Media Asset was recorded according to embedded metadata, falling back visibly to filesystem modification time when unavailable.
_Avoid_: Upload date, unspecified file date

**Indexed Moment**:
A timestamped span within a video that has searchable machine-generated descriptions and a representative frame.
_Avoid_: Clip, video result, extracted frame

**Indexed Photo**:
A photo that has searchable machine-generated descriptions and a representative preview.
_Avoid_: Still frame, image result

**Search Result**:
A ranked Media Asset represented by its highest-ranked Indexed Photo or Indexed Moment, with additional matching moments from the same video nested beneath it.
_Avoid_: Flat moment hit, keyword hit

**Indexing Job**:
One resumable run that discovers new or changed footage and produces Indexed Moments for it.
_Avoid_: Upload, scan

**Indexing Estimate**:
A live prediction of an Indexing Job's remaining duration, based on the machine's measured processing rate and the footage still outstanding.
_Avoid_: Fixed duration, hardware guess

**Storage Estimate**:
A preflight prediction of the local space an Indexing Job will require, based on discovered footage and the selected Indexing Profile.
_Avoid_: Folder size, cache size

**Indexing Profile**:
A user-selectable speed-versus-search-quality choice that determines the compatible local model, Sampling Policy, and captioning effort for the detected hardware.
_Avoid_: Hardware mode, performance preset

**Sampling Policy**:
The rule that chooses timestamps to inspect across a video, scaling sampling density with both video duration and the selected Indexing Profile.
_Avoid_: Fixed interval, frame extraction

**Rescan**:
A user-requested reconciliation of a Footage Library that indexes new or changed videos, preserves unchanged work, and identifies missing originals.
_Avoid_: Re-index, folder watch

**Setup Wizard**:
The guided first-run flow in which a person selects folders, media types, and an Indexing Profile before confirming preflight estimates.
_Avoid_: Settings, configuration form

**Search Home**:
The everyday workspace for natural-language search, library status, Rescan, and access to setup choices.
_Avoid_: Dashboard, results page

**Benchmark Suite**:
A fixed public collection of Media Assets, natural-language queries, and relevance judgments used to compare retrieval quality reproducibly.
_Avoid_: Demo library, sample footage

**Benchmark Tier**:
An immutable, nested portion of the Benchmark Suite on which candidate results are directly comparable.
_Avoid_: Random sample, partial run

**Retrieval Baseline**:
An accepted measured result on a specific Benchmark Tier against which candidate retrieval quality is judged.
_Avoid_: Leaderboard score, target guess

**Benchmark Ambiguity**:
A retrieved result that appears relevant to a query but lacks a corresponding public relevance judgment.
_Avoid_: False positive, corrected result
