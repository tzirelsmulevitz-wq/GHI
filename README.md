# GHI — NYCE PPO EOB filer

Files NYCE PPO (GHI) Explanation of Benefits PDFs into Google Drive and fills in
the claims tracker, running entirely in the cloud.

**How it works**

1. You download a new EOB from nyceppo.com and save it to the **GHI EOB Inbox**
   folder in Drive. The portal blocks cloud servers, so this one step stays
   with you. Only that folder is ever read.
2. A scheduled Claude cloud session follows [PROCEDURE.md](PROCEDURE.md): it
   reads each new PDF, files a renamed copy under
   `Claims by Person/<Name>/<Year> Claims/<DOS> - <Full Name> - <Provider>/`,
   fills `GHI`, `Claim #`, `GHI Paid` and `Paid To` on the matching tracker row,
   logs what it did, and emails a summary, including EOBs announced by email but
   not downloaded yet.

The Python package `ghi_eob` does the deterministic part (reading the EOB text,
naming, matching tracker rows) and produces a reviewable JSON plan; the session
applies the plan with the Google connectors. It only fills empty cells and
reports conflicts instead of overwriting them.

**Privacy.** This repository is public, so it holds no personal data. Names,
folder ids and spreadsheet ids live in a settings file in Drive; see
[`settings.example.json`](settings.example.json) for its shape. Tests use
made-up EOBs.

**Run the tests**

```bash
python3 -m unittest discover -s tests -t .
```

**Try a plan locally**

```bash
python3 -m ghi_eob plan --settings settings.json --tracker tracker.json eob.txt
```

Standard library only; Python 3.10+.
