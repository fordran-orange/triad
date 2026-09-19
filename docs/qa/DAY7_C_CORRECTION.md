# Cycle history correction

Independent QA found five provenance/reporting defects. Rollups now preserve prior blocked states/failures, classify failed inspection work as blocked, retain known REAL/PRODUCT_BUILD identity on early failure, keep canonical SQL work linkage in usage records, and include legacy Proposal records. Selected proposal is based on actual ProductProposal/Change links, not an arbitrary last proposal. Missing historical times remain unknown. Original failed evidence is retained.

Root eight tests: seven passed in combined run; the early-identity argument edit was then completed and its failing regression passed separately. Fresh independent correction QA required.
