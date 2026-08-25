# SACV-Tool 1.2.0

## Main fixes

- Restores reading order in single- and two-column reference lists.
- Reconstructs hanging indents, styled line fragments, page-break continuations, and wrapped DOI/URL values.
- Stops at Appendix, author biography, and “How to cite this article” boundaries.
- Removes publisher download watermarks, page headers/footers, and the audited paper's own DOI.
- Preserves each citation's real `source_page` and `source_end_page`.
- Routes scholarly works to Crossref/OpenAlex (optional PubMed), web/policy sources to HTTP/page metadata, and books/theses to mixed fallbacks.
- Adds conservative evidence states instead of treating every miss as a conflict.
- Prevents year-only evidence and low-quality DOI fragments from becoming `verified`.
- Avoids pytest's Windows temporary-directory ACL failure.

## Regression evidence

- Manually counted BIM sample: 59 extracted, 0 fatal parse records, pages 147–156.
- Published AI Magazine sample: 132 extracted, 0 fatal parse records, pages 14–19.
- Published sample contamination: 0 self-DOI, watermark, appendix, “How to cite,” or biography records.
- Automated suite: 32 tests pass twice consecutively with the same CMD command.
- Live smoke test: Crossref exact DOI verified; OpenAlex exact DOI returned matching metadata; Streamlit returned HTTP 200.
