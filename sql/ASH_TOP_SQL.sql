select * from (
SELECT
    h.sql_id,
    h.sql_plan_hash_value,
    h.sql_exec_id,
    to_char(h.sql_exec_start, 'YYYY-MM-DD HH24:MI:SS') as sql_start,
    s.sql_text,
    COUNT(*) AS total_samples,
    COUNT(*) AS estimated_elapsed_seconds,
    MIN(h.sample_time) AS first_sample_time,
    MAX(h.sample_time) AS last_sample_time,
    h.program,
    h.module,
    MAX(h.wait_class) KEEP (DENSE_RANK LAST ORDER BY h.sample_time) AS dominant_wait_class
FROM
    V$ACTIVE_SESSION_HISTORY h,
    v$sqlarea s
WHERE
    h.sql_id = s.sql_id
    AND h.sample_time >= SYSDATE - INTERVAL '12' HOUR
    AND h.sql_id is not null
    and s.sql_text not like 'DECLARE job BINARY_INTEGER%'
    AND program NOT IN ('plsqldev.exe', 'SQL Developer')
    AND program NOT LIKE 'oracle@%'
GROUP BY
    h.sql_id,
    h.sql_plan_hash_value,
    h.sql_exec_id,
    h.sql_exec_start,
    s.sql_text,
    h.program,
    h.module
HAVING
    COUNT(*) >= 10
ORDER BY
    estimated_elapsed_seconds DESC
) t
where rownum <= 20
