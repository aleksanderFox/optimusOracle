SELECT * FROM (
    SELECT    
        h.sql_id,
        h.sql_plan_hash_value,
        h.sql_exec_id,
        TO_CHAR(h.sql_exec_start, 'YYYY-MM-DD HH24:MI:SS') AS sql_start,
        MAX(DBMS_LOB.SUBSTR(t.sql_text, 200, 1)) AS sql_text,
        COUNT(*) AS total_samples,
        COUNT(*) * 10 AS estimated_elapsed_seconds,  -- 1 сэмпл ≈ 10 секунд
        MIN(h.sample_time) AS first_sample_time,
        MAX(h.sample_time) AS last_sample_time,
        h.program,
        h.module,
        MAX(h.wait_class) KEEP (DENSE_RANK LAST ORDER BY h.sample_time) AS dominant_wait_class
    FROM
        DBA_HIST_ACTIVE_SESS_HISTORY h
        LEFT JOIN DBA_HIST_SQLTEXT t
            ON t.sql_id = h.sql_id
           AND t.dbid   = h.dbid
    WHERE
        h.snap_id IN (
            :snap_id
        )
            AND h.dbid = :dbid
            AND h.instance_number = :instance_number
        AND h.sql_id IS NOT NULL
        AND h.program NOT IN ('plsqldev.exe', 'SQL Developer')
        AND h.program NOT LIKE 'oracle@%'
    GROUP BY
        h.sql_id,
        h.sql_plan_hash_value,
        h.sql_exec_id,
        h.sql_exec_start,
        h.program,
        h.module
    HAVING
        COUNT(*) >= 1  -- в AWR сэмплов меньше, чем в ASH, поэтому порог можно снизить
    ORDER BY
        estimated_elapsed_seconds DESC
)
WHERE ROWNUM <= 20
