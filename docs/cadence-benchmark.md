# Synthetic ten-day cadence comparison

Measured locally on 12 October 2026 against the fully merged p99 implementation (`1494246`) with Python 3.13, ten Pods in one pool and namespace, and two GMP resource queries. `PYTHONPATH=backend .venv/bin/python scripts/cadence-benchmark.py` reproduces the experiment in temporary databases without credentials or network calls. Series use varying six-decimal CPU and memory values over ten days, with explicitly synthetic UID/pool membership proof; the real collector parses the responses, publishes a compressed immutable SQLite snapshot with retained provenance, builds populated saved views, backs up the database, and prunes expired history through the public persistence interface. Machine-readable results are in [cadence-benchmark-synthetic.json](cadence-benchmark-synthetic.json).

| Measurement                                                |                300 seconds |                 60 seconds |
| ---------------------------------------------------------- | -------------------------: | -------------------------: |
| Synthetic GMP requests                                     |                          2 |                          2 |
| Resource evaluation points                                 |                     57,620 |                    288,020 |
| Saved Pod/timestamp samples                                |                     28,810 |                    144,010 |
| Encoded source response bytes                              |                  1,608,337 |                  8,032,951 |
| Synthetic collection plus publication                      |                   3.1833 s |                  15.9011 s |
| Consistent SQLite backup, one snapshot                     |            1,122,304 bytes |            5,009,408 bytes |
| Cold saved view, 1 / 5 / 10 days                           | 0.4123 / 0.3251 / 0.5429 s | 3.3101 / 2.5702 / 3.9236 s |
| Warm 10-day saved view p95, 100 reads                      |                  0.0039 ms |                  0.0038 ms |
| Encoded 10-day saved view                                  |              269,109 bytes |            1,045,180 bytes |
| Cloud calls during saved reads                             |                          0 |                          0 |
| 31-day retention: old unreferenced pruned, latest retained |                     Passed |                     Passed |

The inclusive endpoints yield approximately five times as many evaluation points and source bytes. Request count stays fixed for this small GMP batch; large source responses may require more native pages or hit upstream limits. Compressed database size grew 4.46 times for this waveform, which is not a general compression ratio. Thirty copies at this one-snapshot size are roughly 33.7 MB versus 150.3 MB; real accumulated history, retained scenario references, WAL/transient write space and upstream historical evidence add storage. Retention removes old unreferenced snapshots, preserves latest and scenario-referenced snapshots, and does not shrink the SQLite file automatically. Provision storage and backups for that retained physical high-water mark.

Cold reads parse complete compressed history before selecting a saved window, so a one-day view also pays part of the finer ten-day collection cost. Warm measurements time in-process immutable cache reads, excluding HTTP/IAP/browser/network transfer; larger windows grow serialized view bytes. Refresh timings include synthetic response generation and encoding, collector parsing, compression and publication, but exclude network delay, Google API quotas, real cluster cardinality and remote latency. A real GMP service can impose query evaluation-point or response-size limits; this experiment does not establish operational acceptance or automatic paging. There is no claim that a 60-second step eliminates CPU smoothing or captures all short memory spikes. Actual upstream enabled series and end-to-end costs require approved nonproduction testing.

Keep the 300-second default. Operators may opt into 60 seconds after confirming their workload size, upstream response limits and storage budget. Demo fixtures retain their own 1,800-second cadence; saved snapshots keep their original query semantics regardless of later configuration changes.
