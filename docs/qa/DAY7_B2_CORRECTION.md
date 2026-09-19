# B2 correction

Independent QA at 9bd28ad found metadata/directory calls bypassed the shared tool counter and failed UTF-8 decoding could mint progress. The corrected gateway decodes before recording successful evidence; Codex metadata and directory requests now consume the same run-wide tool allocation as file and process requests.

The three independent regression cases pass (3 passed, 6.83 seconds; logs/day7-b2-correction-root.log). Original CHANGES_REQUIRED evidence is retained in DAY7_B2_QA.md. Fresh independent QA is required for this correction.
