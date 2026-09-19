# B3 completed-response measurement correction

The second independent QA found raw reasoning values could overwrite validated metadata and booleans could pass integer token checks. Successful HTTP responses now retain only sanitized nonnegative integer reasoning measurements, and both HttpProvider and Runtime require exact integer input/output counts (booleans excluded). Original completed/blocked behavior is preserved. Fresh independent QA required; all prior failures remain retained.
