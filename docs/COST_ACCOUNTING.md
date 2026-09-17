# Usage and cost

Usage records bind provider, model, real/simulated mode, input/output token counts, estimated USD cost, duration, WorkItem, run and agent. The dashboard sums daily usage by provider/model and displays conservative reservations separately. For cloud calls, positive configured per-million input/output rates determine estimates; absent rates block dispatch. No current market price is assumed.

Real Qwen usage comes from Ollama prompt_eval_count/eval_count. Its API bill is $0; local electricity, hardware and opportunity cost are not estimated. Simulated adapters have zero API cost and explicit fixture identity. Failed calls may have unknown billed usage: retain reservation and failure classification rather than report a confirmed free call. Provider invoices remain the billing authority.

Input reserves use a conservative byte/schema allowance, not a vendor tokenizer; provider duration is measured wall time. Real successful responses must include valid usage. Health request counts use bounded retained usage history, not a guaranteed rolling-time window. Privacy, capability, risk and availability constrain routing before price; no cheap fallback silently receives restricted work.
