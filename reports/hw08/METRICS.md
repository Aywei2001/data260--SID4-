| Failure scenario | Before fix | After fix |
|---|---|---|
| Duplicate delivery | Two questions with the same correlation_id were processed at once. | Adding idempotency helped the duplicate message be skipped, allowing only the first question to be successfully processed. |
| Consumer killed mid-work | Command entered to second terminal containing PID generate by writer while it is running is entered to stop writer mid process | Restarting writer will allow the terminated process to successfully resume and complete run. |
| Poison message | Message is marked as a bad message and retried to a limit | The "bad" message is sent to dead letter topic |
| Two partitions / two consumers | Unkeyed test is successfully run and per-notice reordering is true | Keyed test is successfully run and passed: key is grocery_recall_notice_id |