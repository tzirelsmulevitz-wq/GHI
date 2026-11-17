# EOB filing run — procedure

This is the runbook a scheduled Claude cloud session follows. The session has
the Google Drive, Google Sheets and Gmail connectors. It is started with the
Drive file id of the **settings file**; everything personal (names, folder ids,
spreadsheet ids, email) comes from that file, never from this repository.

**Ground rules**

- Never delete, move or rename the downloaded PDFs. Filing makes a renamed *copy*.
- Only write the tracker cells listed in the plan's `tracker_updates`. Never
  overwrite anything else, never add or delete rows.
- Never commit, push or write any personal data (EOB text, names, ids) into this
  repository. Work files go in a scratch directory outside the checkout.
- Process at most 25 new PDFs per run; the rest wait for the next run.
- If a step fails, log it, include it in the summary email, and carry on with the
  other files.

## 1. Set up

```bash
git clone --depth 1 https://github.com/tzirelsmulevitz-wq/ghi "$HOME/ghi"
WORK=$(mktemp -d); mkdir -p "$WORK/eobs"
```

Read the settings file with `read_file_content` (the file id is in your
prompt) and save its text exactly to `$WORK/settings.json`. Validate it with
`python3 -m json.tool "$WORK/settings.json"`.

## 2. Find new PDFs

1. Read the log: `get_values` on `log_spreadsheet_id`, range `A:B`. Column B
   holds every source file id already handled.
2. Search the inbox with `search_files`:
   `parentId = '<inbox_folder_id>' and mimeType = 'application/pdf' and createdTime > '<start_after>T00:00:00Z'`
   (follow `nextPageToken`; `excludeContentSnippets: true`).
3. Drop any file whose id is in the log. If nothing is left, go to step 6.

## 3. Read each PDF

For each new file, `read_file_content` and write the returned `fileContent`
verbatim to `$WORK/eobs/<fileId>.txt`. Keep a note of each file's title.

## 4. Make the plan

1. First pass without the tracker, to learn the service dates:
   `cd "$HOME/ghi" && python3 -m ghi_eob plan --settings "$WORK/settings.json" "$WORK"/eobs/*.txt > "$WORK/plan0.json"`
2. Take the earliest service date across all `sources[].eob.claims[].lines[].date`.
   Read column A of the tracker (`'<sheet>'!A:A`) and find the first row whose
   date starts with that date's year. Call it `START`; the last non-empty row is `END`.
3. Read the header (`'<sheet>'!A1:P1`) and the rows (`'<sheet>'!A<START>:P<END>`)
   and save `{"header": [...], "start_row": START, "values": [...]}` to
   `$WORK/tracker.json`.
4. Full plan:
   `python3 -m ghi_eob plan --settings "$WORK/settings.json" --tracker "$WORK/tracker.json" "$WORK"/eobs/*.txt > "$WORK/plan.json"`

In the plan, each `sources[]` entry is one PDF (its `source` is the Drive file
id). It is either `skipped` (not an NYCE PPO EOB) or has `filings` and
`issues`. `tracker_updates` and `tracker_issues` cover all PDFs together.

## 5. Apply the plan

**Filing** — for each filing of each source:

1. Year folder: `search_files` for
   `parentId = '<person_folder_id>' and title = '<year_folder>' and mimeType = 'application/vnd.google-apps.folder'`.
   If none, create it with `create_file`: `title` = `<year_folder>`,
   `contentMimeType` = `application/vnd.google-apps.folder`, `parentId` = the person folder.
2. Claim folder: same search/create for `<claim_folder>` inside the year folder.
3. If a file titled `<file_name>` already exists in the claim folder, record
   "already filed". Otherwise `copy_file` with `fileId` = the source id,
   `parentId` = the claim folder, `title` = `<file_name>`.

**Tracker** — for each entry in `tracker_updates`, `update_values` on the
tracker spreadsheet with `range` = the entry's `range` and `values` = `[[value]]`.

**Log** — `append_values` to the log (`A1`), one row per source:
`[today (YYYY-MM-DD), source id, source title, result, filed as, number of tracker cells changed, notes]`
where result is one of `filed`, `already filed`, `skipped: not an NYCE PPO EOB`,
`needs attention`, and notes holds that source's issues (joined with "; ").

## 6. Check for EOBs not downloaded yet

Search Gmail: `from:<notice_sender> subject:"explanation of benefits" after:<last run date>`
where the last run date is the latest date in log column A (or `start_after` if
the log is empty). Each notice snippet says "Hello <NAME>". Count notices per
person and compare with the EOBs filed for that person this run; list any person
with more notices than filed EOBs as "waiting to be downloaded".

## 7. Email a summary

Only if something happened (a file filed, a tracker change, any issue, or EOBs
waiting to be downloaded), `send_message` to `summary_email`:

- Subject: `GHI EOBs: <n> filed, <m> need attention`
- Plain-text body, short sections: **Filed** (file names), **Tracker updated**
  (row, column, new value), **Needs your attention** (every issue, verbatim),
  **Waiting to be downloaded** (person and notice date). End with a link to the log.

If nothing happened, send nothing.
