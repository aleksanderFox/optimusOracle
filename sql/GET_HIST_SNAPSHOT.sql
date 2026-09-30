SELECT snap_id, max(dbid) over() as dbid, max(instance_number) over() as instance_number
FROM dba_hist_snapshot
WHERE begin_interval_time >= sysdate - 1
